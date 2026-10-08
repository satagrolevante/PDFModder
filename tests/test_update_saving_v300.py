"""Updates resolve every real PDF session before the installer handoff."""
from hashlib import sha256
from types import SimpleNamespace

from pypdf import PdfReader
import pytest

from pdfmodder import updates_v170 as updates
from pdfmodder import workspace_ui_v170 as workspace
from test_saving_v300 import (saving_window, make_pdf, open_editing,
                              change_metadata, start_draft, finished)


class PendingInstaller:
    """Hold the external installer boundary while exercising real PDF work."""
    def __init__(self):
        self.calls = []
        self.value = {'state': 'ready', 'busy': False, 'installedVersion': '3.0.0',
                      'latestVersion': '3.0.1', 'message': 'Instalador descargado', 'progress': 100}

    def status(self):
        return dict(self.value)

    def install(self, **options):
        self.calls.append(options)
        self.value.update(state='verifying', busy=True)
        return True

    def cancel(self):
        self.value.update(state='cancelled', busy=False)


def update_dialog(qtbot, monkeypatch, window, updater):
    monkeypatch.setattr(workspace, 'detected_installation_directory', lambda **_: None)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.timer.stop()
    return dialog


@pytest.mark.parametrize('choice', ['cancel', 'discard'])
def test_update_cancel_or_discard_preserves_sessions_until_installer_handoff(
        qtbot, saving_window, tmp_path, monkeypatch, choice):
    window = saving_window
    first = open_editing(qtbot, window, make_pdf(tmp_path / 'first.pdf'))
    change_metadata(qtbot, window, 'Primera pestaña pendiente')
    second = open_editing(qtbot, window, make_pdf(tmp_path / 'second.pdf'))
    start_draft(qtbot, window, 'Fecha 11/09/2026')
    tabs = dict(window._session_paths_v200)
    revision = window.state['document_revision']
    questions = []
    def answer(entries, *, app):
        questions.append(({entry['session_id'] for entry in entries}, app))
        return choice
    monkeypatch.setattr(window, '_ask_close_v300', answer)
    updater = PendingInstaller()
    dialog = update_dialog(qtbot, monkeypatch, window, updater)
    commands = []
    window.operation_finished.connect(lambda command, _: commands.append(command))
    dialog._install()
    assert not updater.calls
    finished(qtbot, window)
    qtbot.waitUntil(lambda: not dialog._preparing_work_v300, timeout=30000)
    assert questions == [({first, second}, True)]
    assert window._session_paths_v200 == tabs and window._active_session_v200 == second
    assert window.canvas.editor.isVisible() and window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'
    assert window.state['document_revision'] == revision and window.state['history_index'] == 0
    assert window.isVisible() and not window._closed and not window._allow_close
    assert 'close_all' not in commands and 'close_session' not in commands
    if choice == 'cancel':
        assert not updater.calls and updater.status()['state'] == 'ready'
    else:
        assert len(updater.calls) == 1 and updater.status()['state'] == 'verifying'
        # A rejected installer still leaves the discarded work recoverable:
        # approval to close does not destroy sessions before verified handoff.
        updater.value.update(state='error', busy=False, message='SHA-256 no coincide')
        dialog._refresh()
        assert window.isVisible() and window._session_paths_v200 == tabs
        assert window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'
    dialog.reject()


def test_update_saves_inactive_draft_and_active_document_before_installing(
        qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    first_source = make_pdf(tmp_path / 'inactive.pdf')
    first_bytes = first_source.read_bytes()
    first = open_editing(qtbot, window, first_source)
    selections = []
    assert window._submit('rich_selection', {'page': 0, 'ids': [g.id for g in window.model.glyphs]}, selections.append)
    finished(qtbot, window)
    payload = selections[0]
    payload['runs'] = [dict(payload['runs'][0], text='Fecha 12/09/2026')]
    payload.update(auto_width=True, auto_height=True)
    second_source = make_pdf(tmp_path / 'active.pdf')
    second_bytes = second_source.read_bytes()
    second = open_editing(qtbot, window, second_source)
    change_metadata(qtbot, window, 'Metadatos antes de actualizar')
    assert window._submit('store_draft', {'session_id': first,
        'draft': {'kind': 'rich', 'payload': payload}, 'workspace': {}, '_background_ui': True})
    finished(qtbot, window)
    outputs = {first: tmp_path / 'saved-inactive.pdf', second: tmp_path / 'saved-active.pdf'}
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'save')
    monkeypatch.setattr(window, '_choose_destinations_v300', lambda _: outputs)
    updater = PendingInstaller()
    dialog = update_dialog(qtbot, monkeypatch, window, updater)
    commands = []
    window.operation_finished.connect(lambda command, _: commands.append(command))
    dialog._install()
    assert not updater.calls
    qtbot.waitUntil(lambda: bool(updater.calls), timeout=60000)
    finished(qtbot, window)
    assert 'Fecha 12/09/2026' in PdfReader(outputs[first]).pages[0].extract_text()
    assert PdfReader(outputs[second]).metadata.title == 'Metadatos antes de actualizar'
    assert first_source.read_bytes() == first_bytes and second_source.read_bytes() == second_bytes
    assert window._active_session_v200 == second and window.state['session_id'] == second
    assert not window.state['dirty'] and not window._session_views_v200[first]['state']['draft_pending']
    assert window.document_tabs_v200.count() == 2 and window.isVisible() and not window._closed
    assert 'close_all' not in commands and 'close_session' not in commands
    updater.value.update(state='installing', busy=False)
    dialog._refresh()
    assert window._closed and not window.isVisible()


