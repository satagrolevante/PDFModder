"""Explorer actions preserve selection order and keep Office work off Qt."""
from pathlib import Path
from concurrent.futures import Future

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QPlainTextEdit, QPushButton
import pymupdf
import pytest

from pdfmodder.editing_ui import MergeDialog
from pdfmodder.shell_ui_v305 import ShellActionsUiMixin


class ShellWindow(ShellActionsUiMixin, QMainWindow):
    error_raised = Signal(str)

    def __init__(self):
        super().__init__()
        self.busy = False
        self._closed = False
        self.errors = []
        self.notices = []
        self.opened = []
        self.combined = []
        self.submissions = []
        self.accept_submission = True
        self.edit_dialog = lambda dialog: QDialog.Rejected

    def _error(self, message):
        self.errors.append(message)
        self.error_raised.emit(message)

    def _notice(self, message):
        self.notices.append(message)

    def _exec_edit_dialog(self, dialog):
        return self.edit_dialog(dialog)

    def combine_pdfs(self, paths):
        self.combined.append(paths)

    def open_document(self, path):
        self.opened.append(path)
        return True

    def _submit(self, command, payload, callback):
        if not self.accept_submission:
            return False
        self._command = command
        self.submissions.append((command, payload, callback))
        self.busy = True
        return True

    def complete(self, result):
        self.busy = False
        self.submissions[-1][2](result)


@pytest.fixture
def shell_window(qtbot):
    window = ShellWindow()
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close_shell_actions_v305()


def files(tmp_path, *names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b'test source')
        paths.append(str(path))
    return paths


def test_combine_preserves_order_and_allows_reorder_before_accept(shell_window, tmp_path):
    first, second, third = files(tmp_path, 'primero.pdf', 'segundo.PDF', 'tercero.pdf')

    def edit(dialog):
        assert dialog.paths() == [first, second, third]
        assert not dialog.append.isChecked()
        assert not dialog.append.isEnabled()
        dialog.files.setCurrentRow(2)
        dialog.move(-1)
        dialog.files.setCurrentRow(0)
        dialog.remove()
        dialog.validate()
        return dialog.result()

    shell_window.edit_dialog = edit
    assert shell_window.start_shell_action_v305('combine', [first, second, first, third])
    assert shell_window.combined == [[third, second]]
    assert not shell_window.submissions


def test_combine_one_file_offers_adding_more_and_cancel_preserves_sources(shell_window, tmp_path):
    (first,) = files(tmp_path, 'único.pdf')

    def edit(dialog):
        assert dialog.paths() == [first]
        dialog.validate()
        assert dialog.result() == QDialog.Rejected
        assert '2' in dialog.error.text()
        return QDialog.Rejected

    shell_window.edit_dialog = edit
    assert not shell_window.start_shell_action_v305('combine', [first])
    assert not shell_window.combined
    assert Path(first).read_bytes() == b'test source'


def test_convert_submits_once_and_opens_single_pdf_after_worker_finishes(shell_window, tmp_path):
    (source,) = files(tmp_path, 'revisión <final>.DOCX')
    assert shell_window.start_shell_action_v305('convert', [source, source])
    command, payload, _callback = shell_window.submissions[-1]
    assert command == 'convert_office'
    assert payload['paths'] == [source]
    ticket = Path(payload['_office_ticket']['path'])
    assert ticket.is_file()
    progress = shell_window._office_conversion_v305['progress']
    assert progress.isVisible()
    assert not shell_window.opened
    output = str(tmp_path / 'revisión <final>.pdf')
    shell_window.complete({'results': [{'path': output}], 'errors': [], 'cancelled': False})
    assert not ticket.exists()
    assert shell_window._office_conversion_v305 is None
    assert not progress.isVisible()
    assert shell_window.opened == [output]


