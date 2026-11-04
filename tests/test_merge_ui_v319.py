"""Consultation merges stay available without relaxing editing safeguards."""
from pathlib import Path

from PySide6.QtWidgets import QDialog, QLabel
import pytest

from pdfmodder.editing_ui import ExtendedEditing, MergeDialog
from test_reading_ui_v171 import reader, load_fixture
from test_shell_ui_v305 import shell_window, real_shell_window, make_pdf
from test_signature_appearance import visible_certificate


@pytest.mark.parametrize('has_document', [False, True])
def test_merge_dialog_always_explains_consultation_copy(qtbot, has_document):
    dialog = MergeDialog(has_document=has_document)
    qtbot.addWidget(dialog)
    note = dialog.findChild(QLabel, 'mergeConsultationNote').text()
    assert 'documento nuevo para consulta' in note
    assert 'Los originales se conservan' in note
    assert 'Las firmas no certifican el combinado' in note
    assert 'campos se fijan' in note and 'accesibilidad podrían quitarse' in note


def test_merge_dialog_preserves_explicit_repeats_and_updates_warning(qtbot, tmp_path):
    dialog = MergeDialog()
    qtbot.addWidget(dialog)
    first, second = [str(tmp_path / name) for name in ('primero.pdf', 'segundo.pdf')]
    dialog.files.addItems([first, second, first])
    assert dialog.paths() == [first, second, first]
    assert 'primero.pdf' in dialog.duplicates.text()
    assert '1, 3' in dialog.duplicates.text()
    dialog.files.setCurrentRow(2)
    dialog.move(-1)
    assert dialog.paths() == [first, first, second]
    assert '1, 2' in dialog.duplicates.text()
    dialog.remove()
    assert dialog.paths() == [first, second]
    assert not dialog.duplicates.text()
    dialog.validate()
    assert dialog.result() == QDialog.Accepted


@pytest.mark.parametrize('tagged,issues', [(False, []), (True, []),
                                         (False, ['El documento contiene firmas digitales.']),
                                         (True, ['El documento contiene firmas digitales.'])])
def test_reading_can_merge_signed_and_tagged_but_cannot_edit(reader, qtbot, tagged, issues):
    load_fixture(reader, qtbot)
    reader.state.update(tagged=tagged, issues=issues)
    reader._refresh_actions()
    assert reader.application_mode == 'reading'
    assert not reader.state['editing_prepared']
    assert reader.merge_action.isEnabled()
    for name in ('add_text_action', 'add_image_action', 'sign_action',
                 'delete_pages_action', 'document_security_action'):
        assert not getattr(reader, name).isEnabled(), name
    assert reader._reading_command_allowed_v171('merge')
    assert not reader._reading_command_allowed_v171('delete_pages')
    assert not reader._reading_command_allowed_v171('sign')


@pytest.mark.parametrize('attribute,value', [('_rich_active', True), ('_rich_loading', True),
                                          ('_rich_accept_pending', True), ('_close_waiting_v300', True),
                                          ('_placement', 'image'), ('_mode_preparing_v171', True),
                                          ('_save_transaction_v300', {'active': True})])
def test_merge_remains_unavailable_while_draft_or_operation_is_pending(
        reader, qtbot, monkeypatch, attribute, value):
    load_fixture(reader, qtbot)
    monkeypatch.setattr(reader, attribute, value)
    reader._refresh_actions()
    assert not reader.merge_action.isEnabled()


def test_choose_merge_acceptance_does_not_ask_to_discard_other_tab(reader, monkeypatch):
    combined = []

    def accept(dialog):
        dialog.append.setChecked(False)
        dialog.files.addItems(['primero.pdf', 'segundo.pdf'])
        dialog.validate()
        return dialog.result()

    monkeypatch.setattr(reader, '_exec_edit_dialog', accept)
    monkeypatch.setattr(reader, '_confirm_discard', lambda: pytest.fail('Redundant discard confirmation'))
    monkeypatch.setattr(reader, 'combine_pdfs', combined.append)
    reader.choose_merge()
    assert combined == [['primero.pdf', 'segundo.pdf']]


def test_merge_report_names_identical_sources_and_never_claims_a_valid_signature(reader, monkeypatch):
    applied = []
    monkeypatch.setattr(reader, '_edited', applied.append)
    result = {'report': {'as_copy': True, 'result_unsigned': True,
                         'warning': 'Se retiraron las etiquetas de accesibilidad.',
                         'warnings': ['Los campos se han fijado.'],
                         'source_paths': ['/input/EPS-primero.pdf', '/input/EPS-segundo.pdf'],
                         'duplicate_sources': [{'indices': [0, 1], 'sha256': 'test'}]}}
    ExtendedEditing._merged_v319(reader, result)
    assert applied == [result]
    text = reader.message.text()
    assert 'sin firmas digitales' in text and 'no certifican' in text
    assert 'EPS-primero.pdf' in text and 'EPS-segundo.pdf' in text
    assert 'cada aparición seleccionada' in text
    assert 'etiquetas de accesibilidad' in text and 'campos se han fijado' in text
    assert 'firma válida' not in text.lower()


def test_shell_keeps_distinct_files_with_identical_contents(shell_window, tmp_path):
    paths = [str(tmp_path / name) for name in ('EPS-primero.pdf', 'EPS-segundo.pdf')]
    for path in paths:
        Path(path).write_bytes(b'identical source contents')

    def accept(dialog):
        assert dialog.paths() == paths
        assert 'consulta' in dialog.findChild(QLabel, 'mergeConsultationNote').text()
        dialog.validate()
        return dialog.result()

    shell_window.edit_dialog = accept
    assert shell_window.start_shell_action_v305('combine', paths)
    assert shell_window.combined == [paths]


def test_real_signed_reading_merge_creates_unsigned_tab_and_preserves_sources(
        real_shell_window, visible_certificate, qtbot, tmp_path):
    from pdfmodder.signing import sign_pdf

    window = real_shell_window
    first = make_pdf(tmp_path / 'firmado.pdf', 'Signed source')
    certificate, _ = visible_certificate
    signed, _report = sign_pdf(Path(first).read_bytes(), certificate, 'test-only')
    Path(first).write_bytes(signed)
    second = make_pdf(tmp_path / 'consulta.pdf', 'Additional source')
    originals = {path: Path(path).read_bytes() for path in (first, second)}
    completed = []
    window.operation_finished.connect(lambda command, result: completed.append((command, result)))
    assert window.open_document(first)
    qtbot.waitUntil(lambda: bool(window.model) and not window.busy, timeout=30000)
    source_session = window.state['session_id']
    assert window.application_mode == 'reading'
    assert not window.state['editing_prepared']
    assert window.merge_action.isEnabled()
    assert not window.sign_action.isEnabled()
    window.merge_pdfs([second])
    qtbot.waitUntil(lambda: any(command == 'merge' for command, _ in completed), timeout=30000)
    qtbot.waitUntil(lambda: not window.busy, timeout=30000)
    result = next(result for command, result in completed if command == 'merge')
    assert result['new_session']
    assert window.state['session_id'] != source_session
    assert window.state['page_count'] == 2
    assert window.document_tabs_v200.count() == 2
    assert window._active_session_v200 == window.state['session_id']
    assert result['report']['result_unsigned']
    assert not window.last_error, window.last_error
    assert 'sin firmas digitales' in window.message.text()
    assert all(Path(path).read_bytes() == data for path, data in originals.items())
