"""Deleting reusable handwriting removes only its own accessible Figure."""
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NullObject
import pytest

from pdfmodder.media import add_image_pdf, delete_image_pdf, edit_image_pdf, image_items
from pdfmodder.model import EditError
from pdfmodder.tagged import analyze
from tagged_corpus import audit_tagged, make_tagged_pdf
from test_tagged import assert_control_page_unchanged


def ink():
    image = Image.new('RGBA', (180, 60), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(5, 45), (40, 10), (65, 50), (110, 15), (175, 30)],
                               fill=(0, 0, 0, 255), width=3)
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def last_image(data, page=0):
    with fitz.open(stream=data) as document:
        return image_items(document, page)[-1]


@pytest.mark.parametrize('decorative', [False, True])
@pytest.mark.parametrize('rotated', [False, True])
def test_delete_added_signature_preserves_existing_reading_order_images_and_objr(decorative, rotated):
    source = make_tagged_pdf(named_properties=True, include_objr=True)
    before = audit_tagged(source)
    added, _ = add_image_pdf(source, 0, ink(), (160, 260, 300, 310),
                             accessibility_order=None if decorative else 'page_end',
                             alt_text=None if decorative else 'Firma manuscrita: Prueba',
                             decorative=decorative)
    item = last_image(added)
    assert item['editable']
    if rotated:
        added, _ = edit_image_pdf(added, 0, item['id'], rotation=23., fit_mode='fit')
        item = last_image(added)
    after, report = delete_image_pdf(added, 0, item['id'])
    audit = audit_tagged(after)
    assert report['verified'] and report['accessibility']['verified']
    assert report['accessibility']['removed_figure'] is not decorative
    assert audit['reading_order'] == before['reading_order']
    assert audit['content'] == before['content']
    assert audit['objrs'] == before['objrs']
    assert all('Firma manuscrita' not in str(node) for node in analyze(after).nodes.values())
    assert_control_page_unchanged(source, after)
    with fitz.open(stream=source) as original, fitz.open(stream=after) as result:
        old = np.frombuffer(original[0].get_pixmap().samples, np.uint8).astype(int)
        new = np.frombuffer(result[0].get_pixmap().samples, np.uint8).astype(int)
        # MuPDF's graphics-state isolation may round existing image colors by
        # one 8-bit level; no visible source content may remain changed.
        assert np.abs(old-new).max() <= 1
        assert len(original[0].get_image_info()) == len(result[0].get_image_info())


def test_delete_one_of_two_figures_keeps_other_mcid_and_alternative_description():
    source = make_tagged_pdf(include_objr=True)
    first, _ = add_image_pdf(source, 0, ink(), (160, 260, 300, 310),
                             accessibility_order='page_end', alt_text='Firma manuscrita: Primera')
    selected = last_image(first)['id']
    second, _ = add_image_pdf(first, 0, ink(), (160, 320, 300, 370),
                              accessibility_order='page_end', alt_text='Firma manuscrita: Segunda')
    existing = analyze(second)
    removed_mcid = max(analyze(first).marks[0])
    survivor_mcid = max(existing.marks[0])
    output, _ = delete_image_pdf(second, 0, selected)
    current = analyze(output)
    assert removed_mcid not in current.marks[0] and survivor_mcid in current.marks[0]
    assert set(current.marks[0]) == set(existing.marks[0]) - {removed_mcid}
    assert 'Primera' not in audit_tagged(output)['reading_order']
    assert 'Segunda' in audit_tagged(output)['reading_order']


def test_accessible_reference_to_deleted_figure_rejects_instead_of_dangling():
    source, _ = add_image_pdf(make_tagged_pdf(), 0, ink(), (160, 260, 300, 310),
                              accessibility_order='page_end', alt_text='Firma manuscrita: Referenciada')
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    tree = writer._root_object['/StructTreeRoot']
    parent = tree['/K'].get_object()
    figure = parent['/K'][-2]
    assert figure.get_object()['/S'] == '/Figure'
    parent[NameObject('/Ref')] = ArrayObject([figure])
    stream = BytesIO()
    writer.write(stream)
    data = stream.getvalue()
    with pytest.raises(EditError, match='relación accesible'):
        delete_image_pdf(data, 0, last_image(data)['id'])


def test_deleting_only_figure_on_a_page_removes_unused_parent_key():
    # Keep only the figure on page 0 and the full control page. Historical
    # ParentTree holes must not make a now-empty page association survive.
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    tree = writer._root_object['/StructTreeRoot']
    document = tree['/K'].get_object()
    children = document['/K']
    document[NameObject('/K')] = ArrayObject([children[2], children[3]])
    writer.pages[0][NameObject('/Contents')] = ArrayObject([writer.pages[0]['/Contents'][2]])
    owners = tree['/ParentTree']['/Nums'][1].get_object()
    owners[0] = NullObject()
    owners[1] = NullObject()
    buffer = BytesIO()
    writer.write(buffer)
    source = buffer.getvalue()
    existing = analyze(source)
    key = existing.reader.pages[0]['/StructParents']
    output, _ = delete_image_pdf(source, 0, last_image(source)['id'])
    result = analyze(output)
    assert result.marks[0] == {}
    assert set(result.parents) == set(existing.parents) - {key}
    assert result.reader.pages[0].get('/StructParents') is None
    assert_control_page_unchanged(source, output)