def test_cancel_invalidates_only_office_ticket_and_waits_for_worker(shell_window, qtbot, tmp_path):
    (source,) = files(tmp_path, 'largo.doc')
    assert shell_window.start_shell_action_v305('convert', [source])
    job = shell_window._office_conversion_v305
    ticket = Path(shell_window.submissions[-1][1]['_office_ticket']['path'])
    cancel = next(button for button in job['progress'].findChildren(QPushButton)
                  if button.text() == 'Cancelar')
    qtbot.mouseClick(cancel, Qt.LeftButton)
    assert not ticket.exists()
    assert shell_window.busy
    assert shell_window._office_conversion_v305 is job
    assert job['cancelled']
    shell_window.complete({'results': [], 'errors': [], 'cancelled': True})
    assert shell_window._office_conversion_v305 is None
    assert not shell_window.errors
    assert not shell_window.opened
    assert 'cancelada' in shell_window.notices[-1]


def test_batch_shows_created_files_and_partial_errors_without_opening_all(shell_window, qtbot, tmp_path):
    sources = files(tmp_path, 'uno.docx', 'dos.doc', 'fallido.docx')
    assert shell_window.start_shell_action_v305('convert', sources)
    outputs = [str(tmp_path / 'uno.pdf'), str(tmp_path / 'dos.pdf')]
    shell_window.complete({
        'results': [{'path': path} for path in outputs],
        'errors': [{'source': sources[-1], 'error': 'Documento protegido.'}],
        'cancelled': False,
    })
    assert not shell_window.opened
    dialog = shell_window._office_results_v305
    assert dialog.isVisible()
    assert [dialog.files.item(i).text() for i in range(dialog.files.count())] == outputs
    assert 'Documento protegido.' in dialog.findChild(QPlainTextEdit, 'officeConversionErrors').toPlainText()
    dialog.files.setCurrentRow(1)
    qtbot.mouseClick(dialog.open_button, Qt.LeftButton)
    assert shell_window.opened == [outputs[1]]


def test_office_error_and_rejected_submission_release_progress_and_marker(shell_window, tmp_path):
    (source,) = files(tmp_path, 'texto.docx')
    assert shell_window.start_shell_action_v305('convert', [source])
    ticket = Path(shell_window.submissions[-1][1]['_office_ticket']['path'])
    shell_window.busy = False
    shell_window._error('Instala Microsoft Word o LibreOffice para convertir DOC y DOCX.')
    assert shell_window._office_conversion_v305 is None
    assert not ticket.exists()
    shell_window.accept_submission = False
    assert not shell_window.start_shell_action_v305('convert', [source])
    assert shell_window._office_conversion_v305 is None


def test_close_cancels_pending_office_work_and_ignores_late_callback(shell_window, tmp_path):
    (source,) = files(tmp_path, 'cerrar.docx')
    assert shell_window.start_shell_action_v305('convert', [source])
    ticket = Path(shell_window.submissions[-1][1]['_office_ticket']['path'])
    shell_window.close_shell_actions_v305()
    assert not ticket.exists()
    shell_window.complete({'results': [{'path': str(tmp_path / 'cerrar.pdf')}], 'errors': []})
    assert not shell_window.opened
    assert shell_window._office_conversion_v305 is None


def test_invalid_requests_never_submit_or_launch_merge(shell_window, tmp_path):
    doc, pdf = files(tmp_path, 'texto.docx', 'archivo.pdf')
    for action, paths in (('combine', [doc, pdf]), ('convert', [pdf]),
                          ('convert', [str(tmp_path / 'ausente.docx')]),
                          ('other', [pdf]), ('convert', []), ('convert', [doc] * 2001)):
        assert not shell_window.start_shell_action_v305(action, paths)
    assert len(shell_window.errors) == 6
    assert not shell_window.submissions
    assert not shell_window.combined


@pytest.fixture
def real_shell_window(qtbot, tmp_path):
    from pdfmodder.app import MainWindow

    history = tmp_path / 'history'
    history.mkdir()
    window = MainWindow(config_path=tmp_path / 'fonts.json', history_dir=history)
    qtbot.addWidget(window, before_close_func=lambda widget: setattr(widget, '_allow_close', True))
    window.show()
    window.thumbnail_timer.stop()
    yield window
    window._allow_close = True
    window.close()


