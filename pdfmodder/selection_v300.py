"""Geometric text scopes and explicit draft area decisions, independent of Qt.

PDF extraction groups describe painting, not necessarily words, columns or
cells. Scopes combine their identity with direction, spacing and painted edges;
they remain a user-correctable suggestion, never an edit of the PDF.
"""
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from math import hypot, isfinite
from statistics import median

from .model import EditError, union


def boundaries_from_drawings(drawings):
    """Return only painted straight edges; filled backgrounds are not borders."""
    edges = []
    for drawing in drawings:
        if drawing.get('type') not in ('s', 'fs') or drawing.get('stroke_opacity', 1.) <= 0:
            continue
        for item in drawing.get('items', []):
            if item[0] == 'l':
                a, b = item[1:3]
                edges.append((float(a[0]), float(a[1]), float(b[0]), float(b[1])))
            elif item[0] == 're':
                x0, y0, x1, y1 = map(float, item[1])
                edges.extend(((x0,y0,x1,y0), (x1,y0,x1,y1), (x1,y1,x0,y1), (x0,y1,x0,y0)))
            elif item[0] == 'qu':
                quad = item[1]
                points = [quad.ul, quad.ur, quad.lr, quad.ll]
                for a, b in zip(points, points[1:]+points[:1]):
                    edges.append((float(a[0]),float(a[1]),float(b[0]),float(b[1])))
    return edges


def _direction(glyph):
    x, y = glyph.direction
    length = hypot(x, y) or 1.
    return x/length, y/length


def _project(rect, direction):
    dx, dy = direction
    points = [(x*dx+y*dy, -x*dy+y*dx) for x,y in
              ((rect[0],rect[1]),(rect[2],rect[1]),(rect[2],rect[3]),(rect[0],rect[3]))]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def _family(glyph):
    return glyph.mode, glyph.opacity > 0, glyph.layer, tuple(round(v, 3) for v in _direction(glyph))


@dataclass(frozen=True)
class SelectionScope:
    ids: tuple[int, ...]
    mode: str
    rect: tuple
    inferred: bool = True
    description: str = ''


