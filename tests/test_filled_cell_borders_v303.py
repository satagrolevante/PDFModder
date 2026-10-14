"""Cell suggestions use actual opaque filled bars without inventing boxes."""
from copy import deepcopy

import pymupdf as fitz
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.selection_v300 import boundaries_from_drawings, selection_index


def filled_bar(path_rect, **metadata):
    return {'type': 'f', 'fill': (0., 0., 0.), 'fill_opacity': 1.,
            'items': [('re', path_rect, 1)], **metadata}


@pytest.mark.parametrize(('rect', 'edge'), [
    ((10., 20., 90., 20.48), (10., 20.24, 90., 20.24)),
    ((10., 20., 10.72, 90.), (10.36, 20., 10.36, 90.)),
])
def test_opaque_filled_bar_has_one_centerline_from_its_path(rect, edge):
    drawing = filled_bar(rect, rect=(-1000., -1000., 1000., 1000.))
    original = deepcopy(drawing)
    edges = boundaries_from_drawings([drawing])
    assert len(edges) == 1
    assert edges[0] == pytest.approx(edge)
    assert drawing == original


@pytest.mark.parametrize('rect', [
    (0., 0., 100., 60.),       # A broad background.
    (0., 0., 100., 2.),        # A long but thick highlight.
    (0., 0., 10., 1.5),        # Insufficient aspect ratio.
    (0., 0., 4., .1),          # A short decorative mark.
    (0., 0., 100., 0.),        # Degenerate or reversed geometry.
    (100., 0., 0., .5),
    (0., 0., float('nan'), .5),
    (0., 0., 100., float('inf')),
])
def test_backgrounds_and_invalid_or_decorative_rectangles_are_not_borders(rect):
    assert boundaries_from_drawings([filled_bar(rect)]) == []


@pytest.mark.parametrize('metadata', [
    {'fill_opacity': 0.},
    {'fill_opacity': .5},
    {'fill_opacity': .999},
    {'fill_opacity': None},
    {'fill': None},
])
def test_only_explicit_opaque_fill_is_inferred(metadata):
    assert boundaries_from_drawings([filled_bar((0., 0., 100., .5), **metadata)]) == []


def test_compound_paths_and_nonrectangular_fill_bounding_boxes_are_not_borders():
    rect = (0., 0., 100., .5)
    quad = fitz.Quad((0., 0.), (100., 1.), (0., .5), (100., 1.5))
    drawings = [
        filled_bar(rect, items=[('re', rect, 1), ('re', (1., .1, 99., .4), -1)],
                   even_odd=True),
        filled_bar(rect, items=[('qu', quad)], rect=rect),
        filled_bar(rect, items=[('l', (0., 0.), (100., .5))], rect=rect),
    ]
    assert boundaries_from_drawings(drawings) == []


def test_stroked_path_behavior_is_preserved_including_filled_strokes():
    rect = (10., 20., 90., 60.)
    expected = [(10., 20., 90., 20.), (90., 20., 90., 60.),
                (90., 60., 10., 60.), (10., 60., 10., 20.)]
    for kind in ('s', 'fs'):
        drawing = {'type': kind, 'items': [('re', rect, 1)]}
        assert boundaries_from_drawings([drawing]) == expected
        drawing['stroke_opacity'] = 0.
        assert boundaries_from_drawings([drawing]) == []


def cell_pdf(*, omit_bottom=False):
    """Public fixture: two neighboring cells with .72 pt filled border bars."""
    with fitz.open() as doc:
        page = doc.new_page(width=300., height=180.)
        # Broad paint must not contribute a box around the page or the cells.
        page.draw_rect((0., 0., 300., 180.), color=None, fill=(.95, .95, .95))
        for rect in [(30.36, 30., 99.64, 30.72), (30.36, 89.28, 99.64, 90.),
                     (29.64, 30.72, 30.36, 89.28),
                     (100.36, 30., 169.64, 30.72), (100.36, 89.28, 169.64, 90.),
                     (169.64, 30.72, 170.36, 89.28)]:
            if omit_bottom and rect[1] > 80.:
                continue
            page.draw_rect(rect, color=None, fill=(0., 0., 0.))
        page.draw_rect((99.64, 30.72, 100.36, 89.28), color=None, fill=(0., 0., 0.))
        page.insert_text((40., 52.), 'ONE', fontsize=10.)
        page.insert_text((40., 68.), 'TWO', fontsize=10.)
        page.insert_text((110., 52.), 'NEXT', fontsize=10.)
        return doc.tobytes()


def test_real_get_drawings_filled_bars_infer_cells_and_exclude_neighbor():
    data = cell_pdf()
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
        index = selection_index(model)
        first = model.glyphs[0]
        scope = index.scope(first, 'cell')
        assert scope.rect == pytest.approx((30., 30.36, 100., 89.64), abs=.001)
        assert ''.join(g.text for g in model.selected(scope.ids)) == 'ONETWO'
        neighbor = next(g for g in model.glyphs if g.origin[0] > 100.)
        assert index.cell_rect(neighbor) == pytest.approx((100., 30.36, 170., 89.64), abs=.001)
        assert len(model.selection_boundaries) == 7


def test_incomplete_filled_bars_do_not_invent_a_large_cell_from_background():
    data = cell_pdf(omit_bottom=True)
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
        index = selection_index(model)
        assert index.cell_rect(model.glyphs[0]) is None
        neighbor = next(g for g in model.glyphs if g.origin[0] > 100.)
        assert index.cell_rect(neighbor) is None
