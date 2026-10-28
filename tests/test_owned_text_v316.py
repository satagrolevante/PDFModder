"""Native owned streams preserve artwork and exact editing semantics."""
from dataclasses import replace
import hashlib
import json

import pymupdf as fitz
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError,EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf,move_rich_pdf,selection_payload
from test_richtext_v09 import selection


def source(rotation=0):
    with fitz.open() as doc:
        page=doc.new_page(width=420,height=350)
        page.draw_rect((10,10,400,330),color=(.2,.3,.4))
        page.set_cropbox((20,30,400,330));page.set_rotation(rotation)
        doc.new_page(width=420,height=350).insert_text((30,50),'UNCHANGED')
        return doc.tobytes()


def add(data,text='Hello world',underline=False):
    return edit_rich_pdf(data,RichTextRequest(0,[],[dict(text=text,font_name='Helvetica',size=12.,
        color=(0.,0.,0.),opacity=1.,underline=underline)],rect=(50,70,250,120),
        auto_width=True,auto_height=True,allow_overlap=True,auto_adapt=True))


def stream_hashes(data,page=0):
    with fitz.open(stream=data,filetype='pdf') as doc:
        return [hashlib.sha256(doc.xref_stream(ref)).hexdigest() for ref in doc[page].get_contents()]


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_add_and_move_keep_original_stream_exact_with_crop_and_rotation(rotation):
    data=source(rotation);originals=stream_hashes(data)
    current,report=add(data)
    assert report['verified'] and report['preserved_graphics_v316']
    assert all(item in stream_hashes(current) for item in originals)
    current,report=move_rich_pdf(current,EditRequest(0,selection(current,'Hello world'),
        dx=10,dy=20,allow_overlap=True))
    assert report['native_stream_v316'] and report['preserved_graphics_v316']
    assert all(item in stream_hashes(current) for item in originals)
    with fitz.open(stream=current,filetype='pdf') as doc:
        assert doc[0].get_text().count('Hello world')==1
        assert doc[1].get_text().strip()=='UNCHANGED'


def test_partial_edit_selection_and_partial_move_stay_in_small_native_layer():
    data=source();current,_=add(data)
    payload=selection_payload(current,0,selection(current,'world'))
    assert payload['native_stream_v316']
    current,report=edit_rich_pdf(current,RichTextRequest(0,payload['ids'],
        [dict(run,text='there') for run in payload['runs']],rect=payload['rect'],
        auto_width=True,auto_height=True,allow_overlap=True,auto_adapt=True))
    assert report['native_stream_v316'] and report['verified']
    current,report=move_rich_pdf(current,EditRequest(0,selection(current,'there'),dx=10,dy=15,allow_overlap=True))
    assert report['native_stream_v316'] and report['verified']
    payload=selection_payload(current,0,selection(current,'there'))
    assert payload['native_stream_v316'] and payload['text']=='there'
    assert all(item in stream_hashes(current) for item in stream_hashes(data))
    with fitz.open(stream=current,filetype='pdf') as doc:
        assert 'world' not in doc[0].get_text() and 'there' in doc[0].get_text()


def test_underlined_layer_moves_only_owned_rectangles():
    current,_=add(source(),underline=True)
    current,report=move_rich_pdf(current,EditRequest(0,selection(current,'Hello world'),dx=10,dy=20))
    assert report['native_stream_v316'] and report['underlines_moved']==len('Hello world')
    payload=selection_payload(current,0,selection(current,'world'))
    current,report=edit_rich_pdf(current,RichTextRequest(0,payload['ids'],
        [dict(run,text='there') for run in payload['runs']],rect=payload['rect'],
        auto_width=True,auto_height=True,allow_overlap=True))
    assert report['native_stream_v316'] and report['verified']


def test_owned_marker_cannot_authorize_unrelated_vector_paint():
    current,_=add(source())
    with fitz.open(stream=current,filetype='pdf') as doc:
        ref=doc[0].get_contents()[-1]
        content=doc.xref_stream(ref)+b'\nq 1 0 0 rg 5 5 10 10 re f Q\n'
        doc.update_stream(ref,content)
        records=json.loads(doc.xref_get_key(doc[0].xref,'PDFModderRichText')[1])
        records[-1]['native_stream_v316']['sha256']=hashlib.sha256(content).hexdigest()
        doc.xref_set_key(doc[0].xref,'PDFModderRichText',fitz.get_pdf_str(json.dumps(records)))
        current=doc.tobytes()
    with pytest.raises(EditError,match='independencia'):
        move_rich_pdf(current,EditRequest(0,selection(current,'Hello world'),dx=10,dy=20))


