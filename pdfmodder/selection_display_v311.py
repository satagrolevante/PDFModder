"""Compact visual selection runs; the selected character IDs stay unchanged."""
from .model import union


def selection_rectangles_v311(glyphs):
    groups = {}
    for glyph in glyphs:
        if abs(glyph.direction[0]) < .8:
            yield glyph.bbox
            continue
        groups.setdefault((glyph.block, glyph.line, glyph.direction, glyph.mode), []).append(glyph)
    for members in groups.values():
        members.sort(key=lambda glyph: glyph.bbox[0])
        rect = None
        for glyph in members:
            box = glyph.bbox
            if (rect is not None and box[0] <= rect[2] + 1.5
                    and abs(box[1]-rect[1]) < 1. and abs(box[3]-rect[3]) < 1.):
                rect = union((rect, box))
            else:
                if rect is not None:
                    yield rect
                rect = box
        if rect is not None:
            yield rect
