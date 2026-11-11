"""Inline semantics and optional layers survive real native text transactions."""
from io import BytesIO
from dataclasses import replace

import pymupdf as fitz
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ContentStream,DecodedStreamObject,NameObject,TextStringObject
import pytest

from pdfmodder.clipping import _serialize,_signature,operator_glyph_map
from pdfmodder.engine import edit_pdf,extract_page
from pdfmodder.model import EditRequest,EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import selection_payload,edit_rich_pdf
from pdfmodder.validation import page_issues
from pdfmodder.marked_content_v303 import MARKED_ISSUE
from pdfmodder.marked_text_v324 import native_marked_plan
from tagged_corpus import dictionary
from test_rich_ui_v09 import window


def document(*,actual='ALPHA BETA',layer=False,second_layer=False):
    with fitz.open() as doc:
        p=doc.new_page(width=340,height=230)
        oc=doc.add_ocg('Texto editable') if layer else 0
        p.insert_text((30,55),'ALPHA BETA',fontsize=12,oc=oc)
        first=p.get_contents()[0]
        if actual is not None:
            data=doc.xref_stream(first)
            props=dictionary(ActualText=TextStringObject(actual),Lang=TextStringObject('es-ES'))
            b=BytesIO();props.write_to_stream(b)
            doc.update_stream(first,b'/Span '+b.getvalue()+b' BDC\n'+data+b'\nEMC\n')
        p.insert_text((30,145),'CONTROL',fontsize=12)
        if second_layer:
            other=doc.add_ocg('Otra capa')
            p.insert_text((180,55),'OTHER',fontsize=12,oc=other)
        doc.new_page(width=340,height=230).insert_text((30,55),'OTHER PAGE')
        return doc.tobytes()


def selection(data,text):
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,0,data)
    flat=''.join(g.text for g in model.glyphs);at=flat.index(text)
    return model,[g.id for g in model.glyphs[at:at+len(text)]]


def actual_texts(data):
    r=PdfReader(BytesIO(data))
    return [str(a[1]['/ActualText']) for a,o in ContentStream(r.pages[0].get_contents(),r).operations
            if o==b'BDC' and isinstance(a[1],dict) and '/ActualText' in a[1]]


def assert_controls(source,output):
    with fitz.open(stream=source,filetype='pdf') as a,fitz.open(stream=output,filetype='pdf') as b:
        assert a[1].get_pixmap().samples==b[1].get_pixmap().samples
        assert a[0].get_pixmap(clip=(0,100,340,230)).samples==b[0].get_pixmap(clip=(0,100,340,230)).samples
    assert '/StructTreeRoot' not in PdfReader(BytesIO(output)).trailer['/Root']


@pytest.mark.parametrize('layer',[False,True])
@pytest.mark.parametrize('text,new',[('BETA','GAMMA'),('ALPHA BETA','NEW TEXT'),('ALPHA BETA','')])
def test_actualtext_partial_full_and_delete_keep_neighbor_and_update_logical_text(layer,text,new):
    source=document(layer=layer);model,ids=selection(source,text)
    assert MARKED_ISSUE not in page_issues(source,0)
    output,report=edit_pdf(source,EditRequest(0,ids,text=new,auto_adapt=True,auto_width=True,
                                            auto_height=True,allow_overlap=True,revision=model.revision))
    assert report['verified'] and report['accessibility']['marked_content_preserved']
    assert actual_texts(output)==['ALPHA BETA'.replace(text,new)]
    assert_controls(source,output)


def test_whole_block_replaces_a_different_actualtext_but_partial_change_needs_whole_block():
    source=document(actual='An expanded logical description')
    model,ids=selection(source,'ALPHA BETA')
    output,report=edit_pdf(source,EditRequest(0,ids,text='REPLACEMENT',auto_adapt=True,auto_width=True))
    assert report['verified'] and actual_texts(output)==['REPLACEMENT']
    model,ids=selection(source,'BETA')
    with pytest.raises(EditError,match='bloque completo'):
        edit_pdf(source,EditRequest(0,ids,text='GAMMA',auto_adapt=True,auto_width=True))


def test_layer_edit_keeps_registered_membership_and_everything_hides_when_layer_is_off():
    source=document(actual=None,layer=True,second_layer=True);model,ids=selection(source,'BETA')
    assert {g.layer for g in model.selected(ids)}=={'Texto editable'}
    output,report=edit_pdf(source,EditRequest(0,ids,text='GAMMA',auto_adapt=True,auto_width=True))
    assert report['verified'] and report['accessibility']['layer_membership_preserved']
    a=PdfReader(BytesIO(source));b=PdfReader(BytesIO(output))
    assert _signature(a.trailer['/Root']['/OCProperties'])==_signature(b.trailer['/Root']['/OCProperties'])
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        for d in (before,after):d.set_layer(-1,basestate='OFF',on=[],off=list(d.get_ocgs()))
        with fitz.open(stream=before.tobytes(),filetype='pdf') as off_a,fitz.open(stream=after.tobytes(),filetype='pdf') as off_b:
            assert off_a[0].get_pixmap().samples==off_b[0].get_pixmap().samples
    assert_controls(source,output)


@pytest.mark.parametrize('layer',[False,True])
def test_move_retains_actualtext_and_same_layer(layer):
    source=document(layer=layer);model,ids=selection(source,'ALPHA BETA')
    output,report=edit_pdf(source,EditRequest(0,ids,dx=12,dy=8,allow_overlap=True))
    assert report['verified'] and report['marked_content']['marked_content_preserved']
    assert actual_texts(output)==['ALPHA BETA']
    assert_controls(source,output)


