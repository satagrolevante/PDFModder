"""Real Qt/worker save transactions, multiple tabs, drafts and failed writes."""
from pathlib import Path
from dataclasses import asdict

import pymupdf as fitz
from pypdf import PdfReader
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from pdfmodder.app import MainWindow
from pdfmodder.model import EditError, EditRequest
from pdfmodder.saving_ui_v300 import SaveDocumentsDialogV300, default_save_path_v300
from pdfmodder.saving_worker_v300 import apply_stored_draft_v300
from pdfmodder.worker import Session


def make_pdf(path, text='Fecha 10/09/2026'):
    with fitz.open() as document:
        document.new_page(width=400, height=300).insert_text((35, 90), text, fontsize=12)
        document.save(path)
    return path


@pytest.fixture
def saving_window(qtbot, tmp_path):
    history = tmp_path / 'history'
    history.mkdir()
    window = MainWindow(config_path=tmp_path / 'fonts.json', history_dir=history)
    window.thumbnail_timer.stop()
    window.reader_timer_v180.stop()
    qtbot.addWidget(window, before_close_func=lambda widget: setattr(widget, '_allow_close', True))
    window.show()
    yield window
    window._allow_close = True
    window.close()


def finished(qtbot, window, error=False):
    qtbot.waitUntil(lambda: not window.busy and window._save_transaction_v300 is None
        and not window._rich_loading and not window._rich_accept_pending, timeout=60000)
    if not error:
        assert not window.last_error, window.last_error


def open_editing(qtbot, window, source):
    assert window.open_document(source)
    finished(qtbot, window)
    window.tools_action.setChecked(True)
    finished(qtbot, window)
    assert window.application_mode == 'editing'
    return window._active_session_v200


def change_metadata(qtbot, window, title):
    assert window._submit('edit_document_metadata', {'metadata': {'title': title}}, lambda _: window.commit())
    finished(qtbot, window)
    assert window.state['dirty']


def start_draft(qtbot, window, text):
    window.canvas.set_selection([glyph.id for glyph in window.model.glyphs])
    window.start_edit()
    qtbot.waitUntil(lambda: window.canvas.editor.isVisible() and not window.busy, timeout=60000)
    window.canvas.editor.selectAll()
    window.canvas.editor.insertPlainText(text)
    window._rich_timer.stop()


