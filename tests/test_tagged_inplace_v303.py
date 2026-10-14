"""In-place operators preserve mixed graphics and independently owned marks."""
from io import BytesIO
import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, FloatObject, NameObject, NumberObject, TextStringObject

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.tagged import analyze, semantic_paragraph_scopes
from tagged_corpus import dictionary, make_tagged_pdf
from test_engine import select, request_for


def changed_fixture(*,paint=False,table=False,nested_actual=False):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(mixed_styles=True))))
    tree=writer.root_object['/StructTreeRoot']
    if table:
        span=tree['/K']['/K'][0]['/K']
        span[NameObject('/A')]=dictionary(O=NameObject('/Table'),ColSpan=NumberObject(2),RowSpan=NumberObject(1))
    if paint or nested_actual:
        page=writer.pages[0];content=ContentStream(page.get_contents(),writer)
        ops=[];inside=False
        for args,op in content.operations:
            if op==b'BDC' and args[1].get('/MCID')==0:
                inside=True
                ops.append((args,op))
                if nested_actual:ops.append(([NameObject('/Span'),dictionary(ActualText=TextStringObject('Fecha: 10/09/2026'))],b'BDC'))
                continue
            if op==b'EMC' and inside:
                if nested_actual:ops.append(([],b'EMC'))
                if paint:ops.extend([([],b'q'),([FloatObject(.2),FloatObject(.4),FloatObject(.6)],b'rg'),
                    ([NumberObject(200),NumberObject(200),NumberObject(30),NumberObject(20)],b're'),([],b'f'),([],b'Q')])
                inside=False
            ops.append((args,op))
        content.operations=ops;page.replace_contents(content)
    output=BytesIO();writer.write(output);return output.getvalue()


def rich(source,text='10/09/2026',replacement='11/09/2026'):
    model,selected=select(source,text)
    ids=[g.id for g in selected];payload=selection_payload(source,0,ids)
    return RichTextRequest(0,ids,[dict(r,text=r['text'].replace(text,replacement)) for r in payload['runs']],
                           rect=payload['rect'],revision=model.revision)


def test_native_inplace_text_keeps_graphics_inside_same_mark():
    source=changed_fixture(paint=True)
    output,report=edit_rich_pdf(source,rich(source))
    assert report['verified'] and report['accessibility']['verified']
    assert analyze(source).semantic()==analyze(output).semantic()
    with fitz.open(stream=source,filetype='pdf') as a,fitz.open(stream=output,filetype='pdf') as b:
        assert a[0].get_drawings()==b[0].get_drawings()
        assert '11/09/2026' in b[0].get_text()
        assert a[1].get_pixmap().samples==b[1].get_pixmap().samples


def test_reconstructing_route_still_rejects_mixed_graphics():
    source=changed_fixture(paint=True)
    model,selected=select(source,'10/09/2026')
    with pytest.raises(EditError,match='combina texto'):
        edit_pdf(source,request_for(model,selected,text='11/09/2026'))


def test_full_deletion_across_three_marks_preserves_structure():
    source=make_tagged_pdf(mixed_styles=True)
    model,selected=select(source,'Mover PALABRA fin.')
    ids=[g.id for g in selected];payload=selection_payload(source,0,ids)
    output,report=edit_rich_pdf(source,RichTextRequest(0,ids,[],rect=payload['rect'],revision=model.revision))
    assert report['accessibility']['mcids']==[1,2,3]
    assert analyze(source).semantic()==analyze(output).semantic()
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert 'PALABRA' not in doc[0].get_text()
        assert '10/09/2026' in doc[0].get_text()


def test_table_grid_attributes_survive_text_only_edit():
    source=changed_fixture(table=True)
    output,report=edit_rich_pdf(source,rich(source))
    assert report['accessibility']['verified']
    assert analyze(source).semantic()==analyze(output).semantic()


def test_native_edit_retains_existing_decoration_attributes():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(changed_fixture(paint=True))))
    span=writer.root_object['/StructTreeRoot']['/K']['/K'][0]['/K']
    span[NameObject('/A')]=dictionary(O=NameObject('/Layout'),
        TextDecorationType=NameObject('/Underline'),
        TextDecorationColor=ArrayObject([FloatObject(0),FloatObject(0),FloatObject(0)]))
    target=BytesIO();writer.write(target);source=target.getvalue()
    output,report=edit_rich_pdf(source,rich(source))
    assert report['verified'] and analyze(source).semantic()==analyze(output).semantic()
    with pytest.raises(EditError,match='decoración original'):
        req=rich(source,replacement='100100100/09/2026')
        req.auto_width=True
        edit_rich_pdf(source,req)


def test_new_nested_actualtext_is_not_silently_left_stale():
    source=changed_fixture(nested_actual=True)
    with pytest.raises(EditError,match='semánticas'):
        edit_rich_pdf(source,rich(source))


def test_model_receives_complete_paragraph_ownership_without_probe_recursion():
    source=make_tagged_pdf(mixed_styles=True)
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    model_ids={g.id for g in model.glyphs if 140<g.origin[1]<160}
    assert any(set(ids)==model_ids for ids in model.semantic_paragraph_scopes)


@pytest.mark.parametrize('span', [NumberObject(0),FloatObject(1.5),TextStringObject('2')])
def test_invalid_table_spans_remain_blocked(span):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(changed_fixture(table=True))))
    writer.root_object['/StructTreeRoot']['/K']['/K'][0]['/K']['/A'][NameObject('/ColSpan')]=span
    output=BytesIO();writer.write(output)
    with pytest.raises(EditError,match='atributos de tabla'):
        edit_rich_pdf(output.getvalue(),rich(output.getvalue()))
