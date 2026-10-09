"""Native text edits preserve declared paragraph styles without guessing boxes."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, FloatObject, NameObject, TextStringObject

from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.tagged import analyze, _preservable_layout_attributes
from tagged_corpus import audit_tagged, dictionary, make_tagged_pdf
from test_engine import select


def layout_style():
    return dictionary(O=NameObject('/Layout'), SpaceBefore=FloatObject(6), SpaceAfter=FloatObject(8),
        StartIndent=FloatObject(10), EndIndent=FloatObject(15), TextIndent=FloatObject(-4),
        TextAlign=NameObject('/Start'), WritingMode=NameObject('/LrTb'))


def styled_pdf(attributes, *, indirect=False, classed=False):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(include_objr=True))))
    tree=writer.root_object['/StructTreeRoot']
    paragraph=tree['/K']['/K'][0].get_object()
    paragraph[NameObject('/A')]=writer._add_object(attributes) if indirect else attributes
    if classed:
        paragraph[NameObject('/C')]=NameObject('/ParagraphClass')
        tree[NameObject('/ClassMap')]=dictionary(ParagraphClass=layout_style())
    output=BytesIO();writer.write(output)
    return output.getvalue()


def replacement(source):
    model,selected=select(source,'10/09/2026',x=100,y=100)
    ids=[g.id for g in selected]
    payload=selection_payload(source,0,ids)
    return RichTextRequest(0,ids,[dict(run,text=run['text'].replace('10/09/2026','11/09/2026'))
                                 for run in payload['runs']],rect=payload['rect'],revision=model.revision)


@pytest.mark.parametrize('indirect',[False,True])
def test_native_replacement_preserves_layout_style_neighbours_and_control_page(indirect):
    source=styled_pdf(layout_style(),indirect=indirect)
    before=analyze(source).semantic()
    output,report=edit_rich_pdf(source,replacement(source))
    assert report['verified'] and report['accessibility']['verified']
    assert analyze(output).semantic()==before
    old_audit,new_audit=audit_tagged(source),audit_tagged(output)
    assert new_audit['reading_order']==old_audit['reading_order'].replace('10/09/2026','11/09/2026',1)
    assert new_audit['content'][(0,1)]==old_audit['content'][(0,1)]
    with fitz.open(stream=source,filetype='pdf') as old,fitz.open(stream=output,filetype='pdf') as new:
        assert old[1].get_texttrace()==new[1].get_texttrace()
        assert old[1].get_pixmap(alpha=False).samples==new[1].get_pixmap(alpha=False).samples
    old_para=PdfReader(BytesIO(source)).trailer['/Root']['/StructTreeRoot']['/K']['/K'][0].get_object()
    new_para=PdfReader(BytesIO(output)).trailer['/Root']['/StructTreeRoot']['/K']['/K'][0].get_object()
    assert old_para['/A']==new_para['/A']


@pytest.mark.parametrize('key,value',[
    ('/BBox',ArrayObject([FloatObject(v) for v in (0,0,100,100)])),
    ('/Width',FloatObject(100)),('/Height',FloatObject(20)),
    ('/Color',ArrayObject([FloatObject(1),FloatObject(0),FloatObject(0)])),
    ('/UnknownLayoutKey',FloatObject(0)),('/O',NameObject('/Table')),
    ('/WritingMode',NameObject('/RlTb')),('/TextAlign',NameObject('/Middle')),
    ('/SpaceBefore',FloatObject(-1)),('/SpaceAfter',TextStringObject('eight')),
    ('/StartIndent',BooleanObject(True)),
])
def test_unverified_layout_semantics_remain_blocked(key,value):
    attributes=layout_style();attributes[NameObject(key)]=value
    source=styled_pdf(attributes)
    with pytest.raises(EditError,match='atributos de disposición o clases'):
        edit_rich_pdf(source,replacement(source))


@pytest.mark.parametrize('classed',[False,True])
def test_attribute_arrays_and_classes_remain_blocked(classed):
    attributes=layout_style() if classed else ArrayObject([layout_style()])
    source=styled_pdf(attributes,classed=classed)
    with pytest.raises(EditError,match='atributos de disposición o clases'):
        edit_rich_pdf(source,replacement(source))


def test_nonfinite_layout_style_values_are_never_admitted():
    attributes=layout_style();attributes[NameObject('/StartIndent')]=FloatObject(float('inf'))
    assert not _preservable_layout_attributes(attributes)