def test_ctrl_s_remembers_copy_and_save_as_changes_only_its_tab(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    source = make_pdf(tmp_path / 'original.pdf')
    original = source.read_bytes()
    sid = open_editing(qtbot, window, source)
    change_metadata(qtbot, window, 'Primero')
    destination = tmp_path / 'copia.pdf'
    choices = []
    def choose(*args):
        choices.append(args)
        return str(destination), 'Documento PDF (*.pdf)'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    window.save_action.trigger()
    finished(qtbot, window)
    assert len(choices) == 1 and destination.is_file()
    assert window._save_paths_v300[sid] == str(destination.resolve())
    assert window.save_action.shortcut().toString() == 'Ctrl+S'
    assert window.save_as_action_v300.shortcut().toString() == 'Ctrl+Shift+S'
    change_metadata(qtbot, window, 'Segundo')
    window.save_action.trigger()
    finished(qtbot, window)
    assert len(choices) == 1
    assert PdfReader(destination).metadata.title == 'Segundo'
    new_destination = tmp_path / 'otra-copia.pdf'
    window.save_as(new_destination)
    finished(qtbot, window)
    assert window._save_paths_v300[sid] == str(new_destination.resolve())
    assert source.read_bytes() == original


def test_save_as_in_reading_keeps_exact_bytes_without_font_preparation(qtbot, saving_window, tmp_path):
    window = saving_window
    source = make_pdf(tmp_path / 'reading.pdf')
    original = source.read_bytes()
    assert window.open_document(source)
    finished(qtbot, window)
    assert window.application_mode == 'reading' and not window.state['editing_prepared']
    assert window.save_action.isEnabled() and window.save_as_action_v300.isEnabled()
    output = tmp_path / 'reading-copy.pdf'
    assert window.save_as(output)
    finished(qtbot, window)
    assert output.read_bytes() == original and source.read_bytes() == original
    assert not window.state['editing_prepared'] and window.application_mode == 'reading'


@pytest.mark.parametrize('encrypted', [False, True])
def test_worker_clean_reading_copy_preserves_pdf_and_encryption(tmp_path, encrypted):
    source = tmp_path / 'immutable.pdf'
    with fitz.open() as document:
        document.new_page(width=400, height=300).insert_text((35, 90), 'Copia exacta', fontsize=12)
        if encrypted:
            document.save(source, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner-test',
                          user_pw='reader-test', permissions=fitz.PDF_PERM_PRINT)
        else:
            document.save(source)
    original = source.read_bytes()
    session = Session(source, password='reader-test' if encrypted else '', reading=True,
                      history_dir=tmp_path / 'history', recovery_root=tmp_path / 'recovery')
    try:
        output = tmp_path / 'unchanged-copy.pdf'
        result = session.save(output, reading_copy=True)
        assert output.read_bytes() == original and source.read_bytes() == original
        assert result['state']['last_save_path'] == str(output.resolve())
        assert session.resolver is None and not session._editing_prepared
        with fitz.open(output) as copied:
            assert copied.needs_pass == encrypted
            if encrypted:
                assert copied.authenticate('reader-test')
                assert not copied.permissions & fitz.PDF_PERM_COPY
            assert copied.page_count == 1
        with pytest.raises(EditError):
            session.save(source, reading_copy=True)
        assert source.read_bytes() == original
    finally:
        session.close()


def test_save_all_keeps_active_tab_and_each_destination(qtbot, saving_window, tmp_path):
    window = saving_window
    first = make_pdf(tmp_path / 'primero.pdf')
    second = make_pdf(tmp_path / 'segundo.pdf')
    first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
    first_sid = open_editing(qtbot, window, first)
    change_metadata(qtbot, window, 'Documento uno')
    second_sid = open_editing(qtbot, window, second)
    change_metadata(qtbot, window, 'Documento dos')
    outputs = {first_sid: tmp_path / 'uno-guardado.pdf', second_sid: tmp_path / 'dos-guardado.pdf'}
    assert window.save_all_v300(outputs)
    finished(qtbot, window)
    assert window._active_session_v200 == second_sid
    assert window.state['session_id'] == second_sid and not window.state['dirty']
    assert not window._session_views_v200[first_sid]['state']['dirty']
    assert PdfReader(outputs[first_sid]).metadata.title == 'Documento uno'
    assert PdfReader(outputs[second_sid]).metadata.title == 'Documento dos'
    assert first.read_bytes() == first_bytes and second.read_bytes() == second_bytes
    # The backend must also have been restored: the next edit belongs to tab 2.
    change_metadata(qtbot, window, 'Dos posterior')
    window.save_document_v300()
    finished(qtbot, window)
    assert PdfReader(outputs[second_sid]).metadata.title == 'Dos posterior'
    assert PdfReader(outputs[first_sid]).metadata.title == 'Documento uno'


def test_save_all_applies_persisted_rich_draft_in_inactive_tab(qtbot, saving_window, tmp_path):
    window = saving_window
    first_source = make_pdf(tmp_path / 'draft-inactive.pdf')
    original = first_source.read_bytes()
    first_sid = open_editing(qtbot, window, first_source)
    payloads = []
    assert window._submit('rich_selection', {'page': 0, 'ids': [g.id for g in window.model.glyphs]}, payloads.append)
    finished(qtbot, window)
    payload = payloads[0]
    payload['runs'] = [dict(payload['runs'][0], text='Fecha 12/09/2026')]
    payload.update(auto_width=True, auto_height=True)
    second_sid = open_editing(qtbot, window, make_pdf(tmp_path / 'active.pdf'))
    change_metadata(qtbot, window, 'Documento activo')
    assert window._submit('store_draft', {'session_id': first_sid, 'draft': {'kind': 'rich', 'payload': payload},
                                         'workspace': {}, '_background_ui': True})
    finished(qtbot, window)
    outputs = {first_sid: tmp_path / 'saved-draft.pdf', second_sid: tmp_path / 'saved-active.pdf'}
    assert window.save_all_v300(outputs)
    finished(qtbot, window)
    assert 'Fecha 12/09/2026' in PdfReader(outputs[first_sid]).pages[0].extract_text()
    assert PdfReader(outputs[second_sid]).metadata.title == 'Documento activo'
    assert first_source.read_bytes() == original
    assert window._active_session_v200 == second_sid and window.state['session_id'] == second_sid
    assert not window._session_views_v200[first_sid]['state']['draft_pending']
    assert not window._session_views_v200[first_sid]['state']['dirty']


def test_save_all_partial_failure_leaves_failed_tab_dirty_and_retryable(qtbot, saving_window, tmp_path):
    window = saving_window
    first_sid = open_editing(qtbot, window, make_pdf(tmp_path / 'primero.pdf'))
    change_metadata(qtbot, window, 'Guardado')
    second_sid = open_editing(qtbot, window, make_pdf(tmp_path / 'segundo.pdf'))
    change_metadata(qtbot, window, 'Pendiente')
    first_output = tmp_path / 'guardado.pdf'
    impossible = tmp_path / 'directorio.pdf'
    impossible.mkdir()
    window.save_all_v300({first_sid: first_output, second_sid: impossible})
    finished(qtbot, window, error=True)
    assert first_output.is_file() and impossible.is_dir()
    assert not window._session_views_v200[first_sid]['state']['dirty']
    assert window.state['dirty'] and window._active_session_v200 == second_sid
    assert 'Guardados: 1' in window.message.text() and 'Pendientes: 1' in window.message.text()
    retry = tmp_path / 'reintentado.pdf'
    window.save_all_v300({second_sid: retry})
    finished(qtbot, window)
    assert PdfReader(retry).metadata.title == 'Pendiente'


def test_cancel_save_all_and_close_keep_exact_draft_and_history(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    source = make_pdf(tmp_path / 'original.pdf')
    open_editing(qtbot, window, source)
    start_draft(qtbot, window, 'Fecha 11/09/2026')
    revision = window.state['document_revision']
    monkeypatch.setattr(window, '_choose_destinations_v300', lambda _: None)
    window.save_all_v300()
    finished(qtbot, window)
    assert window.canvas.editor.isVisible()
    assert window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'
    assert window.state['document_revision'] == revision and window.state['history_index'] == 0
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'cancel')
    window._close_tab_v200(0)
    finished(qtbot, window)
    assert window.document_tabs_v200.count() == 1 and window.canvas.editor.isVisible()
    window.close()
    finished(qtbot, window)
    assert not window._closed and window.isVisible()
    assert window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'


def test_save_while_rich_draft_open_validates_once_and_closes_tab(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    source = make_pdf(tmp_path / 'original.pdf')
    original = source.read_bytes()
    sid = open_editing(qtbot, window, source)
    start_draft(qtbot, window, 'Fecha 11/09/2026')
    destination = tmp_path / 'aceptado.pdf'
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'save')
    monkeypatch.setattr(window, '_choose_destinations_v300', lambda _: {sid: destination})
    operations = []
    window.operation_finished.connect(lambda command, _: operations.append(command))
    window._close_tab_v200(0)
    finished(qtbot, window)
    assert window.document_tabs_v200.count() == 0 and not window._closed
    assert operations.count('rich_prepare') == 1 and operations.count('rich_commit') == 1
    assert operations.index('rich_commit') < operations.index('save') < operations.index('close_session')
    assert 'Fecha 11/09/2026' in PdfReader(destination).pages[0].extract_text()
    assert source.read_bytes() == original


def test_failed_draft_validation_does_not_close_or_create_file(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    source = make_pdf(tmp_path / 'original.pdf')
    sid = open_editing(qtbot, window, source)
    start_draft(qtbot, window, 'Fecha 11/09/2026')
    payload = window.canvas.editor.payload()
    payload.update(width=1., height=1., auto_width=False, auto_height=False)
    payload['rect'] = [35., 80., 36., 81.]
    monkeypatch.setattr(window.canvas.editor, 'payload', lambda: payload)
    destination = tmp_path / 'no-creado.pdf'
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'save')
    monkeypatch.setattr(window, '_choose_destinations_v300', lambda _: {sid: destination})
    window._close_tab_v200(0)
    finished(qtbot, window, error=True)
    assert window.last_error and not destination.exists()
    assert window.document_tabs_v200.count() == 1 and window.canvas.editor.isVisible()
    assert window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'
    assert window.state['history_index'] == 0


def test_destinations_reject_other_open_original_and_collisions(qtbot, saving_window, tmp_path):
    window = saving_window
    first_sid = open_editing(qtbot, window, make_pdf(tmp_path / 'primero.pdf'))
    change_metadata(qtbot, window, 'Uno')
    second_source = make_pdf(tmp_path / 'segundo.pdf')
    original = second_source.read_bytes()
    second_sid = open_editing(qtbot, window, second_source)
    change_metadata(qtbot, window, 'Dos')
    window.save_all_v300({first_sid: second_source, second_sid: tmp_path / 'dos.pdf'})
    finished(qtbot, window, error=True)
    assert 'original' in window.last_error and second_source.read_bytes() == original
    collision = tmp_path / 'duplicado.pdf'
    window.save_all_v300({first_sid: collision, second_sid: collision})
    finished(qtbot, window, error=True)
    assert 'diferente' in window.last_error and not collision.exists()


def test_discard_closes_requested_inactive_tab_only(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    first_sid = open_editing(qtbot, window, make_pdf(tmp_path / 'primero.pdf'))
    change_metadata(qtbot, window, 'Uno')
    second_sid = open_editing(qtbot, window, make_pdf(tmp_path / 'segundo.pdf'))
    change_metadata(qtbot, window, 'Dos')
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'discard')
    window._close_tab_v200(0)
    finished(qtbot, window)
    assert first_sid not in window._session_paths_v200
    assert window._active_session_v200 == second_sid and window.state['dirty']
    assert window.document_tabs_v200.count() == 1


def test_persisted_legacy_draft_uses_real_worker_validation(tmp_path):
    source = make_pdf(tmp_path / 'stored.pdf')
    session = Session(source, history_dir=tmp_path / 'history', recovery_root=tmp_path / 'recovery')
    try:
        model = session.page(0)['model']
        draft = {'kind': 'legacy', 'page': 0, 'ids': [g.id for g in model.glyphs],
                 'revision': model.revision, 'text': 'Fecha 11/09/2026'}
        session.store_draft(draft)
        result = apply_stored_draft_v300(session)
        assert result['state']['history_index'] == 1
        assert not session.history.metadata.get('draft')
        output = tmp_path / 'stored-output.pdf'
        session.save(output)
        assert '11/09/2026' in PdfReader(output).pages[0].extract_text()
        # A stale draft is rejected without changing history or deleting it.
        session.store_draft(dict(draft, text='Fecha 12/09/2026'))
        with pytest.raises(EditError):
            apply_stored_draft_v300(session)
        assert session.history.index == 1 and session.history.metadata['draft']['text'] == 'Fecha 12/09/2026'
    finally:
        session.close()


def test_persisted_legacy_draft_preserves_explicit_formatting(tmp_path):
    source = make_pdf(tmp_path / 'format.pdf')
    original = source.read_bytes()
    session = Session(source, history_dir=tmp_path / 'history', recovery_root=tmp_path / 'recovery')
    try:
        model = session.page(0)['model']
        request = EditRequest(page=0, ids=[g.id for g in model.glyphs], revision=model.revision,
                              text='Fecha 11/09/2026', size=14., color=(.7, .1, .2), auto_width=True, auto_height=True)
        session.store_draft({'kind': 'legacy', 'page': 0, 'ids': request.ids,
                             'revision': request.revision, 'text': request.text, 'request': asdict(request)})
        apply_stored_draft_v300(session)
        output = tmp_path / 'formatted.pdf'
        session.save(output)
        with fitz.open(output) as document:
            spans = [span for block in document[0].get_text('dict')['blocks'] if block.get('type') == 0
                     for line in block['lines'] for span in line['spans']]
            assert any('11/09/2026' in span['text'] and span['size'] == pytest.approx(14.) for span in spans)
        assert source.read_bytes() == original
    finally:
        session.close()


@pytest.mark.parametrize('valid', [True, False])
def test_persisted_rich_draft_replaces_older_preview_or_restores_it(tmp_path, valid):
    source = make_pdf(tmp_path / 'rich-stored.pdf')
    session = Session(source, history_dir=tmp_path / 'history', recovery_root=tmp_path / 'recovery')
    try:
        model = session.page(0)['model']
        ids = [g.id for g in model.glyphs]
        payload = session.rich_selection(0, ids)
        payload['runs'] = [dict(payload['runs'][0], text='Fecha 12/09/2026')]
        payload.update(auto_width=valid, auto_height=valid)
        if not valid:
            payload.update(width=1., height=1., rect=[35., 80., 36., 81.])
        session.preview(EditRequest(page=0, ids=ids, revision=model.revision, text='Fecha 11/09/2026'))
        previous_preview = session.pending
        session.store_draft({'kind': 'rich', 'payload': payload})
        if valid:
            apply_stored_draft_v300(session)
            output = tmp_path / 'rich-newer.pdf'
            session.save(output)
            text = PdfReader(output).pages[0].extract_text()
            assert '12/09/2026' in text and '11/09/2026' not in text
            assert session.history.index == 1 and not session.history.metadata.get('draft')
        else:
            with pytest.raises(EditError):
                apply_stored_draft_v300(session)
            assert session.pending == previous_preview and session.history.index == 0
            assert session.history.pending_path.read_bytes() == previous_preview
            assert session.history.metadata['draft']['payload']['runs'][0]['text'] == 'Fecha 12/09/2026'
    finally:
        session.close()


def test_overwrite_cancel_keeps_draft_and_existing_copy(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    sid = open_editing(qtbot, window, make_pdf(tmp_path / 'original.pdf'))
    start_draft(qtbot, window, 'Fecha 11/09/2026')
    destination = make_pdf(tmp_path / 'existing.pdf', 'Copia previa')
    existing = destination.read_bytes()
    monkeypatch.setattr(window, '_confirm_overwrites_v300', lambda *_: False)
    window.save_all_v300({sid: destination})
    finished(qtbot, window)
    assert destination.read_bytes() == existing
    assert window.canvas.editor.isVisible() and window.canvas.editor.toPlainText() == 'Fecha 11/09/2026'
    assert window.state['history_index'] == 0 and window.centralWidget().isEnabled()


def test_save_transaction_disables_shortcuts_and_restores_controls(qtbot, saving_window, tmp_path):
    window = saving_window
    sid = open_editing(qtbot, window, make_pdf(tmp_path / 'original.pdf'))
    change_metadata(qtbot, window, 'Guardar sin interferencias')
    assert window.save_all_v300({sid: tmp_path / 'guardado.pdf'})
    assert not window.centralWidget().isEnabled() and not window.save_action.isEnabled()
    assert all(not action.isEnabled() for action in window.actions())
    assert not window._submit('cancel')
    finished(qtbot, window)
    assert window.centralWidget().isEnabled() and window.save_action.isEnabled()


def test_save_and_close_application_saves_all_tabs(qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    first = open_editing(qtbot, window, make_pdf(tmp_path / 'first.pdf'))
    change_metadata(qtbot, window, 'Uno antes de cerrar')
    second = open_editing(qtbot, window, make_pdf(tmp_path / 'second.pdf'))
    change_metadata(qtbot, window, 'Dos antes de cerrar')
    outputs = {first: tmp_path / 'saved-first.pdf', second: tmp_path / 'saved-second.pdf'}
    monkeypatch.setattr(window, '_ask_close_v300', lambda *_args, **_kwargs: 'save')
    monkeypatch.setattr(window, '_choose_destinations_v300', lambda _: outputs)
    window.close()
    qtbot.waitUntil(lambda: window._closed, timeout=60000)
    assert not window.isVisible() and not window._session_paths_v200
    assert PdfReader(outputs[first]).metadata.title == 'Uno antes de cerrar'
    assert PdfReader(outputs[second]).metadata.title == 'Dos antes de cerrar'


def test_destinations_dialog_lists_documents_and_retains_edits(qtbot, tmp_path):
    entries = [{'session_id': 'uno', 'path': str(tmp_path / 'uno.pdf')},
               {'session_id': 'dos', 'path': str(tmp_path / 'dos.pdf'), 'last_save_path': str(tmp_path / 'dos-copia.pdf')}]
    dialog = SaveDocumentsDialogV300(entries)
    qtbot.addWidget(dialog)
    assert dialog.table.rowCount() == 2
    assert dialog.destinations()['uno'] == default_save_path_v300(entries[0]['path'])
    assert dialog.destinations()['dos'] == str(tmp_path / 'dos-copia.pdf')
    dialog.paths['uno'].setText(str(tmp_path / 'elegido.pdf'))
    assert dialog.destinations()['uno'] == str(tmp_path / 'elegido.pdf')
