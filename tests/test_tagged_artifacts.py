"""Native decorative-header edits preserve all logical neighbours and tags."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, FloatObject, NameObject, TextStringObject

from pdfmodder.clipping import operator_glyph_map
from pdfmodder.engine import extract_page
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.tagged import analyze
from pdfmodder.tagged_artifacts import verified_artifact_selection
from tagged_corpus import audit_tagged, dictionary, make_tagged_pdf


def header_pdf(*, named=False, semantic=None, wrapper=False, second=False, bbox=None,
               rotation=0, crop=None, include_objr=True):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(include_objr=include_objr))))
    page = writer.pages[0]
    props = dictionary(Type=NameObject('/Pagination'), Subtype=NameObject('/Header'))
    if semantic:
        props[NameObject(semantic)] = TextStringObject('Semantic header')
    if bbox is not None:
        props[NameObject('/BBox')] = ArrayObject([FloatObject(value) for value in bbox])
    if named:
        resources = page['/Resources']
        properties = dictionary()
        properties[NameObject('/HeaderArtifact')] = writer._add_object(props)
        resources[NameObject('/Properties')] = properties
        opening = b'/Artifact /HeaderArtifact BDC\n'
    else:
        buffer = BytesIO(); props.write_to_stream(buffer)
        opening = b'/Artifact ' + buffer.getvalue() + b' BDC\n'
    text = b'q\n' + opening + b'BT /helv 12 Tf 1 0 0 1 48 370 Tm (Header 2026) Tj ET\nEMC\nQ\n'
    if wrapper:
        text = b'/ReversedChars BMC\n' + text + b'EMC\n'
    if second:
        text += b'q\n/Artifact BMC\nBT /helv 12 Tf 1 0 0 1 48 340 Tm (Other header) Tj ET\nEMC\nQ\n'
    stream = DecodedStreamObject(); stream.set_data(text)
    page[NameObject('/Contents')] = ArrayObject([*page['/Contents'], writer._add_object(stream)])
    output = BytesIO(); writer.write(output)
    source = output.getvalue()
    if rotation or crop:
        with fitz.open(stream=source, filetype='pdf') as document:
            if crop:
                document[0].set_cropbox(fitz.Rect(crop))
            document[0].set_rotation(rotation)
            source = document.tobytes(garbage=0, deflate=False)
    return source


def evidence(source, text='Header 2026'):
    with fitz.open(stream=source, filetype='pdf') as document:
        model = extract_page(document, 0, source)
    full = ''.join(g.text for g in model.glyphs)
    begin = full.index(text)
    ids = [g.id for g in model.glyphs[begin:begin + len(text)]]
    _, operations, _, mapping = operator_glyph_map(source, 0, model)
    return analyze(source), model, ids, mapping, operations


@pytest.mark.parametrize('named', [False, True])
def test_artifact_header_edits_preserve_tagged_neighbours_and_control_page(named):
    source = header_pdf(named=named)
    structure, model, ids, mapping, operations = evidence(source)
    assert verified_artifact_selection(structure, 0, ids, mapping, operations)
    payload = selection_payload(source, 0, ids)
    runs = [dict(run, text=run['text'].replace('2026', '2020')) for run in payload['runs']]
    output, report = edit_rich_pdf(source, RichTextRequest(0, ids, runs,
        rect=payload['rect'], revision=payload['revision']))
    assert report['verified']
    assert analyze(output).semantic() == structure.semantic()
    assert audit_tagged(output) == audit_tagged(source)
    with fitz.open(stream=source, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        assert 'Header 2020' in after[0].get_text()
        assert 'Header 2026' not in after[0].get_text()
        assert before[1].get_texttrace() == after[1].get_texttrace()
        assert before[1].get_pixmap(alpha=False).samples == after[1].get_pixmap(alpha=False).samples
        remaining = [g for g in extract_page(after, 0, output).glyphs if g.origin[1] > 70]
    assert [(g.text, g.origin) for g in remaining] == [(g.text, g.origin) for g in model.glyphs if g.origin[1] > 70]


@pytest.mark.parametrize('semantic', ['/ActualText', '/Alt', '/E', '/ReversedChars', '/BBox'])
@pytest.mark.parametrize('named', [False, True])
def test_semantic_or_geometric_artifact_properties_do_not_bypass_tagged_guard(semantic, named):
    source = header_pdf(named=named, semantic=semantic)
    structure, _, ids, mapping, operations = evidence(source)
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations)
    payload = selection_payload(source, 0, ids)
    with pytest.raises(EditError, match='artefacto'):
        edit_rich_pdf(source, RichTextRequest(0, ids,
            [dict(run, text=run['text'].replace('2026', '2020')) for run in payload['runs']],
            rect=payload['rect'], revision=payload['revision']))


def test_artifact_and_mcid_content_cannot_be_edited_as_one_decorative_scope():
    source = header_pdf()
    structure, model, ids, mapping, operations = evidence(source)
    ids += [g.id for g in model.glyphs if abs(g.origin[1] - 100) < .03]
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations)


def test_distinct_artifact_scopes_cannot_be_consolidated():
    source = header_pdf(second=True)
    structure, model, ids, mapping, operations = evidence(source)
    ids += [g.id for g in model.glyphs if abs(g.origin[1] - 80) < .03]
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations)


def test_semantic_wrapper_around_artifact_keeps_the_normal_guard():
    source = header_pdf(wrapper=True)
    structure, _, ids, mapping, operations = evidence(source)
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations)


@pytest.mark.parametrize('named', [False, True])
@pytest.mark.parametrize('rotation,crop', [(0, None), (90, (10, 10, 400, 410))])
def test_artifact_bbox_edit_preserves_exact_box_with_crop_and_display_rotation(named, rotation, crop):
    bbox = (40, 360, 300, 400)
    source = header_pdf(named=named, bbox=bbox, rotation=rotation, crop=crop,
                        include_objr=not rotation)
    structure, model, ids, mapping, operations = evidence(source)
    selected = model.selected(ids)
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations)
    assert verified_artifact_selection(structure, 0, ids, mapping, operations,
                                       model=model, planned=selected)
    payload = selection_payload(source, 0, ids)
    runs = [dict(run, text=run['text'].replace('2026', '2020')) for run in payload['runs']]
    output, report = edit_rich_pdf(source, RichTextRequest(0, ids, runs,
        rect=payload['rect'], revision=payload['revision']))
    assert report['verified']
    assert analyze(output).semantic() == structure.semantic()
    after = PdfReader(BytesIO(output))
    page = after.pages[0]
    if named:
        properties = page['/Resources']['/Properties']['/HeaderArtifact'].get_object()
        assert tuple(properties['/BBox']) == bbox
    else:
        from pypdf.generic import ContentStream
        boxes = [tuple(args[1]['/BBox']) for args, operator in
                 ContentStream(page.get_contents(), after).operations
                 if operator == b'BDC' and args[0] == '/Artifact' and '/BBox' in args[1]]
        assert boxes == [bbox]
    with fitz.open(stream=output, filetype='pdf') as document:
        assert 'Header 2020' in document[0].get_text()
        assert document[0].rotation == rotation


def test_artifact_bbox_rejects_planned_or_original_overflow():
    source = header_pdf(bbox=(40, 360, 300, 400))
    structure, model, ids, mapping, operations = evidence(source)
    selected = model.selected(ids)
    outside = replace(selected[0], bbox=(305, 35, 315, 48))
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations,
                                           model=model, planned=[outside])
    shifted_model = replace(model, glyphs=[outside if g.id == outside.id else g for g in model.glyphs])
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations,
                                           model=shifted_model, planned=selected)


@pytest.mark.parametrize('bbox', [(40, 400, 300, 360), (40, 360, 40, 400),
                                  (float('inf'), 360, 300, 400)])
def test_artifact_bbox_rejects_invalid_geometry(bbox):
    source = header_pdf(bbox=(40, 360, 300, 400))
    structure, model, ids, mapping, operations = evidence(source)
    # Keep the PDF valid while exercising the proof's bounds validation.
    properties = next(args[1] for args, op in structure.operations[0]
                      if op == b'BDC' and args[0] == '/Artifact')
    properties[NameObject('/BBox')] = ArrayObject([FloatObject(value) for value in bbox])
    operations = structure.operations[0]
    assert not verified_artifact_selection(structure, 0, ids, mapping, operations,
                                           model=model, planned=model.selected(ids))
