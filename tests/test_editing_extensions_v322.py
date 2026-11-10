"""User-facing extensions: local scopes, reconstruction and semantic blocks."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
import pytest
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject

from pdfmodder.engine import edit_pdf,extract_page
from pdfmodder.model import EditRequest,EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf,selection_payload
from pdfmodder.search_replace import find_matches,replace_matches
from test_form_instances_v200 import form_document,selection


FONT=str(Path(__file__).resolve().parents[1]/'assets/fonts/LiberationSans-Regular.ttf')


@pytest.mark.parametrize('group,layer',[(True,False),(False,True),(True,True)])
def test_one_reused_instance_keeps_group_and_layer_properties(group,layer):
    source=form_document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        xref=doc[0].get_xobjects()[0][0]
        if group:doc.xref_set_key(xref,'Group','<< /S /Transparency /I true /K false >>')
        if layer:
            ocg=doc.add_ocg('Capa del documento',on=True)
            doc.xref_set_key(xref,'OC',f'{ocg} 0 R')
        source=doc.tobytes()
    model,ids=selection(source)
    output,report=edit_pdf(source,EditRequest(0,ids,text='2026',auto_adapt=True))
    assert report['verified'] and report['form_isolation']['shared_objects_unchanged']
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert after[0].get_text().count('2026')==1 and after[0].get_text().count('2025')==1
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        edited=[x for x in after[0].get_xobjects() if x[1].startswith('PMInstanceEdited')]
        assert edited
        if group:assert after.xref_get_key(edited[0][0],'Group')[0]=='dict'
        if layer:
            assert after.xref_get_key(edited[0][0],'OC')[0]=='xref'
            before.set_layer(-1,basestate='OFF',on=[],off=list(before.get_ocgs()))
            after.set_layer(-1,basestate='OFF',on=[],off=list(after.get_ocgs()))
            with fitz.open(stream=before.tobytes(),filetype='pdf') as hidden_before, \
                    fitz.open(stream=after.tobytes(),filetype='pdf') as hidden_after:
                assert hidden_before[0].get_pixmap().samples==hidden_after[0].get_pixmap().samples


def text_document(text='uno dos', second='tres cuatro'):
    with fitz.open() as doc:
        p=doc.new_page(width=340,height=220)
        p.insert_text((30,50),text,fontsize=12)
        p.insert_text((30,65),second,fontsize=12)
        p.insert_text((30,160),'CONTROL',fontsize=12)
        return doc.tobytes()


def test_multiline_phrase_uses_rich_replacement_and_keeps_other_text():
    source=text_document()
    hits=find_matches(source,'dos\ntres')
    assert len(hits)==1 and hits[0]['multiline']
    output,report=replace_matches(source,hits,'texto nuevo')
    assert report['verified']
    with fitz.open(stream=output,filetype='pdf') as doc:
        text=doc[0].get_text()
        assert 'texto nuevo' in text and 'CONTROL' in text and 'uno' in text and 'cuatro' in text
    assert len(find_matches(source,'dos tres'))==1


def custom_cmap_document():
    with fitz.open() as doc:
        p=doc.new_page(width=340,height=220)
        p.insert_font(fontname='Custom',fontfile=FONT)
        p.insert_text((30,50),'Texto original',fontname='Custom',fontsize=12)
        p.insert_text((30,160),'CONTROL',fontsize=12)
        data=doc.tobytes()
    reader=PdfReader(BytesIO(data));writer=PdfWriter(clone_from=reader)
    font=writer.pages[0]['/Resources']['/Font']['/Custom'].get_object()
    stream=DecodedStreamObject();stream.set_data(b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n'
        b'/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> def\n'
        b'/CMapName /CustomIdentity def /CMapType 1 def /WMode 0 def\n'
        b'1 begincodespacerange <0000> <FFFF> endcodespacerange\n'
        b'1 begincidrange <0000> <FFFF> 0 endcidrange endcmap CMapName currentdict /CMap defineresource pop end end')
    font[NameObject('/Encoding')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);return out.getvalue()


def test_explicit_reconstruction_retires_real_custom_codes_and_keeps_neighbor():
    source=custom_cmap_document()
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    ids=[g.id for g in model.glyphs if g.origin[1]<80]
    bounds=fitz.Rect(model.selected(ids)[0].bbox)
    for g in model.selected(ids):bounds|=fitz.Rect(g.bbox)
    req=RichTextRequest(0,ids,[dict(text='Texto reconstruido',font_name='LiberationSans',font_file=FONT,
        size=12,color=(0,0,0),opacity=1)],rect=tuple(bounds),revision=model.revision,
        auto_width=True,auto_height=True,auto_adapt=True,reconstruct=True)
    output,report=edit_rich_pdf(source,req)
    assert report['verified'] and report['reconstruction']
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert 'Texto reconstruido' in after[0].get_text() and 'Texto original' not in after[0].get_text()
        assert 'CONTROL' in after[0].get_text()
        assert before[0].get_pixmap(clip=(0,120,340,220)).samples==after[0].get_pixmap(clip=(0,120,340,220)).samples


def test_automatic_area_can_extend_only_the_selected_clipped_text_scope():
    from test_clipped_fields_v321 import document,request,trace
    source=document()
    req=replace(request(source,'ALFA BETA ORGANIC MAS TEXTO'),auto_adapt=True,allow_overlap=True)
    output,report=edit_rich_pdf(source,req)
    assert report['verified'] and 'ALFA BETA ORGANIC MAS TEXTO' in trace(output)
    assert 'NEIGHBOR' in trace(output)


def test_advanced_font_composition_preserves_tagged_paragraph():
    from tagged_corpus import make_tagged_pdf,audit_tagged
    from pdfmodder.tagged import analyze_readonly
    source=make_tagged_pdf()
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    text=''.join(g.text for g in model.glyphs);at=text.index('10/09/2026')
    ids=[g.id for g in model.glyphs[at:at+10]]
    payload=selection_payload(source,0,ids)
    run=dict(payload['runs'][0],text='11/09/2026',font_name='LiberationSans',font_file=FONT,
             font_resource=None,font_xref=None,font_features={'liga':1,'kern':1})
    output,report=edit_rich_pdf(source,RichTextRequest(0,ids,[run],rect=payload['rect'],
        revision=model.revision,auto_width=True,auto_height=True,auto_adapt=True))
    assert report['verified'] and report['accessibility']['verified']
    assert analyze_readonly(source).semantic()==analyze_readonly(output).semantic()
    assert '11/09/2026' in PdfReader(BytesIO(output)).pages[0].extract_text()
    with fitz.open(stream=output,filetype='pdf') as doc:actual=extract_page(doc,0,output)
    joined=''.join(g.text for g in actual.glyphs);start=joined.index('11/09/2026')
    contexts=analyze_readonly(output).glyph_contexts(0,actual)
    assert {contexts[g.id] for g in actual.glyphs[start:start+10]}=={0}


def test_compatible_tagged_spans_can_be_replaced_as_one_block():
    from tagged_corpus import make_tagged_pdf,audit_tagged
    source=make_tagged_pdf(mixed_styles=True)
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    text=''.join(g.text for g in model.glyphs);at=text.index('Mover PALABRA fin.')
    ids=[g.id for g in model.glyphs[at:at+len('Mover PALABRA fin.')]]
    payload=selection_payload(source,0,ids)
    runs=[dict(payload['runs'][0],text='Bloque completo modificado',font_name='Helvetica',font_file=None,
               font_resource=None,font_xref=None)]
    output,report=edit_rich_pdf(source,RichTextRequest(0,ids,runs,rect=payload['rect'],revision=model.revision,
        auto_width=True,auto_height=True,auto_adapt=True))
    assert report['verified'] and report['accessibility']['verified']
    assert 'Bloque completo modificado' in audit_tagged(output)['reading_order']


@pytest.mark.parametrize('group',[False,True])
def test_form_text_inherits_its_page_tag_and_can_be_edited_in_isolation(group):
    from tagged_corpus import make_tagged_pdf
    from pdfmodder.tagged import analyze_readonly
    from pdfmodder.clipping import _serialize
    from pypdf.generic import ContentStream,DictionaryObject,ArrayObject,NumberObject
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page=writer.pages[0];ops=ContentStream(page.get_contents(),writer).operations
    target=next(i for i,(a,o) in enumerate(ops) if o in (b'Tj',b'TJ') and '10/09/2026' in str(a))
    begin=max(i for i,(a,o) in enumerate(ops[:target]) if o==b'BT')
    end=next(i for i,(a,o) in enumerate(ops[target:],target) if o==b'ET')
    resources=DictionaryObject(dict(page['/Resources']))
    resources[NameObject('/XObject')]=DictionaryObject(dict(resources['/XObject'].get_object()))
    form=DecodedStreamObject();form.set_data(_serialize(ops[begin:end+1]))
    form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
        NameObject('/BBox'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(420),NumberObject(420)]),
        NameObject('/Resources'):resources})
    if group:
        from pypdf.generic import BooleanObject
        form[NameObject('/Group')]=DictionaryObject({NameObject('/S'):NameObject('/Transparency'),NameObject('/I'):BooleanObject(True)})
    page['/Resources']['/XObject'][NameObject('/DateForm')]=writer._add_object(form)
    stream=DecodedStreamObject();stream.set_data(_serialize(ops[:begin]+[([NameObject('/DateForm')],b'Do')]+ops[end+1:]))
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);source=out.getvalue()
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    text=''.join(g.text for g in model.glyphs);at=text.index('10/09/2026')
    ids=[g.id for g in model.glyphs[at:at+10]]
    output,report=edit_pdf(source,EditRequest(0,ids,text='11/09/2026',auto_adapt=True))
    assert report['verified'] and report['form_isolation']['shared_objects_unchanged']
    assert analyze_readonly(source).semantic()==analyze_readonly(output).semantic()
    assert '11/09/2026' in PdfReader(BytesIO(output)).pages[0].extract_text()


def test_complete_footer_can_grow_its_advisory_box_with_properties_retained():
    from test_marked_content_v303 import marked_pdf
    from pypdf.generic import DictionaryObject,ArrayObject,NumberObject
    props=DictionaryObject({NameObject('/Type'):NameObject('/Pagination'),NameObject('/Subtype'):NameObject('/Footer'),
        NameObject('/BBox'):ArrayObject([NumberObject(v) for v in (20,145,110,180)])})
    source=marked_pdf(([NameObject('/Artifact'),props],b'BDC'))
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    ids=[g.id for g in model.glyphs if g.origin[1]<100]
    payload=selection_payload(source,0,ids)
    request=RichTextRequest(0,ids,[dict(payload['runs'][0],text='Texto de pie mucho mas largo')],
        rect=payload['rect'],revision=model.revision,auto_width=True,auto_height=True,auto_adapt=True)
    output,report=edit_rich_pdf(source,request)
    assert report['verified']
    from pypdf.generic import ContentStream
    reader=PdfReader(BytesIO(output));ops=ContentStream(reader.pages[0].get_contents(),reader).operations
    current=next(a[1] for a,o in ops if o==b'BDC' and a[0]=='/Artifact')
    assert current['/Type']=='/Pagination' and current['/Subtype']=='/Footer'
    assert current['/BBox'][2]>props['/BBox'][2]
