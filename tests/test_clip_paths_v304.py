"""Canonical clipping paths remain native, with holes and curves protected."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from pdfmodder.clipping import _signature
from pdfmodder.clipped_layout import _state_at
from pdfmodder.engine import extract_page
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload


def polygon(left=20, bottom=35, right=180, top=65, *, reverse=False):
    points = [(left, bottom), (right, bottom), (right, top), (left, top)]
    if reverse:
        points.reverse()
    return [(list(points[0]), b'm'), *[(list(p), b'l') for p in points[1:]], ([], b'h')]


def state(path, *, even_odd=False):
    return _state_at([*path, ([], b'W*' if even_odd else b'W'), ([], b'n')], len(path)+2)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('even_odd', [False, True])
def test_polygon_rectangle_has_same_clip_as_re(reverse, even_odd):
    value = state(polygon(reverse=reverse), even_odd=even_odd)
    assert not value['unknown']
    assert tuple(value['clip']) == (20, 35, 180, 65)


def test_open_and_redundant_vertices_remain_exact_rectangle():
    path = [([20, 35], b'm'), ([90, 35], b'l'), ([180, 35], b'l'),
            ([180, 65], b'l'), ([180, 65], b'l'), ([20, 65], b'l')]
    assert tuple(state(path)['clip']) == (20, 35, 180, 65)


def test_current_path_survives_q_q_and_each_vertex_uses_its_construction_matrix():
    path = [([], b'q'), ([.1, 0, 0, .1, 0, 0], b'cm'),
            ([200, 350], b'm'), ([1800, 350], b'l'),
            ([1800, 650], b'l'), ([200, 650], b'l'), ([], b'h'), ([], b'Q')]
    clip = state(path)
    assert not clip['unknown']
    assert tuple(clip['clip']) == pytest.approx((20, 35, 180, 65), abs=.00001)
    assert tuple(clip['ctm']) == (1, 0, 0, 1, 0, 0)


@pytest.mark.parametrize('even_odd', [False, True])
def test_adjacent_subpaths_only_accepted_with_complete_rectangular_coverage(even_odd):
    value = state(polygon(20, 35, 100, 65)+polygon(100, 35, 180, 65), even_odd=even_odd)
    assert not value['unknown']
    assert tuple(value['clip']) == (20, 35, 180, 65)


def test_same_orientation_nested_rectangles_are_solid_only_for_nonzero_fill():
    path = polygon()+polygon(40, 40, 60, 60)
    assert not state(path)['unknown']
    assert state(path, even_odd=True)['unknown']


def test_opposite_orientation_hole_is_never_replaced_by_bounding_rectangle():
    assert state(polygon()+polygon(40, 40, 60, 60, reverse=True))['unknown']


def test_disjoint_cells_and_nonrectangular_polygon_stay_protected():
    assert state(polygon()+polygon(200, 35, 250, 65))['unknown']
    triangle = [([20, 35], b'm'), ([180, 35], b'l'), ([100, 65], b'l'), ([], b'h')]
    assert state(triangle)['unknown']


def test_curve_and_skewed_rectangle_stay_protected():
    assert state([([20, 35], b'm'), ([20, 65, 100, 65, 100, 35], b'c')])['unknown']
    assert state([([1, .1, 0, 1, 0, 0], b'cm'), ([20, 35, 160, 30], b're')])['unknown']


def test_known_clip_intersections_and_q_restore():
    ops = [*polygon(), ([], b'W'), ([], b'n'), ([], b'q'),
           *polygon(30, 40, 150, 60), ([], b'W*'), ([], b'n')]
    assert tuple(_state_at(ops, len(ops))['clip']) == (30, 40, 150, 60)
    ops.append(([], b'Q'))
    assert tuple(_state_at(ops, len(ops))['clip']) == (20, 35, 180, 65)


def fixture(*, curved=False):
    with fitz.open() as document:
        page = document.new_page(width=260, height=180)
        page.insert_text((30, 130), '<100 /10 ml', fontname='cour', fontsize=10)
        xref = page.get_contents()[-1]
        clip = (b'20 35 m 180 35 l 180 65 l 20 65 l h' if not curved
                else b'20 35 m 20 65 180 65 180 35 c h')
        document.update_stream(xref, b'q '+clip+b' W n\n'+document.xref_stream(xref)+b'\nQ')
        page.insert_text((30, 40), 'CONTROL INTACTO', fontname='cour', fontsize=10)
        document.new_page(width=260, height=180).insert_text((30, 40), 'OTRA PAGINA')
        return document.tobytes()


def draft(data, text):
    with fitz.open(stream=data, filetype='pdf') as document:
        model = extract_page(document, 0, data)
    ids = [g.id for g in model.glyphs if abs(g.origin[1]-130)<.01]
    payload = selection_payload(data, 0, ids)
    return RichTextRequest(0, ids, [dict(payload['runs'][0], text=text)],
                           rect=payload['rect'], paragraphs=payload['paragraphs'],
                           revision=payload['revision'], auto_width=True)


@pytest.mark.parametrize('text', ['<200 /10 ml', '<100 /20 ml', '<100 /10 mL', ''])
def test_native_edit_numeric_units_case_and_deletion_preserves_polygon_clip(text):
    data = fixture()
    output, report = edit_rich_pdf(data, draft(data, text))
    assert report['verified']
    before, after = PdfReader(BytesIO(data)), PdfReader(BytesIO(output))
    path_ops = {b'm', b'l', b'c', b'h', b'W', b'W*', b're'}
    paths = lambda reader: [(op, _signature(args)) for args, op in
                            ContentStream(reader.pages[0].get_contents(), reader).operations if op in path_ops]
    assert paths(before) == paths(after)
    with fitz.open(stream=data, filetype='pdf') as old, fitz.open(stream=output, filetype='pdf') as new:
        assert new[1].get_texttrace() == old[1].get_texttrace()
        assert new[1].get_pixmap().samples == old[1].get_pixmap().samples
        assert new[0].get_pixmap(clip=(0, 0, 250, 65)).samples == old[0].get_pixmap(clip=(0, 0, 250, 65)).samples
        assert new[0].get_text().splitlines() == ([text] if text else [])+['CONTROL INTACTO']


def test_native_curved_clip_edit_still_requires_reproducible_geometry():
    data = fixture(curved=True)
    with pytest.raises(EditError, match='recorte complejo'):
        edit_rich_pdf(data, draft(data, '<200 /10 ml'))


def test_polygon_clip_remains_limit_even_with_overlap_permission():
    data = fixture()
    request = replace(draft(data, '<100 /10 ml '*10), allow_overlap=True)
    with pytest.raises(EditError, match='recorte'):
        edit_rich_pdf(data, request)
