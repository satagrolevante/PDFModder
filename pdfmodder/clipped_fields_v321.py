"""Own hidden text only when every visible glyph of its clipping scope is selected.

Equal rectangle coordinates are not an identity: separately painted cells can
share them. Scope keys use the actual W/W* operators and follow q/Q restoration.
No clip is enlarged or removed by this module.
"""
from dataclasses import replace
import pymupdf as fitz

from .clipped_layout import _state_at
from .draft_control_v305 import checkpoint


def _clip_scopes(operations):
    active, stack, pending, scopes = (), [], None, {}
    for index, (_, op) in enumerate(operations):
        if op == b'q':
            stack.append(active)
        elif op == b'Q':
            active = stack.pop() if stack else ()
        elif op in (b'W', b'W*'):
            pending = index
        elif op in (b'n', b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*'):
            if pending is not None:
                active += (pending,)
            pending = None
        elif op in (b'Tj', b'TJ', b"'", b'"'):
            scopes[index] = active
    return scopes


def hidden_field_glyphs(operations, shows, selected, resources, page_matrix, page_bounds):
    """Return provably outside-box source glyphs from complete selected fields.

    Unknown clips, nonvisible text modes, transforms and uncertain code maps
    never acquire implicit ownership. Partial words keep all other source codes.
    Final text, cursor and pixel validation remain the caller's responsibility.
    """
    chosen = {g.id for g in selected}
    scopes = _clip_scopes(operations)
    targets = {scopes.get(s['operation'], ()) for s in shows
               if any(g.id in chosen for g in s['glyphs'])} - {()}
    groups = {}
    for show in shows:
        scope = scopes.get(show['operation'], ())
        if scope in targets:
            groups.setdefault(scope, []).append(show)
    result = []
    for group in groups.values():
        visible, hidden, supported = set(), [], True
        for show in group:
            checkpoint()
            state = _state_at(operations, show['operation'], resources)
            matrix = state['matrix']
            if (state['unknown'] or state['clip'] is None or show['render_mode'] != 0
                    or operations[show['operation']][1] not in (b'Tj', b'TJ')
                    or abs(matrix.b)+abs(matrix.c) > 1e-6 or matrix.a <= 0 or matrix.d <= 0
                    or any(g.mode != 0 or g.layer or abs(g.direction[0]-1)+abs(g.direction[1]) > 1e-6
                           for g in show['glyphs'])):
                supported = False
                break
            clip = (state['clip'] * page_matrix) & page_bounds
            if clip.is_empty:
                supported = False
                break
            # Margin is conservative: borderline glyphs count as visible and
            # must be explicitly selected, never silently removed.
            padded = clip + (-.035, -.035, .035, .035)
            # Fully cropped glyphs are absent from rawdict, hence normally
            # unreliable for reconstruction. Removing mapped codes requires
            # no reconstruction: prove their exact code/trace correspondence.
            from .typography_v300 import _code_groups
            from .model import EditError
            try:
                _, code_groups = _code_groups(show, operations)
            except EditError:
                supported = False
                break
            if any(len(members) != 1 for _, members in code_groups):
                supported = False
                break
            for glyph in show['glyphs']:
                boundary_space = glyph.text.isspace() and (
                    glyph.bbox[2] <= clip.x0+.035 or glyph.bbox[0] >= clip.x1-.035)
                if boundary_space or (fitz.Rect(glyph.bbox) & padded).is_empty:
                    hidden.append(replace(glyph, reliable=True))
                else:
                    visible.add(glyph.id)
                    supported = supported and glyph.reliable
        if supported and visible and visible <= chosen:
            result.extend(g for g in hidden if g.id not in chosen)
    return result