class SelectionIndex:
    def __init__(self, model):
        self.model = model
        self.edges = list(getattr(model, 'selection_boundaries', []) or [])
        self.horizontal = sorted((y0,min(x0,x1),max(x0,x1)) for x0,y0,x1,y1 in self.edges if abs(y1-y0)<.5 and abs(x1-x0)>.5)
        self.vertical = sorted((x0,min(y0,y1),max(y0,y1)) for x0,y0,x1,y1 in self.edges if abs(x1-x0)<.5 and abs(y1-y0)>.5)
        self.horizontal_positions = [edge[0] for edge in self.horizontal]
        self.vertical_positions = [edge[0] for edge in self.vertical]
        self._cells = {}
        groups = {}
        for glyph in model.glyphs:
            # The engine can prove paint continuity across extraction blocks
            # while preserving their original block identities. Its line IDs
            # are page-wide; barriers and gaps split columns independently.
            groups.setdefault((glyph.line, _family(glyph)), []).append(glyph)
        self.lines = []
        self.by_id = {}
        self.native_by_id = {}
        for group in groups.values():
            direction = _direction(group[0])
            group.sort(key=lambda g: (_project(g.bbox, direction)[0], g.id))
            for glyph in group:
                self.native_by_id[glyph.id] = group
            threshold = max(8., 1.65*median(g.size for g in group))
            part = []
            for glyph in group:
                if part:
                    before = _project(part[-1].bbox, direction)
                    after = _project(glyph.bbox, direction)
                    # Large gaps represent columns even if the PDF stores them
                    # as one extraction line; small mixed-font runs stay joined.
                    if after[0]-before[2] > threshold or self._separates(part[-1].bbox, glyph.bbox):
                        self._append(part)
                        part = []
                part.append(glyph)
            if part:
                self._append(part)
        self.lines.sort(key=lambda row: (union(g.bbox for g in row)[1], union(g.bbox for g in row)[0], row[0].id))

    def _append(self, line):
        self.lines.append(line)
        for glyph in line:
            self.by_id[glyph.id] = line

    def _separates(self, a, b):
        """An edge crossing the open corridor blocks a suggested grouping."""
        ax, ay = (a[0]+a[2])/2, (a[1]+a[3])/2
        bx, by = (b[0]+b[2])/2, (b[1]+b[3])/2
        first = bisect_right(self.vertical_positions,min(ax,bx)+.25)
        last = bisect_left(self.vertical_positions,max(ax,bx)-.25)
        for x0,y0,y1 in self.vertical[first:last]:
            if bx!=ax:
                t = (x0-ax)/(bx-ax)
                y = ay+t*(by-ay)
                if min(y0,y1)-.5 <= y <= max(y0,y1)+.5:
                    return True
        first = bisect_right(self.horizontal_positions,min(ay,by)+.25)
        last = bisect_left(self.horizontal_positions,max(ay,by)-.25)
        for y0,x0,x1 in self.horizontal[first:last]:
            if by!=ay:
                t = (y0-ay)/(by-ay)
                x = ax+t*(bx-ax)
                if min(x0,x1)-.5 <= x <= max(x0,x1)+.5:
                    return True
        return False

    def _paragraph(self, glyph):
        initial = self.by_id.get(glyph.id, [glyph])
        direction = _direction(glyph)
        base = _project(union(g.bbox for g in initial), direction)
        base_size = median(g.size for g in initial)
        candidates = []
        cell = self.cell_rect(glyph)
        for line in self.lines:
            if _family(line[0]) != _family(glyph):
                continue
            rect = union(g.bbox for g in line)
            if cell and not contains(cell, rect, .5):
                continue
            projected = _project(rect, direction)
            overlap = min(base[2],projected[2])-max(base[0],projected[0])
            aligned = min(abs(base[0]-projected[0]),abs(base[2]-projected[2])) <= max(2., base_size*.8)
            size = median(g.size for g in line)
            if overlap <= 0 or not aligned or not .67 <= size/max(base_size,.1) <= 1.5:
                continue
            candidates.append((projected, line))
        candidates.sort(key=lambda row: (row[0][1],row[0][0]))
        first = next((i for i,row in enumerate(candidates) if row[1] is initial), None)
        if first is None:
            return initial

        def connected(a, b):
            pa, la = a; pb, lb = b
            size = max(median(g.size for g in la),median(g.size for g in lb))
            # Same-baseline candidates are separate columns/overprinted runs.
            if pb[1]-pa[1] < max(1., size*.3) or pb[1]-pa[1] > size*2.1:
                return False
            return not self._separates(union(g.bbox for g in la),union(g.bbox for g in lb))

        left = right = first
        while left and connected(candidates[left-1], candidates[left]):
            left -= 1
        while right+1 < len(candidates) and connected(candidates[right], candidates[right+1]):
            right += 1
        return [g for _,line in candidates[left:right+1] for g in line]

    def group(self, glyph, mode):
        if mode == 'character':
            return [glyph.id]
        if mode == 'block':
            return [g.id for g in self.model.glyphs if g.block == glyph.block
                    and g.mode == glyph.mode and (g.opacity > 0) == (glyph.opacity > 0)]
        line = self.by_id.get(glyph.id, [glyph])
        if mode == 'line':
            return [g.id for g in line]
        if mode == 'paragraph':
            return [g.id for g in self._paragraph(glyph)]
        if mode == 'cell':
            rect = self.cell_rect(glyph)
            if rect:
                return [g.id for row in self.lines for g in row if g.mode != 3 and g.opacity > 0 and contains(rect,g.bbox,.5)]
            return [g.id for g in self._paragraph(glyph)]
        if glyph.text.isspace():
            return [glyph.id]
        index = next(i for i,g in enumerate(line) if g.id == glyph.id)
        left = right = index
        direction = _direction(glyph)
        def adjacent(a, b):
            gap = _project(b.bbox,direction)[0]-_project(a.bbox,direction)[2]
            return not a.text.isspace() and not b.text.isspace() and gap <= max(a.size,b.size)*.65
        while left and adjacent(line[left-1],line[left]):
            left -= 1
        while right+1 < len(line) and adjacent(line[right],line[right+1]):
            right += 1
        return [g.id for g in line[left:right+1]]

    def range(self, anchor, target, mode='character'):
        """Ranges cannot cross a column gap or a painted cell separator."""
        line = self.by_id.get(anchor.id)
        if line is None or self.by_id.get(target.id) is not line:
            return []
        ids = [g.id for g in line]
        endpoints = self.group(anchor,mode)+self.group(target,mode)
        positions = [ids.index(i) for i in endpoints if i in ids]
        return ids[min(positions):max(positions)+1] if positions else []

    def scope(self, glyph, mode):
        ids = self.group(glyph,mode)
        rect = self.cell_rect(glyph) if mode == 'cell' else None
        description = 'Celda delimitada por líneas' if rect else 'Alcance sugerido; puedes corregirlo'
        return SelectionScope(tuple(ids),mode,rect or union(g.bbox for g in self.model.selected(ids)),mode != 'block',description)

    def cell_rect(self, glyph):
        """Infer the smallest enclosure from complete axis-aligned painted edges."""
        if glyph.id in self._cells:
            return self._cells[glyph.id]
        bx0,by0,bx1,by1 = glyph.bbox
        cx,cy = (bx0+bx1)/2,(by0+by1)/2
        horizontal = [(a,y,b) for y,a,b in self.horizontal]
        vertical = self.vertical
        left = sorted({x for x,a,b in vertical if x<=bx0+.5 and a-.5<=cy<=b+.5},reverse=True)
        right = sorted({x for x,a,b in vertical if x>=bx1-.5 and a-.5<=cy<=b+.5})
        top = sorted({y for a,y,b in horizontal if y<=by0+.5 and a-.5<=cx<=b+.5},reverse=True)
        bottom = sorted({y for a,y,b in horizontal if y>=by1-.5 and a-.5<=cx<=b+.5})
        choices = []
        # Only the nearest barriers around the glyph are eligible. Enumerating
        # all pairs on large tables would turn a click into quadratic work.
        for x0 in left[:4]:
            for x1 in right[:4]:
                for y0 in top[:4]:
                    for y1 in bottom[:4]:
                        if x1<=x0 or y1<=y0:
                            continue
                        if (edge_covers(horizontal,y0,x0,x1) and edge_covers(horizontal,y1,x0,x1)
                                and edge_covers([(a,x,b) for x,a,b in vertical],x0,y0,y1)
                                and edge_covers([(a,x,b) for x,a,b in vertical],x1,y0,y1)):
                            choices.append(((x1-x0)*(y1-y0),(x0,y0,x1,y1)))
        result = min(choices)[1] if choices else None
        self._cells[glyph.id] = result
        return result


