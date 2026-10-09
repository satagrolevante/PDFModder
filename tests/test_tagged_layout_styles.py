"""Tagged edits preserve style and containers; tight text boxes are updated."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, FloatObject, NameObject, NumberObject, TextStringObject

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.tagged import analyze, _preservable_layout_attributes
from tagged_corpus import audit_tagged, dictionary, make_tagged_pdf
from test_engine import request_for, select


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
    ('/BBox',ArrayObject([FloatObject(v) for v in (0,0,100)])),
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
def test_attribute_arrays_and_resolved_classes_preserve_style(classed):
    attributes=layout_style() if classed else ArrayObject([layout_style()])
    source=styled_pdf(attributes,classed=classed)
    output,report=edit_rich_pdf(source,replacement(source))
    assert report['accessibility']['verified']
    assert analyze(source).semantic()==analyze(output).semantic()


def boxed_pdf(*,loose=False,classed=False,rotated_crop=False,actual_text=False):
    base=make_tagged_pdf(actual_text='Fecha: 10/09/2026' if actual_text else None,
                         actual_on='paragraph')
    if rotated_crop:
        with fitz.open(stream=base,filetype='pdf') as doc:
            doc[0].set_cropbox(fitz.Rect(20,30,400,410))
            doc[0].set_rotation(90)
            base=doc.tobytes(garbage=0)
    with fitz.open(stream=base,filetype='pdf') as doc:
        model=extract_page(doc,0)
        structure=analyze(base)
        contexts=structure.glyph_contexts(0,model)
        page=doc[0];page.set_rotation(0)
        inverse=~page.transformation_matrix
        box=fitz.Rect()
        for glyph in model.glyphs:
            if contexts[glyph.id] in ({0} if loose else {0,1}):box|=fitz.Rect(glyph.bbox)*inverse
    if loose:box+=(-20,-20,50,20)
    attributes=dictionary(O=NameObject('/Layout'),Placement=NameObject('/Block'),
                          BBox=ArrayObject([FloatObject(round(v,3)) for v in box]))
    writer=PdfWriter(clone_from=PdfReader(BytesIO(base)))
    tree=writer.root_object['/StructTreeRoot']
    paragraph=tree['/K']['/K'][0].get_object()
    paragraph[NameObject('/S')]=NameObject('/Table') if loose else NameObject('/Div')
    if not loose:
        # The box encloses a second, unselected MCID as well as the date.
        movement=tree['/K']['/K'].pop(1)
        movement.get_object()[NameObject('/P')]=paragraph.indirect_reference
        paragraph[NameObject('/K')]=ArrayObject([paragraph.raw_get('/K'),movement])
    if classed:
        tree[NameObject('/ClassMap')]=dictionary(TextBox=writer._add_object(attributes))
        paragraph[NameObject('/C')]=NameObject('/TextBox')
        # An unrelated node uses the same class; its definition stays intact.
        tree['/K']['/K'][-1].get_object()[NameObject('/C')]=NameObject('/TextBox')
        paragraph[NameObject('/R')]=NumberObject(2)
    else:
        shared=writer._add_object(attributes)
        paragraph[NameObject('/A')]=shared
        tree['/K']['/K'][-1].get_object()[NameObject('/A')]=shared
    output=BytesIO();writer.write(output)
    return output.getvalue()


def test_native_date_in_table_preserves_container_box_and_actualtext():
    source=boxed_pdf(loose=True,actual_text=True)
    before=analyze(source).semantic()
    output,report=edit_rich_pdf(source,replacement(source))
    after=analyze(output).semantic()
    paragraph=('K',0)
    expected=before['nodes'][paragraph]['/ActualText'].replace('10/09/2026','11/09/2026')
    before['nodes'][paragraph]['/ActualText']=expected
    assert after==before
    assert report['accessibility']['actual_text_updates']==1
    assert report['accessibility']['layout_attribute_updates']==0


@pytest.mark.parametrize('classed,rich',[(False,False),(True,True)])
@pytest.mark.parametrize('rotated_crop',[False,True])
def test_tight_box_updates_private_attributes_and_preserves_shared_values(classed,rich,rotated_crop):
    source=boxed_pdf(classed=classed,rotated_crop=rotated_crop)
    # Use a wider digit while retaining the same font, baseline and MCID.
    model,selected=select(source,'10/09/2026')
    if rich:
        payload=selection_payload(source,0,[g.id for g in selected])
        request=RichTextRequest(0,[g.id for g in selected],
            [dict(run,text=run['text'].replace('10/09/2026','100/09/2026')) for run in payload['runs']],
            rect=payload['rect'],auto_width=True,revision=model.revision)
        output,report=edit_rich_pdf(source,request)
    else:
        output,report=edit_pdf(source,request_for(model,selected,text='100/09/2026',width=100))
    before,after=analyze(source),analyze(output)
    paragraph=('K',0)
    control=('K',2)
    assert report['accessibility']['layout_attribute_updates']==1
    expected=before.semantic()
    expected['nodes'][paragraph]['/A']=after.semantic()['nodes'][paragraph]['/A']
    assert expected==after.semantic()
    assert before.semantic()['nodes'][control]==after.semantic()['nodes'][control]
    node=after.nodes[paragraph]
    attributes=node['/A']
    if classed:
        assert attributes[1]==2
        attributes=attributes[0]
    with fitz.open(stream=output,filetype='pdf') as doc:
        model=extract_page(doc,0)
        contexts=after.glyph_contexts(0,model)
        page=doc[0];page.set_rotation(0)
        inverse=~page.transformation_matrix
        actual=fitz.Rect()
        for glyph in model.glyphs:
            if contexts[glyph.id] in {0,1}:actual|=fitz.Rect(glyph.bbox)*inverse
    assert tuple(attributes['/BBox'])==pytest.approx(tuple(actual),abs=.035)


def test_nonfinite_layout_style_values_are_never_admitted():
    attributes=layout_style();attributes[NameObject('/StartIndent')]=FloatObject(float('inf'))
    assert not _preservable_layout_attributes(attributes)
