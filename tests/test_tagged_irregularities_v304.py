"""Preserve benign source tag irregularities without inventing semantic owners."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, ContentStream, DecodedStreamObject,
    FloatObject, NameObject, NumberObject, TextStringObject)

from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.tagged import analyze, assert_structure, ref
from tagged_corpus import dictionary, make_tagged_pdf
from test_engine import select


def encoded(writer):
    target=BytesIO();writer.write(target);return target.getvalue()


def duplicate(*,different_owner=False,mcr=False):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(mcr_references=mcr))))
    document=writer.root_object['/StructTreeRoot']['/K']
    span=document['/K'][0]['/K']
    content=span.raw_get('/K')
    if different_owner:
        other=document['/K'][1]['/K'][0].get_object()
        other[NameObject('/K')]=ArrayObject([other.raw_get('/K'),content])
    else:span[NameObject('/K')]=ArrayObject([content,content])
    return encoded(writer)


def orphan(*,text=False,empty_text=False,form_text=False,bad_parent=False,cycle=False,
           actual_text=False,parent_actual_text=False,semantic_role=False,shared_parent=False,
           form_graphics_depth=0):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page=writer.pages[0];tree=writer.root_object['/StructTreeRoot']
    parent=dictionary(S=NameObject('/P'),Pg=page.indirect_reference,Lang=TextStringObject('es-ES'))
    parent_ref=writer._add_object(parent)
    if shared_parent:tree[NameObject('/AuxParent')]=parent_ref
    leaf=dictionary(S=NameObject('/Span' if semantic_role else '/Artifact'),
                    Pg=page.indirect_reference,K=NumberObject(3),P=parent_ref)
    leaf_ref=writer._add_object(leaf)
    parent[NameObject('/K')]=ArrayObject([NumberObject(0),leaf_ref if not bad_parent else NumberObject(1)])
    if cycle:parent[NameObject('/P')]=leaf_ref
    if actual_text:leaf[NameObject('/ActualText')]=TextStringObject('unrelated')
    if parent_actual_text:parent[NameObject('/ActualText')]=TextStringObject('unrelated')
    tree['/ParentTree']['/Nums'][1].append(leaf_ref)
    ops=[([NameObject('/Artifact'),dictionary(MCID=NumberObject(3))],b'BDC'),([],b'q')]
    if text or empty_text:
        font=next(iter(page['/Resources']['/Font']))
        ops.extend([([],b'BT'),([font,NumberObject(9)],b'Tf'),([NumberObject(3)],b'Tr'),
                    ([TextStringObject('invisible' if text else '')],b'Tj'),([],b'ET')])
    if form_text:
        stream=DecodedStreamObject();stream.set_data(b'BT ET')
        stream[NameObject('/Type')]=NameObject('/XObject')
        stream[NameObject('/Subtype')]=NameObject('/Form')
        stream[NameObject('/BBox')]=ArrayObject([NumberObject(0),NumberObject(0),NumberObject(10),NumberObject(10)])
        form_ref=writer._add_object(stream)
        page['/Resources']['/XObject'][NameObject('/HiddenForm')]=form_ref
        ops.append(([NameObject('/HiddenForm')],b'Do'))
    if form_graphics_depth:
        nested=None
        for _ in range(form_graphics_depth):
            stream=DecodedStreamObject()
            stream.set_data(b'q /Nested Do Q' if nested else b'0 0 1 1 re f')
            stream[NameObject('/Type')]=NameObject('/XObject')
            stream[NameObject('/Subtype')]=NameObject('/Form')
            stream[NameObject('/BBox')]=ArrayObject([NumberObject(0),NumberObject(0),NumberObject(10),NumberObject(10)])
            if nested:stream[NameObject('/Resources')]=dictionary(XObject=dictionary(Nested=nested))
            nested=writer._add_object(stream)
        page['/Resources']['/XObject'][NameObject('/GraphicsForm')]=nested
        ops.append(([NameObject('/GraphicsForm')],b'Do'))
    ops.extend([([FloatObject(.7),FloatObject(.8),FloatObject(.9)],b'rg'),
                ([NumberObject(200),NumberObject(200),NumberObject(15),NumberObject(10)],b're'),
                ([],b'f'),([],b'Q'),([],b'EMC')])
    content=ContentStream(None,writer);content.operations=ops
    page['/Contents'].append(writer._add_object(content))
    return encoded(writer)


def edit_date(source):
    model,glyphs=select(source,'10/09/2026')
    ids=[g.id for g in glyphs];payload=selection_payload(source,0,ids)
    request=RichTextRequest(0,ids,[dict(run,text=run['text'].replace('10/09/2026','11/09/2026'))
                                   for run in payload['runs']],
                            rect=payload['rect'],revision=model.revision)
    return edit_rich_pdf(source,request)


@pytest.mark.parametrize('mcr',[False,True])
def test_repeated_exact_owner_is_preserved_when_editing(mcr):
    source=duplicate(mcr=mcr);before=analyze(source)
    assert before.source_irregularities==[{'kind':'repeated_same_owner','page':0,'mcid':0}]
    output,report=edit_date(source)
    assert report['verified'] and before.semantic()==analyze(output).semantic()
    with fitz.open(stream=source,filetype='pdf') as a,fitz.open(stream=output,filetype='pdf') as b:
        assert '11/09/2026' in b[0].get_text()
        assert a[1].get_pixmap().samples==b[1].get_pixmap().samples
        assert a.metadata==b.metadata


def test_repeated_mcid_with_different_owner_stays_blocked():
    with pytest.raises(EditError,match='propietarios diferentes'):analyze(duplicate(different_owner=True))


def test_repeated_source_mark_stays_blocked():
    with pytest.raises(EditError,match='repetido en la página'):analyze(make_tagged_pdf(defect='duplicate_mcid'))


def test_disconnected_graphical_artifact_and_exact_graph_are_preserved():
    source=orphan();before=analyze(source)
    assert len(before.semantic()['detached_nodes'])==2
    assert before.source_irregularities==[{'kind':'detached_graphical_artifact','page':0,'mcid':3}]
    output,report=edit_date(source)
    assert report['verified'] and assert_structure(source,output)
    assert before.semantic()==analyze(output).semantic()
    with fitz.open(stream=source,filetype='pdf') as a,fitz.open(stream=output,filetype='pdf') as b:
        assert a[0].get_drawings()==b[0].get_drawings()
        assert a[1].get_pixmap().samples==b[1].get_pixmap().samples


@pytest.mark.parametrize('options',[dict(text=True),dict(empty_text=True),dict(form_text=True),
    dict(actual_text=True),dict(parent_actual_text=True),dict(semantic_role=True),
    dict(bad_parent=True),dict(cycle=True)])
def test_unproven_disconnected_artifacts_stay_blocked(options):
    with pytest.raises(EditError,match='no coincide con ParentTree'):analyze(orphan(**options))


def test_nested_graphics_are_checked_and_depth_limit_is_a_controlled_rejection():
    assert analyze(orphan(form_graphics_depth=31)).detached_nodes
    with pytest.raises(EditError,match='no coincide con ParentTree'):
        analyze(orphan(form_graphics_depth=40))


@pytest.mark.parametrize('mutation',['language','extra_reference','different_parent_alias'])
def test_disconnected_graph_mutation_is_not_hidden_by_canonical_identity(mutation):
    source=orphan(shared_parent=mutation=='different_parent_alias')
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    leaf=writer.root_object['/StructTreeRoot']['/ParentTree']['/Nums'][1][3].get_object()
    parent=leaf['/P']
    if mutation=='language':parent[NameObject('/Lang')]=TextStringObject('en-GB')
    elif mutation=='extra_reference':parent['/K'].append(NumberObject(0))
    else:
        # Equal dictionaries are insufficient: replacing one shared alias must
        # either fail reciprocal ownership proof or change the canonical graph.
        alternate=writer._add_object(dictionary(**{str(k)[1:]:v for k,v in parent.items()}))
        leaf[NameObject('/P')]=alternate
    target=encoded(writer)
    with pytest.raises(EditError,match='cambios ajenos|no coincide con ParentTree'):
        assert_structure(source,target)
