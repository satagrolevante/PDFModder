"""Normal UI entry points permit overlap without a failing first validation."""
from copy import deepcopy

import pytest

from pdfmodder.dialogs import TextDialog
from test_selection_ui_v300 import payload
from test_tools_ui_v150 import _canvas_document, tools_window


@pytest.fixture
def editor(tools_window):
    window=tools_window
    _canvas_document(window)
    window.state={'page_count':1}
    window.canvas.set_selection([0])
    return window


def test_movement_and_legacy_text_requests_allow_overlap_by_default_and_allow_opt_out(editor):
    assert editor.allow_overlap_box.isChecked()
    assert 'automáticamente' in editor.allow_overlap_box.text()
    assert editor._request(dx=12.,dy=4.).allow_overlap
    assert editor._request(text='Cambio').allow_overlap
    editor.allow_overlap_box.setChecked(False)
    assert not editor._request(dx=12.).allow_overlap
    assert not editor._request(text='Cambio').allow_overlap


def test_fresh_rich_selection_carries_automatic_permission_to_editable_draft(editor,monkeypatch):
    requests=[]
    def submit(command,request,callback):
        requests.append(command)
        callback(payload(allow_overlap=False))
    monkeypatch.setattr(editor,'_submit',submit)
    editor.start_rich_edit()
    assert requests==['rich_selection']
    assert editor.canvas.editor.payload()['allow_overlap']
    assert editor.draft_overlap_box_v303.isChecked()
    editor.draft_overlap_box_v303.setChecked(False)
    assert not editor.canvas.editor.payload()['allow_overlap']


def test_inline_insertion_and_resize_use_the_same_default_without_manual_checkbox(editor,monkeypatch):
    monkeypatch.setattr(editor,'_catalog',lambda ready:ready([]))
    editor.begin_text()
    editor.placed(40.,80.)
    assert editor.canvas.editor.isVisible()
    assert editor.canvas.editor.payload()['allow_overlap']
    assert editor.draft_overlap_box_v303.isChecked()
    editor._end_rich()
    editor.canvas.set_selection([0])
    monkeypatch.setattr(editor,'_submit',lambda command,request,callback:callback(payload(allow_overlap=False)))
    editor.resize_text_area((15.,15.,120.,90.))
    assert editor.canvas.editor.payload()['allow_overlap']
    assert editor.draft_overlap_box_v303.isChecked()


def test_add_with_copied_format_inherits_current_overlap_policy(editor):
    value=payload(allow_overlap=False)
    editor._format_copy={'payload':value,'style':deepcopy(value['runs'][0])}
    editor.place_copied_text(30.,80.)
    assert editor.canvas.editor.payload()['allow_overlap']
    assert editor.draft_overlap_box_v303.isChecked()


@pytest.mark.parametrize('existing',[False,True])
def test_properties_dialog_allows_overlap_by_default_but_can_be_disabled(qtbot,existing):
    catalog=[dict(name='Helvetica',family='Helvetica',variant='Regular',editable=True)]
    dialog=TextDialog(catalog,text='Texto',existing=existing)
    qtbot.addWidget(dialog)
    assert dialog.values()['allow_overlap']
    assert 'automáticamente' in dialog.allow_overlap_box.text()
    dialog.allow_overlap_box.setChecked(False)
    assert not dialog.values()['allow_overlap']
