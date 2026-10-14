"""Orphan associations permit edits; useful semantics and layers remain guarded."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, ContentStream,
    DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject,
    TextStringObject)

from pdfmodder.engine import extract_page
from pdfmodder.marked_content_v303 import MARKED_ISSUE
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.untag_v180 import remove_tags
from pdfmodder.validation import page_issues
from tagged_corpus import make_tagged_pdf


def marked_pdf(opening, *, closing=True, named=None, form=False):
    with fitz.open() as doc:
        doc.new_page(width=300,height=220).insert_text((30,60),'ALPHA BETA',fontsize=12)
        source=doc.tobytes()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    page=writer.pages[0]
    ops=ContentStream(page.get_contents(),writer).operations
    stream=DecodedStreamObject()
    content=ContentStream(None,writer)
    content.operations=[opening,*ops,*([([],b'EMC')] if closing else [])]
    stream.set_data(content.get_data())
    if named is not None:
        page['/Resources'][NameObject('/Properties')]=DictionaryObject({NameObject('/Marker'):named})
    if form:
        # The invoked Form's own Properties shadow the page namespace.
        resources=DictionaryObject(dict(page['/Resources']))
        if named is not None:
            page['/Resources'][NameObject('/Properties')]=DictionaryObject({NameObject('/Marker'):DictionaryObject({NameObject('/MCID'):NumberObject(99)})})
        stream.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                       NameObject('/BBox'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(300),NumberObject(220)]),
                       NameObject('/Resources'):resources})
        page['/Resources'][NameObject('/XObject')]=DictionaryObject({NameObject('/F'):writer._add_object(stream)})
        call=DecodedStreamObject();call.set_data(b'/F Do\n')
        page[NameObject('/Contents')]=writer._add_object(call)
    else:page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);return out.getvalue()


@pytest.mark.parametrize('named',[False,True])
def test_app_created_tagless_pdf_can_be_edited_without_removing_wrappers(named):
    source,_=remove_tags(make_tagged_pdf(named_properties=named))
    with fitz.open(stream=source,filetype='pdf') as doc:
        model=extract_page(doc,0,source)
        target='10/09/2026';text=''.join(g.text for g in model.glyphs);start=text.index(target)
        ids=[g.id for g in model.glyphs[start:start+len(target)]]
    assert MARKED_ISSUE not in model.issues
    payload=selection_payload(source,0,ids)
    out,report=edit_rich_pdf(source,RichTextRequest(0,ids,
        [dict(r,text=r['text'].replace('10/09/2026','11/09/2026')) for r in payload['runs']],
        rect=payload['rect'],revision=payload['revision']))
    assert report['verified']
    before=PdfReader(BytesIO(source));after=PdfReader(BytesIO(out))
    old_marks=[(a,o) for a,o in ContentStream(before.pages[0].get_contents(),before).operations if o in (b'BMC',b'BDC',b'EMC')]
    new_marks=[(a,o) for a,o in ContentStream(after.pages[0].get_contents(),after).operations if o in (b'BMC',b'BDC',b'EMC')]
    assert old_marks==new_marks and '/StructTreeRoot' not in after.trailer['/Root']
    assert '11/09/2026' in after.pages[0].extract_text()
    with fitz.open(stream=source,filetype='pdf') as a,fitz.open(stream=out,filetype='pdf') as b:
        assert a[1].get_pixmap().samples==b[1].get_pixmap().samples


@pytest.mark.parametrize('key',['/ActualText','/Alt','/E','/OC','/BBox','/Unknown'])
@pytest.mark.parametrize('form',[False,True])
def test_semantic_unknown_and_geometric_properties_remain_blocked_in_forms(key,form):
    props=DictionaryObject({NameObject('/MCID'):NumberObject(0),NameObject(key):TextStringObject('preserved')})
    source=marked_pdf(([NameObject('/Span'),NameObject('/Marker')],b'BDC'),named=props,form=form)
    assert MARKED_ISSUE in page_issues(source,0)
    assert PdfReader(BytesIO(source)).pages[0]['/Resources']['/Properties']['/Marker'] is not None


@pytest.mark.parametrize('tag',['/OC','/ReversedChars','/PMT','/PMParagraph'])
def test_special_scopes_are_not_blessed_as_plain_associations(tag):
    source=marked_pdf(([NameObject(tag)],b'BMC'))
    assert MARKED_ISSUE in page_issues(source,0)


@pytest.mark.parametrize('mcid',[NumberObject(-1),FloatObject(.5),BooleanObject(False)])
def test_malformed_mcid_is_blocked(mcid):
    source=marked_pdf(([NameObject('/Span'),DictionaryObject({NameObject('/MCID'):mcid})],b'BDC'))
    assert MARKED_ISSUE in page_issues(source,0)


@pytest.mark.parametrize('form',[False,True])
def test_unclosed_scope_is_blocked_even_inside_invoked_form(form):
    source=marked_pdf(([NameObject('/Artifact')],b'BMC'),closing=False,form=form)
    assert MARKED_ISSUE in page_issues(source,0)


def test_resolved_nonsemantic_artifact_and_custom_mcid_scope_are_accepted():
    artifact=DictionaryObject({NameObject('/Type'):NameObject('/Pagination'),NameObject('/Subtype'):NameObject('/Header')})
    assert MARKED_ISSUE not in page_issues(marked_pdf(([NameObject('/Artifact'),NameObject('/Marker')],b'BDC'),named=artifact),0)
    assert MARKED_ISSUE not in page_issues(marked_pdf(([NameObject('/SourceCustomRole'),DictionaryObject({NameObject('/MCID'):NumberObject(4)})],b'BDC')),0)


def test_missing_named_properties_and_orphan_emc_remain_blocked():
    assert MARKED_ISSUE in page_issues(marked_pdf(([NameObject('/Span'),NameObject('/Missing')],b'BDC')),0)
    assert MARKED_ISSUE in page_issues(marked_pdf(([],b'EMC'),closing=False),0)


@pytest.mark.parametrize('box',[
    ArrayObject([NumberObject(1),NumberObject(2),NumberObject(0),NumberObject(5)]),
    ArrayObject([NumberObject(1),NumberObject(2),NumberObject(5)]),
    ArrayObject([BooleanObject(False),NumberObject(2),NumberObject(5),NumberObject(6)]),
])
def test_malformed_artifact_bbox_is_not_a_compatible_advisory_extent(box):
    source=marked_pdf(([NameObject('/Artifact'),DictionaryObject({NameObject('/BBox'):box})],b'BDC'))
    assert MARKED_ISSUE in page_issues(source,0)


def test_artifact_bbox_is_retained_and_edited_text_must_stay_inside_it():
    props=DictionaryObject({NameObject('/Type'):NameObject('/Pagination'),
        NameObject('/Subtype'):NameObject('/Header'),
        NameObject('/BBox'):ArrayObject([NumberObject(v) for v in (20,145,110,180)])})
    source=marked_pdf(([NameObject('/Artifact'),props],b'BDC'))
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    assert MARKED_ISSUE not in model.issues
    ids=[g.id for g in model.glyphs];payload=selection_payload(source,0,ids)
    output,report=edit_rich_pdf(source,RichTextRequest(0,ids,
        [dict(payload['runs'][0],text='ALPHA')],rect=payload['rect'],auto_width=True))
    assert report['verified']
    reader=PdfReader(BytesIO(output))
    after_props=next(args[1] for args,op in ContentStream(reader.pages[0].get_contents(),reader).operations if op==b'BDC')
    assert after_props['/BBox']==props['/BBox']
    from pdfmodder.model import EditError
    with pytest.raises(EditError,match='caja.*encabezado|caja.*pie'):
        edit_rich_pdf(source,RichTextRequest(0,ids,
            [dict(payload['runs'][0],text='ALPHA BETA ALPHA BETA')],rect=payload['rect'],auto_width=True))
