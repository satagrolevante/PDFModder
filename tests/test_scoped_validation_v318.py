"""Scoped proofs skip only exact inputs and leave independent guards active."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject)

from pdfmodder.model import EditError
from pdfmodder.page_content_proof_v318 import MappedPageContentProofV318
from pdfmodder.pageops import extract_pages_pdf, organize_pages_pdf
from pdfmodder.page_tools_v150 import crop_pages_pdf
from test_pageops import fixture_pdf


def rewrite(source, change):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    change(writer)
    result = BytesIO(); writer.write(result)
    return result.getvalue()


def annotation_precision_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    appearance = DecodedStreamObject()
    appearance.set_data(b'0 0 100000000 100 re f')
    appearance.update({NameObject('/Type'): NameObject('/XObject'),
        NameObject('/Subtype'): NameObject('/Form'),
        NameObject('/BBox'): ArrayObject([NumberObject(n) for n in (0, 0, 100000000, 100)]),
        NameObject('/Matrix'): ArrayObject([FloatObject(n) for n in (1, .000001, 0, 1, 0, 0)]),
        NameObject('/Resources'): DictionaryObject()})
    annotation = DictionaryObject({NameObject('/Type'): NameObject('/Annot'),
        NameObject('/Subtype'): NameObject('/Stamp'), NameObject('/F'): NumberObject(4),
        NameObject('/Rect'): ArrayObject([NumberObject(n) for n in (50, 50, 250, 250)]),
        NameObject('/AP'): DictionaryObject({NameObject('/N'): writer._add_object(appearance)})})
    page[NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
    output = BytesIO(); writer.write(output)
    return output.getvalue()


def change_annotation_precision(writer):
    appearance = writer.pages[0]['/Annots'][0].get_object()['/AP']['/N']
    appearance['/Matrix'][1] = FloatObject(.000004)


@pytest.mark.parametrize('operation', ['extract', 'organize', 'crop'])
def test_subprecision_annotation_matrix_change_cannot_use_page_identity(operation, monkeypatch):
    from pdfmodder import pageops, page_tools_v150
    source = annotation_precision_pdf()
    changed = rewrite(source, change_annotation_precision)
    before, after = (PdfReader(BytesIO(value), strict=True) for value in (source, changed))
    # Legacy tolerance alone cannot prove appearance identity: the small
    # shear is amplified by this valid appearance's large coordinate system.
    assert pageops._annotation_details(before, 0) == pageops._annotation_details(after, 0)
    assert pageops._annotation_details(before, 0, exact_numbers=True) != pageops._annotation_details(after, 0, exact_numbers=True)
    assert MappedPageContentProofV318(source, changed).unchanged(0, 0)
    with fitz.open(stream=source, filetype='pdf') as first, fitz.open(stream=changed, filetype='pdf') as second:
        assert first[0].get_pixmap().samples != second[0].get_pixmap().samples
    owner, name = ((page_tools_v150, '_write_crop_boxes') if operation == 'crop'
                   else (pageops, '_build_organized' if operation == 'organize' else '_build_pdf'))
    real = getattr(owner, name)
    def tampered(*args, **kwargs):
        return rewrite(real(*args, **kwargs), change_annotation_precision)
    monkeypatch.setattr(owner, name, tampered)
    with pytest.raises(EditError):
        if operation == 'crop':
            crop_pages_pdf(source, [0], (1, 1, 1, 1))
        elif operation == 'organize':
            organize_pages_pdf(source, [{'source': 'current', 'page': 0, 'rotation': 90}])
        else:
            extract_pages_pdf(source, [0])


def test_page_reordering_and_rotation_reuse_exact_paint_inputs():
    source = fixture_pdf(links=False)
    output, report = organize_pages_pdf(source, [
        {'source': 'current', 'page': 2, 'rotation': 90},
        {'source': 'current', 'page': 0, 'rotation': 0}])
    assert all(page['verification'] == 'identical_content_resources_sha256'
               and page['rasterized'] is False for page in report['pages'])
    proof = MappedPageContentProofV318(source, output)
    assert proof.unchanged(2, 0) and proof.unchanged(0, 1)
    assert not proof.unchanged(0, 0)


def test_crop_retains_independent_geometry_and_annotation_validation(monkeypatch):
    from pdfmodder import page_tools_v150
    source = fixture_pdf(links=False)
    output, report = crop_pages_pdf(source, [0], (5, 6, 7, 8))
    assert all(page['verification'] == 'identical_content_resources_sha256'
               for page in report['pages'])
    real_write = page_tools_v150._write_crop_boxes

    def tampered(reader, boxes):
        candidate = real_write(reader, boxes)
        return rewrite(candidate, lambda writer: writer.pages[0]['/Annots'][0].get_object().__setitem__(
            NameObject('/F'), NumberObject(0)))

    monkeypatch.setattr(page_tools_v150, '_write_crop_boxes', tampered)
    with pytest.raises(EditError, match='anotaciones'):
        crop_pages_pdf(source, [0], (5, 6, 7, 8))


def test_modified_resources_or_operators_never_inherit_proof():
    source = fixture_pdf(links=False)
    with fitz.open(stream=source, filetype='pdf') as document:
        document[0].insert_text((40, 350), 'Unexpected new content')
        changed = document.tobytes()
    proof = MappedPageContentProofV318(source, changed)
    assert not proof.unchanged(0, 0) and proof.unchanged(1, 1)
    changed_resource = rewrite(source, lambda writer: writer.pages[0]['/Resources']['/Font']['/helv'].get_object().__setitem__(
        NameObject('/BaseFont'), NameObject('/Courier')))
    assert not MappedPageContentProofV318(source, changed_resource).unchanged(0, 0)
    assert not MappedPageContentProofV318(source, source, max_nodes=1).unchanged(0, 0)


def test_unknown_inherited_state_falls_back_to_complete_validation():
    source = fixture_pdf(links=False)
    changed = rewrite(source, lambda writer: writer.pages[0]['/Parent'].__setitem__(
        NameObject('/UnknownInheritedState'), NumberObject(1)))
    assert not MappedPageContentProofV318(changed, changed).unchanged(0, 0)


def test_complete_page_operation_registers_exact_snapshot_only_in_session_scope():
    from pdfmodder.validation_evidence_v318 import (
        ValidationEvidenceCacheV318, has_validated_snapshot_v318,
        validated_snapshot_v318, validation_scope_v318,
    )
    source = fixture_pdf(links=False)
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        assert validated_snapshot_v318(source) is None
        output, report = extract_pages_pdf(source, [0])
        proof = validated_snapshot_v318(output)
        assert report['verified'] and has_validated_snapshot_v318(output, proof)
        assert not has_validated_snapshot_v318(source, proof)


def test_unchanged_malformed_text_scopes_cannot_receive_complete_snapshot_proof():
    from pdfmodder.validation_evidence_v318 import (
        ValidationEvidenceCacheV318, validated_snapshot_v318, validation_scope_v318,
    )
    source = fixture_pdf(links=False)
    with fitz.open(stream=source, filetype='pdf') as document:
        stream = document[0].get_contents()[0]
        document.update_stream(stream, document.xref_stream(stream) + b'\nET\n')
        malformed = document.tobytes(garbage=0)
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        with pytest.raises(EditError, match='ET sin apertura'):
            extract_pages_pdf(malformed, [0])
        assert validated_snapshot_v318(malformed) is None