def test_automatic_wrapping_reaches_real_pdf_without_shrinking():
    data=source()
    current,report=edit_rich_pdf(data,RichTextRequest(0,[],
        [dict(text='many words that need to wrap within the visible page',font_name='Helvetica',size=12.)],
        rect=(280,60,292,65),auto_width=True,auto_adapt=True,allow_overlap=True))
    assert report['auto_adapt'] and report['line_count']>1
    with fitz.open(stream=current,filetype='pdf') as doc:
        model=extract_page(doc,0,current)
    assert {g.size for g in model.glyphs}=={12.}
    assert all(g.bbox[2]<=380.035 and g.bbox[3]<=300.035 for g in model.glyphs)


def test_failed_grafted_final_candidate_does_not_skip_integrity(monkeypatch):
    from pdfmodder import richtext
    data=source();write=richtext._write_rich_transaction
    def tamper(doc):
        if len(doc)==2:doc[0].draw_rect((300,250,320,270),fill=(1,0,0))
        return write(doc)
    monkeypatch.setattr(richtext,'_write_rich_transaction',tamper)
    with pytest.raises(EditError,match='vectores|visuales'):
        add(data)


def test_partial_move_respects_overlap_policy_with_text_in_another_stream():
    data=source()
    with fitz.open(stream=data,filetype='pdf') as doc:
        doc[0].insert_text((180,180),'NEIGHBOR',fontsize=12)
        data=doc.tobytes()
    current,_=add(data)
    with fitz.open(stream=current,filetype='pdf') as doc:model=extract_page(doc,0,current)
    chosen=model.selected(selection(current,'world'))
    neighbor=model.selected(selection(current,'NEIGHBOR'))[0]
    request=EditRequest(0,[g.id for g in chosen],
        dx=neighbor.origin[0]-chosen[0].origin[0],dy=neighbor.origin[1]-chosen[0].origin[1])
    with pytest.raises(EditError,match='vecino'):move_rich_pdf(current,request)
    output,report=move_rich_pdf(current,replace(request,allow_overlap=True))
    assert report['verified'] and report['overlap_count'] and report['warning']


def test_selection_preview_font_identity_belongs_to_original_document():
    current,_=add(source())
    payload=selection_payload(current,0,selection(current,'world'))
    assert payload['native_stream_v316']
    with fitz.open(stream=current,filetype='pdf') as doc:
        fonts={row[4]:row[0] for row in doc[0].get_fonts()}
    for run in payload['runs']:
        assert run['font_xref']==fonts[run['font_resource'].lstrip('/')]
        assert any(face['font_name']==run['font_name'] and face['font_xref']==run['font_xref']
                   for face in payload['font_previews'])


def test_tagged_document_keeps_semantic_movement_route():
    from pdfmodder.owned_text_v316 import _owned_selection
    current,_=add(source())
    with fitz.open(stream=current,filetype='pdf') as doc:
        model=extract_page(doc,0,current)
        ids=[g.id for g in model.glyphs]
        assert _owned_selection(doc,0,model,ids) is not None
        root=doc.get_new_xref();doc.update_object(root,'<< /Type /StructTreeRoot /K [] >>')
        doc.xref_set_key(doc.pdf_catalog(),'StructTreeRoot',f'{root} 0 R')
        assert _owned_selection(doc,0,model,ids) is None


def test_external_inherited_clip_retains_native_clip_checks():
    from pdfmodder.owned_text_v316 import _owned_selection,_isolated_layer,_new_stream,_contents
    current,_=add(source())
    with fitz.open(stream=current,filetype='pdf') as doc:
        refs=doc[0].get_contents();owned=refs[-1]
        # The original text is inside this clip; moving far right would hide it.
        prefix=_new_stream(doc,b'q 0 0 200 350 re W n\n')
        suffix=_new_stream(doc,b'Q\n')
        _contents(doc,0,[*refs[:-1],prefix,owned,suffix])
        data=doc.tobytes(garbage=0,no_new_id=True)
        model=extract_page(doc,0)
        ids=[g.id for g in model.glyphs]
        assert _owned_selection(doc,0,model,ids) is None
    assert _isolated_layer(data,0,model,ids) is None


def test_external_marked_scope_does_not_enter_unstructured_fast_route():
    from pdfmodder.owned_text_v316 import _owned_selection,_new_stream,_contents
    current,_=add(source())
    with fitz.open(stream=current,filetype='pdf') as doc:
        refs=doc[0].get_contents();owned=refs[-1]
        prefix=_new_stream(doc,b'/Artifact BMC\n');suffix=_new_stream(doc,b'EMC\n')
        _contents(doc,0,[*refs[:-1],prefix,owned,suffix])
        model=extract_page(doc,0)
        assert _owned_selection(doc,0,model,[g.id for g in model.glyphs]) is None