def test_selection_cannot_merge_two_layers_and_final_validation_rejects_an_unregistered_copy():
    source=document(actual=None,layer=True,second_layer=True)
    model,ids=selection(source,'BETA')
    _,other=selection(source,'OTHER')
    with pytest.raises(EditError,match='capas'):
        edit_pdf(source,EditRequest(0,ids+other,text='MERGED',auto_adapt=True,auto_width=True))
    reader,ops,_,mapping=operator_glyph_map(source,0,model)
    plan=native_marked_plan(source,0,model,model.selected(ids),model.selected(ids),ops,mapping,reader=reader)
    writer=PdfWriter(clone_from=reader)
    props=writer.pages[0]['/Resources']['/Properties']
    key=next(a[1] for a,o in ContentStream(writer.pages[0].get_contents(),writer).operations if o==b'BDC' and a[0]=='/OC')
    props[key]=writer._add_object(dictionary(**{str(k).lstrip('/'):v for k,v in props[key].get_object().items()}))
    stream=BytesIO();writer.write(stream)
    with pytest.raises(EditError,match='capas'):
        plan.validate(stream.getvalue())


def test_gui_layer_actualtext_edit_save_reopen_and_undo(qtbot,window,tmp_path):
    from PySide6.QtGui import QTextCursor
    from test_rich_ui_v09 import idle,select
    source=document(layer=True);path=tmp_path/'marked.pdf';path.write_bytes(source)
    window.open_document(path);idle(qtbot,window)
    select(window,'BETA');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible() or bool(window.last_error),timeout=15000)
    assert window.canvas.editor.isVisible(),window.last_error
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.select(QTextCursor.Document);cursor.insertText('GAMMA')
    editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==1
    target=tmp_path/'edited.pdf';window.save_as(target);idle(qtbot,window)
    assert actual_texts(target.read_bytes())==['ALPHA GAMMA']
    assert_controls(source,target.read_bytes())
    window.open_document(target);idle(qtbot,window)
    select(window,'GAMMA');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible() or bool(window.last_error),timeout=15000)
    assert window.canvas.editor.isVisible(),window.last_error
    window.cancel();idle(qtbot,window)
    window.open_document(path);idle(qtbot,window)
    select(window,'BETA');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=15000)
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.select(QTextCursor.Document);cursor.insertText('GAMMA')
    editor.accept_draft();idle(qtbot,window)
    window.history('undo');idle(qtbot,window)
    assert 'ALPHA BETA' in ''.join(g.text for g in window.model.glyphs)
    assert path.read_bytes()==source


def test_complete_added_text_finds_default_page_end_in_a_previously_blank_tagged_page():
    from pdfmodder.composition import AddTextRequest,insert_text_pdf
    from tagged_corpus import make_tagged_pdf,audit_tagged
    original=make_tagged_pdf()
    with fitz.open(stream=original,filetype='pdf') as doc:
        doc.new_page(width=420,height=420)
        source=doc.tobytes()
    output,report=insert_text_pdf(source,AddTextRequest(2,30,50,240,40,'Nuevo texto'))
    assert report['verified'] and report['accessibility']['automatic_reading_order']
    assert audit_tagged(output)['reading_order']==audit_tagged(original)['reading_order']+'Nuevo texto'


def test_underlines_follow_the_original_layer_and_can_be_removed_on_reedit():
    source=document(actual=None,layer=True);model,ids=selection(source,'BETA')
    payload=selection_payload(source,0,ids)
    output,report=edit_rich_pdf(source,RichTextRequest(0,ids,
        [dict(r,text=r['text'].replace('BETA','GAMMA'),underline=True) for r in payload['runs']],
        rect=payload['rect'],auto_width=True,auto_height=True,auto_adapt=True))
    assert report['verified']
    model,ids=selection(output,'GAMMA');payload=selection_payload(output,0,ids)
    second,report=edit_rich_pdf(output,RichTextRequest(0,ids,
        [dict(r,underline=False) for r in payload['runs']],rect=payload['rect'],auto_adapt=True))
    assert report['verified']
    rendered=[]
    for data in (source,output,second):
        with fitz.open(stream=data,filetype='pdf') as doc:
            doc.set_layer(-1,basestate='OFF',on=[],off=list(doc.get_ocgs()))
            with fitz.open(stream=doc.tobytes(),filetype='pdf') as hidden:
                rendered.append(hidden[0].get_pixmap().samples)
    assert rendered[0]==rendered[1]==rendered[2]


def test_complete_character_actualtext_scopes_can_be_replaced_as_one_verified_block():
    with fitz.open() as doc:
        p=doc.new_page(width=340,height=230);x=30
        for char in 'ALPHA':
            p.insert_text((x,55),char,fontsize=12)
            stream=p.get_contents()[-1]
            doc.update_stream(stream,('/Span <</ActualText ('+char+') /Lang (es-ES)>> BDC\n').encode()+doc.xref_stream(stream)+b'\nEMC')
            x+=fitz.get_text_length(char,fontsize=12)
        p.insert_text((30,145),'CONTROL',fontsize=12)
        source=doc.tobytes()
    model,ids=selection(source,'ALPHA')
    output,report=edit_pdf(source,EditRequest(0,ids,text='GAMMA',auto_adapt=True,auto_width=True))
    assert report['verified'] and actual_texts(output)==['GAMMA','','','','']
