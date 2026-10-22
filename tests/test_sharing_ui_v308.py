"""Sharing uses current saved bytes and waits for the existing save workflow."""
from hashlib import sha256
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

from pdfmodder.sharing_ui_v308 import (
    ShareDialogV308, SharingUiV308Mixin, verified_share_file_v308,
)
from test_saving_v300 import saving_window, make_pdf, open_editing, start_draft, finished


class ShareWindow(SharingUiV308Mixin, QMainWindow):
    def __init__(self, source):
        super().__init__()
        self.state = {'path': str(source), 'document_revision': sha256(source.read_bytes()).hexdigest()}
        self.busy = False
        self._save_transaction_v300 = None
        self._active_session_v200 = 'document'
        self._session_views_v200 = {}
        self.shown = []
        self.errors = []

    def _entry_v300(self, sid):
        return dict(self.state, session_id=sid)

    def _begin_save_flow_v300(self):
        self._save_transaction_v300 = {'saved': [], 'error': ''}
        return True

    def _start_save_entries_v300(self, entries, destinations):
        self.saving = entries, destinations
        return True

    def _show_share_v308(self, verified):
        self.shown.append(verified[0])
        return True

    def _error(self, error):
        self.errors.append(error)


@pytest.fixture
def share_window(qtbot, tmp_path):
    source = tmp_path / 'documento.pdf'
    source.write_bytes(b'current PDF snapshot')
    window = ShareWindow(source)
    qtbot.addWidget(window)
    return window


def test_copy_file_exports_file_urls_and_rejects_later_changes(qtbot, tmp_path):
    path = tmp_path / 'Informe clínico.pdf'
    path.write_bytes(b'PDF snapshot')
    verified = verified_share_file_v308(path, sha256(path.read_bytes()).hexdigest())
    dialog = ShareDialogV308(*verified)
    qtbot.addWidget(dialog)
    dialog.copy_file()
    try:
        # Qt emits portable separators, including on Windows. Compare the
        # actual file identity, not the platform's display spelling.
        copied = QApplication.clipboard().mimeData().urls()[0].toLocalFile()
        assert Path(copied).resolve() == path.resolve()
    finally:
        QApplication.clipboard().clear()
    path.write_bytes(b'externally replaced PDF')
    dialog.copy_file()
    data = QApplication.clipboard().mimeData()
    assert data is None or not data.hasUrls()
    assert not dialog.copy_button.isEnabled()


def test_clean_document_shares_existing_verified_file_without_save(share_window):
    window = share_window
    assert window.choose_share_v308()
    assert window.shown == [Path(window.state['path'])]
    assert window._save_transaction_v300 is None


@pytest.mark.parametrize('pending', ['dirty', 'draft_pending', 'preview'])
def test_pending_changes_wait_for_successful_save(share_window, tmp_path, monkeypatch, pending):
    window = share_window
    destination = tmp_path / 'copia.pdf'
    window.state[pending] = True
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), ''))
    assert window.choose_share_v308()
    assert not window.shown
    assert window.saving[1] == {'document': str(destination)}
    # This is the save transaction completion contract, not a direct action.
    destination.write_bytes(b'validated changed PDF')
    revision = sha256(destination.read_bytes()).hexdigest()
    window._session_views_v200['document'] = {'state': {'document_revision': revision}}
    transaction = window._save_transaction_v300
    transaction['saved'].append('document')
    transaction['after'](False)
    assert window.shown == [destination]


@pytest.mark.parametrize('result', ['cancelled', 'failed'])
def test_unsuccessful_save_does_not_share_an_older_copy(share_window, tmp_path, monkeypatch, result):
    window = share_window
    window.state['dirty'] = True
    output = tmp_path / 'copia.pdf'
    output.write_bytes(b'previous copy')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), ''))
    window.choose_share_v308()
    transaction = window._save_transaction_v300
    if result == 'failed':
        transaction['error'] = 'Write failed'
    transaction['after'](False)
    assert not window.shown


def test_external_change_and_cancel_preserve_original(share_window, monkeypatch):
    window = share_window
    source = Path(window.state['path'])
    source.write_bytes(b'changed outside app')
    choices = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (choices.append(args) or ('', '')))
    assert not window.choose_share_v308()
    assert choices and not window.shown and window._save_transaction_v300 is None
    assert source.read_bytes() == b'changed outside app'


def test_real_draft_is_validated_and_saved_before_sharing(qtbot, saving_window, tmp_path, monkeypatch):
    import pymupdf as fitz
    window = saving_window
    source = make_pdf(tmp_path / 'original.pdf')
    original = source.read_bytes()
    open_editing(qtbot, window, source)
    start_draft(qtbot, window, 'Fecha 22/10/2026')
    destination = tmp_path / 'compartir.pdf'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), ''))
    shown = []
    monkeypatch.setattr(window, '_show_share_v308', lambda verified: shown.append(verified[0]), raising=False)
    assert SharingUiV308Mixin.choose_share_v308(window)
    assert not shown
    finished(qtbot, window)
    qtbot.waitUntil(lambda: bool(shown), timeout=30000)
    assert shown == [destination]
    with fitz.open(destination) as saved:
        assert '22/10/2026' in saved[0].get_text()
    assert source.read_bytes() == original