def edge_covers(edges, position, start, end, tolerance=.75):
    covered = start
    # Horizontal tuples are (start,position,end); vertical callers supply the
    # equivalent axis order through the branch below.
    ranges = [(a,b) for a,p,b in edges if abs(p-position)<=tolerance]
    for a,b in sorted(ranges):
        if a>covered+tolerance:
            break
        if b>=covered:
            covered = max(covered,b)
        if covered>=end-tolerance:
            return True
    return False


def contains(rect, inner, tolerance=0.):
    return rect[0]-tolerance<=inner[0] and rect[1]-tolerance<=inner[1] and inner[2]<=rect[2]+tolerance and inner[3]<=rect[3]+tolerance


def selection_index(model):
    """Cache per PageModel; a page reload/revision gets its own geometry index."""
    cached = getattr(model,'_selection_index_v300',None)
    if cached is None:
        cached = SelectionIndex(model)
        model._selection_index_v300 = cached
    return cached


def selected_in_area(model, rect):
    values = tuple(float(v) for v in rect)
    if len(values)!=4 or not all(isfinite(v) for v in values) or values[2]<=values[0] or values[3]<=values[1]:
        raise EditError('El área de selección no es válida.')
    selected = []
    for glyph in model.glyphs:
        if glyph.mode==3 or glyph.opacity<=0:
            continue
        b = glyph.bbox
        cx,cy = (b[0]+b[2])/2,(b[1]+b[3])/2
        if values[0]<=cx<=values[2] and values[1]<=cy<=values[3]:
            if not contains(values,b,.01):
                raise EditError('El borde corta caracteres. Amplía el área para incluirlos completos.')
            selected.append(glyph)
    if not selected:
        raise EditError('No hay texto visible dentro del área elegida.')
    return selected


def draft_overflow(rect, required_width, required_height, tolerance=.5):
    width,height = rect[2]-rect[0],rect[3]-rect[1]
    return (required_width>width+tolerance,required_height>height+tolerance)


def enlarged_area(rect, required_width, required_height, page_rect):
    """Explicit expansion preserves the anchor and never extends outside page."""
    x0,y0,x1,y1 = rect
    result = (x0,y0,max(x1,x0+required_width),max(y1,y0+required_height))
    if not contains(page_rect,result,.035):
        raise EditError('La ampliación supera el borde de página. Redistribuye el texto o elige un tamaño de letra.')
    return result