@pytest.mark.parametrize('failure', ['invalid_draft', 'destination_cancel'])
def test_update_save_failure_or_destination_cancel_never_starts_installer(
        qtbot, saving_window, tmp_path, monkeypatch, failure):
    window = saving_window
    source = make_pdf(tmp_path / 'original.pdf')
    original = source.read_bytes()
    sid = open_editing(qtbot, window, source)
    start_draft(qtbot, window, 'Fecha 11/09/2026')
    destination = tmp_path / 'saved.pdf'
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'save')
    monkeypatch.setattr(window, '_choose_destinations_v300',
                        lambda _: None if failure == 'destination_cancel' else {sid: destination})
    if failure == 'invalid_draft':
        payload = window.canvas.editor.payload()
        payload.update(width=1., height=1., auto_width=False, auto_height=False, rect=[35., 80., 36., 81.])
        monkeypatch.setattr(window.canvas.editor, 'payload', lambda: payload)
    updater = PendingInstaller()
    dialog = update_dialog(qtbot, monkeypatch, window, updater)
    dialog._install()
    finished(qtbot, window, error=failure == 'invalid_draft')
    qtbot.waitUntil(lambda: not dialog._preparing_work_v300, timeout=30000)
    assert not updater.calls and not destination.exists()
    assert source.read_bytes() == original and window.state['history_index'] == 0
    assert window.canvas.editor.isVisible() and window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'
    assert window.isVisible() and not window._closed
    dialog.reject()


def test_reject_update_dialog_during_work_resolution_does_not_install(
        qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    open_editing(qtbot, window, make_pdf(tmp_path / 'pending.pdf'))
    change_metadata(qtbot, window, 'Trabajo pendiente')
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'discard')
    updater = PendingInstaller()
    dialog = update_dialog(qtbot, monkeypatch, window, updater)
    dialog._install()
    assert dialog._preparing_work_v300 and not updater.calls
    dialog.reject()
    finished(qtbot, window)
    qtbot.wait(10)  # Deliver the already queued resolution callback.
    assert not updater.calls and window.state['dirty'] and window.isVisible() and not window._closed


def test_installer_hash_failure_after_discard_keeps_real_pending_work(
        qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    sid = open_editing(qtbot, window, make_pdf(tmp_path / 'pending.pdf'))
    change_metadata(qtbot, window, 'Cambios recuperables')
    installer = tmp_path / 'installer.exe'
    payload = b'MZ synthetic installer; never executed'
    installer.write_bytes(payload)
    updater = updates.AppUpdater('3.0.0', tmp_path / 'updates')
    updater._release = {'version': '3.0.1', 'sha256': sha256(payload).hexdigest(), 'size': len(payload)}
    updater._ready_path = installer
    updater._set(state='ready')
    installer.write_bytes(b'X' * len(payload))
    monkeypatch.setattr(updates, 'os', SimpleNamespace(name='nt', fdopen=updates.os.fdopen))
    launches = []
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: launches.append(args))
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'discard')
    dialog = update_dialog(qtbot, monkeypatch, window, updater)
    dialog._install()
    qtbot.waitUntil(lambda: updater.status()['state'] == 'error' and not updater.status()['busy'], timeout=60000)
    dialog._refresh()
    assert not launches and 'SHA-256' in updater.status()['message']
    assert window._active_session_v200 == sid and window.state['dirty']
    assert window.document_tabs_v200.count() == 1 and window.isVisible() and not window._closed
    assert not window._allow_close
    dialog.reject()
