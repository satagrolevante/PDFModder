"""Automatic area fitting remains bounded and keeps explicit typography."""
import pytest

from pdfmodder.auto_layout_v316 import adapt_rich_layout_v316
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import _layout
from pdfmodder.dialogs import TextDialog
from test_auto_overlap_v315 import editor
from test_tools_ui_v150 import tools_window
from test_selection_ui_v300 import payload


def tokens(text,size=12.):
    return [dict(char=char,width=size*.5,size=size,spacing=0.,asc=size*.75,
                 desc=size*.25,index=index) for index,char in enumerate(text)]


def request(**kwargs):
    return RichTextRequest(0,[],[dict(text='Original',font_name='Helvetica',size=12.)],**kwargs)


def test_long_natural_width_wraps_within_visible_limits_without_shrinking():
    value=request(auto_adapt=True,auto_width=True)
    text='Muchas palabras que deben conservarse completas'
    items=tokens(text)
    fitted,area,report=adapt_rich_layout_v316(value,items,(10.,20.,400.,23.),(0.,0.,120.,180.))
    laid,lines,final=_layout(fitted,items,area)
    assert len(lines)>1 and ''.join(t['char'] for t in laid)==text
    assert all(10.<=t['bbox'][0] and t['bbox'][2]<=120. and t['bbox'][3]<=180. for t in laid)
    assert {t['size'] for t in laid}=={12.} and fitted.runs==value.runs
    assert report['auto_adapt'] and final[3]>23.


def test_explicit_fixed_width_stays_fixed_and_height_can_grow():
    value=request(auto_adapt=True,auto_width=False)
    fitted,area,_=adapt_rich_layout_v316(value,tokens('Texto largo en caja'),(10.,20.,45.,22.),(0.,0.,120.,180.))
    _,lines,final=_layout(fitted,tokens('Texto largo en caja'),area)
    assert area[0:3]==(10.,20.,45.) and len(lines)>1 and final[3]>22.


def test_too_narrow_box_can_expand_for_a_single_exact_sized_glyph():
    value=request(auto_adapt=True,auto_width=False)
    fitted,area,report=adapt_rich_layout_v316(value,tokens('W'),(10.,20.,11.,40.),(0.,0.,120.,180.))
    laid,_,_=_layout(fitted,tokens('W'),area)
    assert area[0]==10. and area[2]>=16.
    assert laid[0]['size']==12. and 'expand_minimum_width' in report['automatic_area_adjustments']


def test_opt_out_preserves_fixed_box_and_strict_overflow():
    value=request(auto_adapt=False,auto_width=False,auto_height=False)
    fitted,area,report=adapt_rich_layout_v316(value,tokens('Texto'),(10.,20.,11.,22.),(0.,0.,120.,180.))
    assert fitted is value and area==(10.,20.,11.,22.) and not report
    with pytest.raises(EditError,match='anchura'):_layout(fitted,tokens('Texto'),area)


@pytest.mark.parametrize('area,limits',[
    ((130.,20.,140.,40.),(0.,0.,120.,180.)),
    ((10.,20.,15.,40.),(0.,0.,14.,180.)),
])
def test_adaptation_never_changes_origin_or_shrinks_an_unfittable_glyph(area,limits):
    with pytest.raises(EditError,match='espacio|supera'):
        adapt_rich_layout_v316(request(auto_adapt=True),tokens('W'),area,limits)


def test_normal_requests_and_fresh_drafts_enable_adaptation_with_opt_out(editor,monkeypatch):
    assert editor.auto_adapt_box.isChecked()
    assert editor._request(text='Cambio').auto_adapt
    monkeypatch.setattr(editor,'_submit',lambda command,request,callback:callback(payload()))
    editor.start_rich_edit()
    assert editor.canvas.editor.payload()['auto_adapt']
    editor._end_rich()
    editor.auto_adapt_box.setChecked(False)
    assert not editor._request(text='Cambio').auto_adapt
    editor.start_rich_edit()
    assert not editor.canvas.editor.payload()['auto_adapt']


def test_restored_draft_keeps_deliberate_adaptation_opt_out(editor):
    value=payload();value['auto_adapt']=False
    editor._open_rich_payload(value)
    assert editor.auto_adapt_box.isChecked()
    assert not editor.canvas.editor.payload()['auto_adapt']


def test_properties_dialog_enables_adaptation_but_keeps_source_typography(qtbot):
    catalog=[dict(name='Helvetica',family='Helvetica',variant='Regular',editable=True)]
    dialog=TextDialog(catalog,text='Fuente exacta',font_name='Helvetica',size=13.125,existing=True)
    qtbot.addWidget(dialog)
    before=dialog.values()
    assert before['auto_adapt'] and before['size']==13.125 and before['font_name'] is None
    dialog.auto_adapt_box.setChecked(False)
    after=dialog.values()
    assert not after['auto_adapt'] and after['size']==before['size'] and after['font_name'] is None


@pytest.mark.parametrize('enabled',[False,True])
def test_recovery_preserves_automatic_adaptation_choice(tmp_path,enabled):
    from pdfmodder.worker import Session
    from test_richtext_v09 import document
    path=tmp_path/'source.pdf';path.write_bytes(document())
    session=Session(path,history_dir=tmp_path,config_path=tmp_path/'fonts.json')
    try:
        value=dict(page=0,ids=[],rect=(30,30,200,100),revision=session.history.revision,
                   runs=[dict(text='Draft',font_name='Helvetica',size=12.)],auto_adapt=enabled)
        session.store_draft(dict(kind='rich',payload=value))
        assert session.history.metadata['draft']['payload']['auto_adapt'] is enabled
    finally:session.close()
