"""Styled clipboard text owns a new tag and validates final bytes against the original."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,FloatObject
import pytest

from pdfmodder.engine import edit_pdf,extract_page,transaction_write_v318
from pdfmodder.model import EditRequest,EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf,selection_payload
from pdfmodder.clipboard_ops_v170 import copy_selection_v170,apply_clipboard_v170,_resource_identity
from pdfmodder.worker import Session
from tagged_corpus import make_tagged_pdf,audit_tagged,CONTROL_TEXT


def ids_for(model,text):
    flat=''.join(g.text for g in model.glyphs);at=flat.index(text)
    return [g.id for g in model.glyphs[at:at+len(text)]]


def test_added_styled_text_checks_exact_final_bytes_against_original_once(monkeypatch):
    from pdfmodder import richtext
    source=make_tagged_pdf(include_objr=True)
    validate=richtext._validate;checked=[]
    def record(before,after,*args,**kwargs):
        checked.append((before,after));return validate(before,after,*args,**kwargs)
    monkeypatch.setattr(richtext,'_validate',record)
    output,report=edit_rich_pdf(source,RichTextRequest(0,[],[
        dict(text='NUEVO ',font_name='Helvetica',size=12,color=(0,0,0)),
        dict(text='ESTILO',font_name='Helvetica-Bold',size=12,color=(.5,0,0))],
        rect=(30,350,300,395),auto_adapt=True,auto_height=True))
    assert checked==[(source,output)]
    assert report['verified'] and report['accessibility']['automatic_reading_order']
    a=audit_tagged(source);b=audit_tagged(output)
    assert b['reading_order']==a['reading_order'].replace(CONTROL_TEXT,'NUEVO ESTILO'+CONTROL_TEXT)
    assert all(b['content'][k]==v for k,v in a['content'].items())
    assert '|' not in PdfReader(BytesIO(output)).pages[0].extract_text()


def test_added_styled_text_does_not_allow_damage_to_neighbor_graphics(monkeypatch):
    from pdfmodder import richtext
    write=richtext._write_rich_transaction
    def tamper(doc):
        doc[0].draw_rect((330,30,350,50),fill=(1,0,0));return write(doc)
    monkeypatch.setattr(richtext,'_write_rich_transaction',tamper)
    source=make_tagged_pdf()
    with pytest.raises(EditError,match='vectores|visuales'):
        edit_rich_pdf(source,RichTextRequest(0,[],[dict(text='NUEVO',font_name='Helvetica',size=12)],
                                           rect=(30,350,300,395),auto_adapt=True))


@pytest.mark.parametrize('edit_between',[False,True])
def test_tagged_copy_paste_keeps_mixed_styles_and_exact_save_undo_redo(tmp_path,edit_between):
    source=make_tagged_pdf(mixed_styles=True,include_objr=True)
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    writer.pages[0]['/Resources']['/Font']['/helv'].get_object()[NameObject('/PMNumber')]=FloatObject('905.27344')
    buffer=BytesIO();writer.write(buffer);source=buffer.getvalue()
    path=tmp_path/'source.pdf';path.write_bytes(source)
    session=Session(path,history_dir=tmp_path/'history',config_path=tmp_path/'fonts.json')
    try:
        model=session.page(0)['model'];ids=ids_for(model,'Mover PALABRA fin.')
        copied=copy_selection_v170(session,0,ids=ids,revision=model.revision)
        assert copied['text']=='Mover PALABRA fin.' and session.history.current==source
        if edit_between:
            ids=ids_for(model,'10/09/2026')
            changed,report=edit_pdf(source,EditRequest(0,ids,text='11/09/2026',auto_adapt=True))
            session.history.push(changed,report);session._clear_cache()
        before=session.history.current
        result=apply_clipboard_v170(session,'paste',0,revision=session.history.revision,
                                   bundle=copied['bundle'],point=(30,350),allow_overlap=True,auto_adapt=True)
        pasted=session.history.current
        assert result['report']['verified'] and result['report']['accessibility']['reading_order']=='page_end'
        with fitz.open(stream=pasted,filetype='pdf') as doc:
            model=extract_page(doc,0,pasted)
            new=[g for g in model.glyphs if g.origin[1]>350]
            assert len({g.font for g in new})==2
        target=tmp_path/'saved.pdf';session.save(target)
        assert target.read_bytes()==pasted
        session.navigate_history();assert session.history.current==before
        session.navigate_history(redo=True);assert session.history.current==pasted
        assert path.read_bytes()==source
    finally:session.close()


def test_clipboard_font_identity_survives_exact_binary32_serialization():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    writer.pages[0]['/Resources']['/Font']['/helv'].get_object()[NameObject('/PMNumber')]=FloatObject('905.27344')
    buffer=BytesIO();writer.write(buffer);source=buffer.getvalue()
    with fitz.open(stream=source,filetype='pdf') as doc:output=transaction_write_v318(doc)
    a=PdfReader(BytesIO(source));b=PdfReader(BytesIO(output))
    assert _resource_identity(a,0,'/helv',normalize_numbers=False)!=_resource_identity(b,0,'/helv',normalize_numbers=False)
    assert _resource_identity(a,0,'/helv')==_resource_identity(b,0,'/helv')
    b.pages[0]['/Resources']['/Font']['/helv'].get_object()[NameObject('/Encoding')]=NameObject('/MacRomanEncoding')
    assert _resource_identity(a,0,'/helv')!=_resource_identity(b,0,'/helv')


def test_partial_copy_reproduces_only_selection_and_can_paste_in_another_document(tmp_path):
    original=tmp_path/'original.pdf';original.write_bytes(make_tagged_pdf(mixed_styles=True))
    target=tmp_path/'other.pdf'
    with fitz.open() as doc:
        doc.new_page(width=420,height=420).insert_text((30,50),'CONTROL',fontname='cour')
        target.write_bytes(doc.tobytes())
    source=Session(original,history_dir=tmp_path/'source-history',config_path=tmp_path/'fonts.json')
    dest=Session(target,history_dir=tmp_path/'dest-history',config_path=tmp_path/'dest-fonts.json')
    try:
        model=source.page(0)['model']
        result=copy_selection_v170(source,0,ids=ids_for(model,'Mover PALABRA fin.'),revision=model.revision)
        assert result['bundle']['portable'] and not result['bundle']['font_error']
        pasted=apply_clipboard_v170(dest,'paste',0,revision=dest.history.revision,
                                   bundle=result['bundle'],point=(30,150),allow_overlap=True)
        assert pasted['report']['verified']
        with fitz.open(stream=dest.history.current,filetype='pdf') as doc:
            assert 'Mover PALABRA fin.' in doc[0].get_text() and 'CONTROL' in doc[0].get_text()
    finally:source.close();dest.close()


def test_plain_paste_can_append_beside_an_independent_marked_form_without_layout_adaptation(tmp_path):
    from test_marked_content_v303 import marked_pdf
    from tagged_corpus import dictionary
    from pypdf.generic import TextStringObject
    source=marked_pdf(([NameObject('/Span'),NameObject('/Marker')],b'BDC'),
        named=dictionary(ActualText=TextStringObject('ALPHA BETA')),form=True)
    path=tmp_path/'form.pdf';path.write_bytes(source)
    session=Session(path,history_dir=tmp_path/'history',config_path=tmp_path/'fonts.json')
    try:
        bundle=dict(version=1,kind='plain_text',text='NEW TEXT',font_name='Helvetica',rect=(0,0,160,40),portable=True)
        result=apply_clipboard_v170(session,'paste',0,revision=session.history.revision,bundle=bundle,
                                   point=(30,130),auto_adapt=False)
        assert result['report']['verified']
        with fitz.open(stream=session.history.current,filetype='pdf') as doc:
            assert 'ALPHA BETA' in doc[0].get_text() and 'NEW TEXT' in doc[0].get_text()
    finally:session.close()
