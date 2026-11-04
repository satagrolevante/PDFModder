"""Visible progress across update phases, with no network or installer launch."""
import io
import threading

import pytest

from pdfmodder import updates_v170 as updates
from pdfmodder import workspace_ui_v170 as workspace
from test_updates_v170 import publication
from test_upgrade_v180 import SynchronousUpdater, UpdateWindow


@pytest.mark.parametrize('state', ['checking', 'validating_download', 'verifying', 'installing'])
def test_unmeasured_update_phases_keep_an_animated_bar(qtbot, state):
    window, updater = UpdateWindow(), SynchronousUpdater()
    qtbot.addWidget(window)
    updater.value.update(state=state, busy=True, progress=100, message='Fase de prueba')
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.progress.isHidden()
    assert dialog.progress.minimum() == dialog.progress.maximum() == 0
    assert not dialog.check_button.isEnabled()
    # A visible handoff bar does not grant permission to close PDF sessions.
    assert not window.closed
    dialog.reject()


def test_download_percentage_is_labelled_and_restored_after_animation(qtbot):
    window, updater = UpdateWindow(), SynchronousUpdater()
    qtbot.addWidget(window)
    updater.value.update(state='checking', busy=True)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    updater.value.update(state='downloading', busy=True, progress=43)
    dialog._refresh()
    assert not dialog.progress.isHidden()
    assert dialog.progress.maximum() == 100
    assert dialog.progress.value() == 43
    assert dialog.progress.text() == 'Descarga: 43%'
    updater.value.update(state='ready', busy=False, progress=100)
    dialog._refresh()
    assert dialog.progress.text() == 'Descarga comprobada'
    assert '100%' not in dialog.progress.text()
    dialog.reject()


def test_preparing_documents_keeps_progress_without_claiming_completion(qtbot):
    window, updater = UpdateWindow(), SynchronousUpdater()
    qtbot.addWidget(window)
    updater.value.update(state='ready', busy=False, progress=100)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    dialog._preparing_work_v300 = True
    dialog._refresh()
    assert not dialog.progress.isHidden()
    assert dialog.progress.maximum() == 0
    assert 'documentos' in dialog.message.text()
    assert not dialog.check_button.isEnabled()
    assert not window.closed
    # Cancelling the save prompt restores the download status and retry action.
    dialog._preparing_work_v300 = False
    dialog._refresh()
    assert dialog.progress.maximum() == 100
    assert dialog.check_button.isEnabled()
    dialog.reject()


@pytest.mark.parametrize('state', ['error', 'cancelled', 'current', 'unavailable', 'rate_limited'])
def test_terminal_states_stop_the_animation_and_leave_the_result_visible(qtbot, state):
    window, updater = UpdateWindow(), SynchronousUpdater()
    qtbot.addWidget(window)
    updater.value.update(state='checking', busy=True)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    updater.value.update(state=state, busy=False, message='Resultado de la comprobación')
    dialog._refresh()
    assert dialog.progress.isHidden() and dialog.progress.maximum() == 100
    assert dialog.message.text() == 'Resultado de la comprobación'
    assert not window.closed
    dialog.reject()


@pytest.mark.parametrize('cancel', [False, True])
def test_download_stays_unfinished_while_its_hash_is_being_checked(qtbot, monkeypatch, tmp_path, cancel):
    payload = b'MZ synthetic installer'
    manifest, release = publication(payload)
    selected = updates.validate_manifest(manifest, release)
    monkeypatch.setattr(updates, 'read_release', lambda *_: selected)
    monkeypatch.setattr(updates, 'open_public', lambda *_: io.BytesIO(payload))
    entered, resume = threading.Event(), threading.Event()
    verify = updates.verify_file
    def held_verification(path, information):
        entered.set()
        assert resume.wait(5), 'Verification test was not released'
        verify(path, information)
    monkeypatch.setattr(updates, 'verify_file', held_verification)
    updater = updates.AppUpdater('1.7.0', tmp_path)
    try:
        assert updater.download()
        qtbot.waitUntil(entered.is_set, timeout=3000)
        status = updater.status()
        assert status['state'] == 'validating_download' and status['busy']
        assert status['progress'] < 100
        assert not list(tmp_path.glob('*.exe'))
        if cancel:
            updater.cancel()
    finally:
        resume.set()
    qtbot.waitUntil(lambda: not updater.status()['busy'], timeout=3000)
    assert updater.status()['state'] == ('cancelled' if cancel else 'ready')
    assert not list(tmp_path.glob('*.part'))
    assert bool(list(tmp_path.glob('*.exe'))) is not cancel
