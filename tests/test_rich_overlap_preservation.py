"""Existing nominal font-box overlaps must not prevent native text editing."""
from dataclasses import replace
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError, intersects
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import _new_neighbor_overlap, edit_rich_pdf, selection_payload


def tight_lines():
    with fitz.open() as doc:
        page = doc.new_page(width=240, height=160)
        page.insert_text((50, 60), 'ghjqp', fontsize=12)
        page.insert_text((50, 74), 'ABCDEF', fontsize=12)
        page.insert_text((50, 88), 'UVWXYZ', fontsize=12)
        page.insert_text((20, 74), 'Z', fontsize=12)
        data = doc.tobytes()
        model = extract_page(doc, 0, data)
    selected = [g for g in model.glyphs if abs(g.origin[1]-74) < .01 and g.origin[0] >= 50]
    assert ''.join(g.text for g in selected) == 'ABCDEF'
    others = [g for g in model.glyphs if g not in selected]
    assert any(intersects(g.bbox, n.bbox, .12) for g in selected for n in others)
    payload = selection_payload(data, 0, [g.id for g in selected])
    return data, selected, others, payload


def draft(payload, text):
    return RichTextRequest(0, payload['ids'], [dict(payload['runs'][0], text=text)],
                           rect=payload['rect'], auto_width=True, auto_height=True,
                           revision=payload['revision'])


@pytest.mark.parametrize('replacement', ['ABCDEF', 'FEDCBA'])
def test_tight_leading_native_edit_preserves_neighbors(replacement):
    data, selected, neighbors, payload = tight_lines()
    output, report = edit_rich_pdf(data, draft(payload, replacement))
    assert report['verified'] and report['pages'][0]['pixels_above_8'] == 0
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        actual = extract_page(after, 0, output)
        assert ''.join(g.text for g in actual.glyphs
                       if abs(g.origin[1]-74) < .01 and g.origin[0] >= 50) == replacement
        untouched = [g for g in actual.glyphs
                     if abs(g.origin[1]-74) >= .01 or g.origin[0] < 50]
        assert [(g.text, g.origin, g.bbox) for g in untouched] == [
            (g.text, g.origin, g.bbox) for g in neighbors]
        # These regions contain each neighboring line's actual ink, including
        # descenders; the selected line paints entirely between them.
        for clip in ((40, 43, 145, 64), (40, 78, 145, 101), (15, 60, 32, 80)):
            assert before[0].get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip).samples == \
                after[0].get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip).samples


def test_moving_into_a_new_neighbor_is_rejected():
    data, _, _, payload = tight_lines()
    req = draft(payload, 'FEDCBA')
    rect = req.rect
    req = replace(req, rect=(20, rect[1], rect[2]-30, rect[3]))
    with pytest.raises(EditError, match='solapa con caracteres vecinos'):
        edit_rich_pdf(data, req)


def test_font_growth_beyond_existing_intersection_is_rejected():
    data, _, _, payload = tight_lines()
    req = draft(payload, 'ABCDEF')
    req = replace(req, runs=[dict(req.runs[0], size=18)])
    with pytest.raises(EditError, match='solapa con caracteres vecinos'):
        edit_rich_pdf(data, req)


def test_discontinuous_source_union_does_not_authorize_its_gap():
    glyph = lambda box: SimpleNamespace(bbox=box)
    neighbor = glyph((0, 0, 50, 10))
    selected = [glyph((5, 0, 10, 10)), glyph((40, 0, 45, 10))]
    assert not _new_neighbor_overlap(glyph((5, 0, 10, 10)), neighbor, selected)
    assert not _new_neighbor_overlap(glyph((40, 0, 45, 10)), neighbor, selected)
    assert _new_neighbor_overlap(glyph((5, 0, 45, 10)), neighbor, selected)
    assert _new_neighbor_overlap(glyph((20, 0, 25, 10)), neighbor, selected)
