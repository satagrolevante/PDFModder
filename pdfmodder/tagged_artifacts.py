"""Prove one decorative text scope before preserving its native operators."""
import math

import pymupdf as fitz
from pypdf.generic import NameObject

from .tagged import SHOW, obj


_ARTIFACT_PROPERTIES = {'/Type', '/Subtype', '/Attached', '/BBox'}


def _bbox_contains(structure, page, ids, value, model, planned):
    if model is None or planned is None or model.number != page:
        return False
    value = obj(value)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    numbers = [obj(number) for number in value]
    if any(isinstance(number, bool) or not isinstance(number, (int, float))
           or not math.isfinite(number) for number in numbers):
        return False
    box = fitz.Rect(numbers)
    if box.is_empty or not box.is_valid:
        return False
    selected = model.selected(ids)
    if len(selected) != len(ids):
        return False
    # Artifact BBox is in default PDF user space. Glyphs and planned native
    # text use unrotated, crop-relative MuPDF coordinates. Ignore the display
    # rotation and include the actual crop translation in this conversion.
    with fitz.open(stream=structure.data, filetype='pdf') as document:
        original = document[page]
        original.set_rotation(0)
        box = box * original.transformation_matrix
    box = box + (-.035, -.035, .035, .035)
    for glyph in [*selected, *planned]:
        bounds = fitz.Rect(glyph.bbox)
        if (bounds.is_empty or not bounds.is_valid or not all(math.isfinite(v) for v in bounds)
                or not box.contains(bounds)):
            return False
    return True


def verified_artifact_selection(structure, page, ids, mapping, operations, *, model=None, planned=None):
    """Accept only text inside one simple, explicit, unchanged Artifact scope.

    Named properties are resolved from the verified page's original resources.
    Reading-order content, mixed scopes, semantic wrappers and properties that
    require an update remain on the normal tagged editing path. This proof
    never replaces final character, appearance or structural validation.
    """
    if structure is None or not ids:
        return False
    try:
        if len(ids) != len(set(ids)):
            return False
        original = structure.operations[page]
        if len(operations) != len(original):
            return False
        selected = {mapping[glyph]['operation'] for glyph in ids}
        if any(isinstance(index, bool) or not isinstance(index, int)
               or not 0 <= index < len(original)
               or original[index][1] not in SHOW
               or structure.contexts[page][index] is not None for index in selected):
            return False
        resources = obj(structure.reader.pages[page].get('/Resources', {}))
        properties = obj(resources.get('/Properties', {}))
        stack = []
        scopes = set()
        last_selected = max(selected)
        for index, (args, operator) in enumerate(original):
            supplied_args, supplied_operator = operations[index]
            if operator != supplied_operator:
                return False
            if operator in (b'BMC', b'BDC'):
                if args != supplied_args:
                    return False
                valid = bool(args and args[0] == '/Artifact')
                if operator == b'BMC':
                    valid = valid and len(args) == 1
                else:
                    valid = valid and len(args) == 2
                    prop = args[1] if len(args) == 2 else None
                    if isinstance(prop, NameObject):
                        prop = properties.get(prop)
                    prop = obj(prop)
                    # Unknown attributes include ActualText, Alt, E, MCID and
                    # ReversedChars: do not guess their new meaning. BBox is
                    # retained exactly and requires explicit geometric proof.
                    valid = valid and isinstance(prop, dict) and not (set(prop) - _ARTIFACT_PROPERTIES)
                    if valid and '/BBox' in prop:
                        valid = _bbox_contains(structure, page, ids, prop['/BBox'], model, planned)
                stack.append((index, valid))
            elif operator == b'EMC':
                if not stack:
                    return False
                stack.pop()
            if index in selected:
                if len(stack) != 1 or not stack[0][1]:
                    return False
                scopes.add(stack[0][0])
                if len(scopes) != 1:
                    return False
            if index == last_selected:
                return bool(scopes)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False
    return False
