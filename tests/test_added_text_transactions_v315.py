"""Final-byte integrity and single transactions for added native text."""
import pymupdf as fitz
import pytest

from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, move_rich_pdf, selection_payload
from test_richtext_v09 import document, selection


def addition(data, text='Texto añadido'):
    return RichTextRequest(0, [], [dict(text=text, font_name='Helvetica',
        size=12., color=(0., 0., 0.), opacity=1.)],
        rect=(35., 180., 350., 225.), auto_width=True, auto_height=True)


def test_insertion_checks_exact_final_bytes_against_original_once(monkeypatch):
    from pdfmodder import richtext
    source=document()
    validate=richtext._validate
    checked=[]
    def record(before,after,*args,**kwargs):
        checked.append((before,after))
        return validate(before,after,*args,**kwargs)
    monkeypatch.setattr(richtext,'_validate',record)
    output,report=edit_rich_pdf(source,addition(source))
    assert checked==[(source,output)]
    assert report['verified'] and report['added_text']
    assert report['source_regions']==[]
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert doc[0].get_text().count('Texto añadido')==1
        assert '|' not in doc[0].get_text()


def test_insertion_still_rejects_damage_in_final_candidate(monkeypatch):
    from pdfmodder import richtext
    source=document()
    write=richtext._write_rich_transaction
    def tamper(doc):
        doc[0].draw_rect((300,250,320,270),fill=(1,0,0))
        return write(doc)
    monkeypatch.setattr(richtext,'_write_rich_transaction',tamper)
    with pytest.raises(EditError,match='vectores|visuales'):
        edit_rich_pdf(source,addition(source))


def test_plain_added_move_writes_once_and_keeps_logical_positions(monkeypatch):
    from pdfmodder import richtext,clipped_layout
    source,_=edit_rich_pdf(document(),addition(document()))
    ids=selection(source,'Texto añadido')
    before=selection_payload(source,0,ids)
    write=richtext._write_rich_transaction
    validate=richtext._validate
    written=[];checked=[]
    def record_write(doc):
        output=write(doc);written.append(output);return output
    def record_validate(first,last,*args,**kwargs):
        checked.append((first,last));return validate(first,last,*args,**kwargs)
    monkeypatch.setattr(richtext,'_write_rich_transaction',record_write)
    monkeypatch.setattr(richtext,'_validate',record_validate)
    output,report=move_rich_pdf(source,EditRequest(0,ids,dx=20,dy=15,allow_overlap=True))
    assert written==[output] and checked==[(source,output)]
    assert report['verified'] and report['rich_text_move']
    after=selection_payload(output,0,selection(output,'Texto añadido'))
    for a,b in zip(before['carets'],after['carets']):
        assert b['origin']==pytest.approx((a['origin'][0]+20,a['origin'][1]+15),abs=.002)


def test_plain_added_move_keeps_group_and_partial_metadata():
    from pdfmodder.objects import group_pdf,object_info
    source=document()
    source,_=edit_rich_pdf(source,addition(source))
    ids=selection(source,'añadido')
    source,_=group_pdf(source,0,[dict(kind='text',ids=ids)],name='Moved')
    output,report=move_rich_pdf(source,EditRequest(0,ids,dx=20,dy=15,allow_overlap=True))
    assert report['verified'] and object_info(output,0)['groups'][0]['valid']
    remaining=selection_payload(output,0,selection(output,'Texto '))
    assert remaining['text']=='Texto '
    moved=selection_payload(output,0,selection(output,'añadido'))
    edited,_=edit_rich_pdf(output,RichTextRequest(0,moved['ids'],
        [dict(run,text=run['text'].upper()) for run in moved['runs']],
        rect=moved['rect'],auto_width=True,allow_overlap=True))
    with fitz.open(stream=edited,filetype='pdf') as doc:
        assert 'AÑADIDO' in doc[0].get_text()


def test_moved_candidate_is_independently_checked_after_metadata_write(monkeypatch):
    from pdfmodder import richtext
    source=document()
    source,_=edit_rich_pdf(source,addition(source))
    update=richtext._move_rich_metadata
    def tamper(doc,*args):
        update(doc,*args)
        doc[0].insert_text((300,260),'EXTRA')
    monkeypatch.setattr(richtext,'_move_rich_metadata',tamper)
    with pytest.raises(EditError,match='operadores|glifos|tipografía'):
        move_rich_pdf(source,EditRequest(0,selection(source,'Texto añadido'),dx=20,dy=15))


def test_native_move_keeps_invisible_text_guard_after_redundant_analysis_removed():
    from pdfmodder.textlayout import edit_with_layout
    source=document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc[0].insert_text((35,260),'Invisible',fill_opacity=0)
        source=doc.tobytes()
    source,_=edit_rich_pdf(source,addition(source))
    with pytest.raises(EditError,match='invisible'):
        edit_with_layout(source,EditRequest(0,selection(source,'Invisible'),dx=20,dy=5))


def test_native_move_checks_original_permissions_before_form_isolation():
    from test_form_instances_v200 import form_document
    from pdfmodder.textlayout import edit_with_layout
    source=form_document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc.xref_set_key(doc[0].xref,'PDFModderRichText',
            fitz.get_pdf_str('[{"glyphs":[],"underlines":[]}]'))
        protected=doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw='test-owner',user_pw='',permissions=fitz.PDF_PERM_COPY)
    with pytest.raises(EditError,match='cifrado|permiso'):
        edit_with_layout(protected,EditRequest(0,[0,1,2,3],dx=20,dy=5))


def test_clipped_movement_fallback_still_keeps_owned_metadata():
    import json
    from dataclasses import asdict
    from test_clip_move_v150 import fixture,selection as clipped_selection
    source=fixture()
    _,selected=clipped_selection(source,'2026')
    records=[dict(text='2026',rect=(selected[0].bbox[0],selected[0].bbox[1],
        selected[-1].bbox[2],selected[-1].bbox[3]),underlines=[],paragraphs=[],
        glyphs=[dict(asdict(g),index=i) for i,g in enumerate(selected)])]
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc.xref_set_key(doc[0].xref,'PDFModderRichText',fitz.get_pdf_str(json.dumps(records)))
        source=doc.tobytes()
    output,report=move_rich_pdf(source,EditRequest(0,[g.id for g in selected],dx=12,dy=85))
    assert report['verified'] and report['clip_translated'] and report['rich_text_move']
    after=selection_payload(output,0,selection(output,'2026'))
    assert after['carets'][0]['origin']==pytest.approx(
        (selected[0].origin[0]+12,selected[0].origin[1]+85),abs=.035)


def test_session_releases_analysis_memory_when_suspended_and_closed(tmp_path):
    from pdfmodder.worker import Session
    path=tmp_path/'test.pdf';path.write_bytes(document())
    session=Session(path,history_dir=tmp_path)
    try:
        session.page(0)
        cache=session._analysis_cache_v315
        assert cache._state['syntax']
        session.suspend()
        assert cache._state['syntax_bytes']==0 and not cache._state['entries']
        session.resume()
        session.page(0)
        assert cache._state['syntax']
    finally:session.close()
    assert cache._state['syntax_bytes']==0 and not cache._state['entries']
