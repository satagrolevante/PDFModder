"""Missing embedded characters require a concrete, explicit font choice."""
from dataclasses import replace
from pathlib import Path
import pickle

import pymupdf as fitz
import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog

from pdfmodder.font_choice_v321 import FontChoiceRequired, face_identity
from pdfmodder.font_choice_ui_v321 import FontChoiceDialog
from pdfmodder.fonts import FontResolver
from pdfmodder.rich_editor import PageEditor
from pdfmodder.richtext import edit_rich_pdf
from test_fonts import make_font
from test_clipped_fields_v321 import document, request, trace, assert_preserved
from test_rich_ui_v09 import window, idle, select


def partial_document(tmp_path):
    font = make_font(tmp_path/'partial.ttf', text=' SANDIA')
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=220)
        page.insert_text((30, 60), 'SANDIA', fontname='Partial', fontfile=str(font), fontsize=12)
        page.insert_text((30, 150), 'NEIGHBOR', fontsize=12)
        return doc.tobytes()


def bundled_face():
    # Use the licensed font shipped with the project; do not assume that the
    # host OS has installed it or lists it in its system font catalogue.
    return {'name':'LiberationSans', 'path':str(Path(__file__).resolve().parents[1]
        /'assets/fonts/LiberationSans-Regular.ttf')}


def test_missing_font_error_survives_worker_serialization_and_explicit_retry(tmp_path):
    data = partial_document(tmp_path)
    req = request(data, 'SANDÍA', selection='SANDIA')
    with pytest.raises(FontChoiceRequired) as caught:
        edit_rich_pdf(data, req)
    error = pickle.loads(pickle.dumps(caught.value))
    assert face_identity(error.source_style) == face_identity(req.runs[0])
    assert error.text == 'SANDÍA'
    face = bundled_face()
    chosen = dict(req.runs[0], font_name=face['name'], font_file=face['path'], font_resource=None, font_xref=None)
    output, report = edit_rich_pdf(data, replace(req, runs=[chosen]))
    assert report['verified'] and trace(output) == 'SANDÍANEIGHBOR'
    assert trace(data) == 'SANDIANEIGHBOR'


@pytest.mark.parametrize('shaped', [False, True])
def test_explicit_new_face_in_cropped_field_preserves_clip_and_removes_hidden_tail(shaped):
    data = document()
    req = request(data, 'FRUTA Ñ')
    face = bundled_face()
    run = dict(req.runs[0], font_name=face['name'], font_file=face['path'], font_resource=None, font_xref=None)
    if shaped:
        run['font_features'] = {'liga':1, 'kern':1}
    output, report = edit_rich_pdf(data, replace(req, runs=[run]))
    assert report['verified'] and report['hidden_field_characters_removed'] == 4
    assert trace(output) == 'FRUTA ÑNEIGHBOR'
    assert_preserved(data, output)


def test_dialog_rejects_incomplete_choice_and_cancellation_changes_nothing(qtbot, tmp_path):
    path = make_font(tmp_path/'partial.ttf', text=' SANDIA')
    dialog = FontChoiceDialog('Original', 'SANDÍA', [{'name':'Partial', 'path':str(path)}])
    qtbot.addWidget(dialog)
    dialog.accept()
    assert dialog.result() != QDialog.Accepted and dialog.entry is None
    assert 'Faltan caracteres' in dialog.status.text()
    dialog.reject()
    assert dialog.result() == QDialog.Rejected


def test_explicit_choice_preserves_other_faces_styles_text_and_is_undoable(qtbot):
    editor = PageEditor()
    qtbot.addWidget(editor)
    source = dict(font_name='Partial', font_xref=12, font_resource='/R1', font_file=None, size=12,
                  color=(.8, 0, 0), underline=True)
    other = dict(font_name='Other', font_xref=13, font_resource='/R2', font_file=None, size=15, color=(0, 0, 1))
    editor.load_payload(dict(page=0, ids=[1,2], rect=(0,0,200,100), runs=[dict(source,text='Á'),dict(other,text='B')]))
    before = editor.payload()
    face = bundled_face()
    assert editor.replace_unavailable_face_v321(source, face)
    runs = editor.payload()['runs']
    assert ''.join(r['text'] for r in runs) == 'ÁB'
    assert runs[0]['size'] == 12 and runs[0]['color'] == (.8,0,0) and runs[0]['underline']
    assert face_identity(runs[1]) == face_identity(other)
    editor.undo()
    assert editor.payload()['runs'] == before['runs']


def test_gui_worker_font_choice_preview_accept_save_and_undo(qtbot, window, tmp_path, monkeypatch):
    data = partial_document(tmp_path)
    path = tmp_path/'partial.pdf'; path.write_bytes(data)
    window.open_document(path); idle(qtbot,window)
    select(window, 'SANDIA'); window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=15000)
    editor = window.canvas.editor
    cursor = editor.textCursor(); cursor.select(QTextCursor.Document); cursor.insertText('SANDÍA')
    editor.accept_draft()
    qtbot.waitUntil(lambda:window.font_choice_button_v321.isVisible() and not window.busy,timeout=20000)
    assert window.state['history_index'] == 0 and path.read_bytes() == data
    before = editor.payload()
    monkeypatch.setattr(window, '_exec_edit_dialog', lambda dialog:QDialog.Rejected)
    window._choose_compatible_font_v321()
    assert editor.payload() == before and window.state['history_index'] == 0
    monkeypatch.setattr('pdfmodder.font_choice_ui_v321.QFileDialog.getOpenFileName',
        lambda *args:(bundled_face()['path'], 'Fuentes (*.ttf *.otf)'))
    def choose(dialog):
        dialog.import_font()
        assert dialog.fonts.currentData()['name']=='LiberationSans'
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(window, '_exec_edit_dialog', choose)
    window._choose_compatible_font_v321()
    idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index'] == 0  # Choosing a face only changes the draft.
    editor.accept_draft(); idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index'] == 1
    saved = tmp_path/'saved.pdf'; window.save_as(saved); idle(qtbot,window)
    assert trace(saved.read_bytes()) == 'SANDÍANEIGHBOR'
    window.history('undo'); idle(qtbot,window)
    assert ''.join(g.text for g in window.model.glyphs) == 'SANDIANEIGHBOR'
    assert path.read_bytes() == data