def make_pdf(path, *pages):
    with pymupdf.open() as document:
        for text in pages:
            document.new_page(width=400, height=300).insert_text((35, 90), text)
        document.save(path)
    return str(path)


def test_real_window_combines_reordered_selection_without_recovery_during_modal(
        real_shell_window, qtbot, tmp_path, monkeypatch):
    window = real_shell_window
    first = make_pdf(tmp_path / 'primero.pdf', 'First page 1', 'First page 2')
    second = make_pdf(tmp_path / 'segundo.pdf', 'Second document')
    originals = {path: Path(path).read_bytes() for path in (first, second)}
    calls, completed, observed = [], [], []
    submit = window._submit

    def record(command, payload=None, callback=None):
        calls.append((command, getattr(window, '_modal_depth_v200', 0)))
        return submit(command, payload, callback)

    monkeypatch.setattr(window, '_submit', record)
    window.operation_finished.connect(lambda command, result: completed.append((command, result)))

    def accept_after_startup_recovery_timer():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, MergeDialog)
            assert dialog.paths() == [first, second]
            assert window._modal_depth_v200 == 1
            # Startup's 250 ms recovery callback has had time to run inside
            # the nested modal event loop, where it must defer its query.
            assert not any(command == 'list_recovery' for command, _depth in calls)
            dialog.files.setCurrentRow(1)
            dialog.move(-1)
            observed.append(dialog.paths())
            dialog.validate()
        finally:
            if dialog is not None and dialog.result() != QDialog.Accepted:
                dialog.reject()

    QTimer.singleShot(360, accept_after_startup_recovery_timer)
    assert window.start_shell_action_v305('combine', [first, second])
    qtbot.waitUntil(lambda: any(command == 'combine' for command, _result in completed), timeout=30000)
    assert observed == [[second, first]]
    assert sum(command == 'combine' for command, _depth in calls) == 1
    assert not any(command == 'list_recovery' and depth for command, depth in calls)
    assert window.state['page_count'] == 3
    assert window.document_tabs_v200.count() == 1
    assert not window.last_error, window.last_error
    qtbot.waitUntil(lambda: not window.busy, timeout=30000)
    snapshots = []
    assert window._submit('snapshot_v200', {}, snapshots.append)
    qtbot.waitUntil(lambda: bool(snapshots), timeout=30000)
    with pymupdf.open(stream=snapshots[0]['data'], filetype='pdf') as document:
        assert [page.get_text().strip() for page in document] == [
            'Second document', 'First page 1', 'First page 2',
        ]
    assert all(Path(path).read_bytes() == data for path, data in originals.items())


def test_real_close_waits_for_cancelled_office_job_without_opening_result(
        real_shell_window, qtbot, tmp_path, monkeypatch):
    window = real_shell_window
    (source,) = files(tmp_path, 'cerrar.docx')
    output = make_pdf(tmp_path / 'ya-convertido.pdf', 'Completed before cancellation')
    pending = Future()
    submit = window.pool.submit

    def intercept(function, command, payload):
        return pending if command == 'convert_office' else submit(function, command, payload)

    monkeypatch.setattr(window.pool, 'submit', intercept)
    assert window.start_shell_action_v305('convert', [source])
    job = window._office_conversion_v305
    assert job['channel']._path.is_file()
    assert not window.close()
    assert window._close_waiting_v300
    assert job['cancelled']
    assert job['channel']._path is None
    assert window.busy
    pending.set_result({'results': [{'path': output}], 'errors': [], 'cancelled': True})
    qtbot.waitUntil(lambda: window._closed, timeout=30000)
    assert not window.state
    assert window._office_conversion_v305 is None
    assert getattr(window, '_office_results_v305', None) is None
    assert Path(output).is_file()
