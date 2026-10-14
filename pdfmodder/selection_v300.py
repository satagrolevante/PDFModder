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
    """Return painted straight edges and centerlines of proven thin filled bars."""
    edges = []
    for drawing in drawings:
        if drawing.get('type') == 'f':
            items = drawing.get('items', [])
            # Use the actual rectangle path, never the drawing's bounding box.
            # Compound fills can contain holes or several unrelated shapes.
            if (drawing.get('fill') is None or drawing.get('fill_opacity') != 1.
                    or len(items) != 1 or not items[0] or items[0][0] != 're'):
                continue
            try:
                x0, y0, x1, y1 = map(float, items[0][1])
            except (IndexError, TypeError, ValueError):
                continue
            if not all(isfinite(value) for value in (x0, y0, x1, y1)):
                continue
            width, height = x1-x0, y1-y0
            thickness, length = min(width, height), max(width, height)
            # Half the bar thickness must fit the existing .75 pt edge-joining
            # tolerance. Broad fills and short decorative marks stay excluded.
            if not (0 < thickness <= 1.5 and length >= max(5., 10*thickness)):
                continue
            if width > height:
                middle = (y0+y1)/2
                edges.append((x0, middle, x1, middle))
            else:
                middle = (x0+x1)/2
                edges.append((middle, y0, middle, y1))
            continue
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
        by_id = {g.id:g for g in model.glyphs}
        self.semantic_by_id = {}
        for ids in getattr(model, 'semantic_paragraph_scopes', ()) or ():
            # These scopes come from the immutable snapshot's verified /P
            # owners. Incomplete or overlapping evidence never broadens a click.
            if not ids or len(set(ids)) != len(ids) or any(i not in by_id for i in ids):
                continue
            members = tuple(by_id[i] for i in ids)
            for i in ids:
                previous = self.semantic_by_id.get(i, members)
                self.semantic_by_id[i] = members if previous == members else None
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
        semantic = self.semantic_by_id.get(glyph.id)
        if semantic:
            members = [g for g in semantic if _family(g) == _family(glyph)]
            cell = self.cell_rect(glyph)
            if cell:
                members = [g for g in members if contains(cell, g.bbox, .5)]
            rows = {}
            for g in members:
                rows.setdefault(id(self.by_id.get(g.id)), []).append(g)
            direction = _direction(glyph)
            ordered = sorted(rows.values(),key=lambda row:
                             _project(union(g.bbox for g in row),direction)[1::-1])
            position = next((i for i,row in enumerate(ordered)
                             if any(g.id == glyph.id for g in row)),None)
            if position is not None:
                left = right = position
                while left and not self._separates(union(g.bbox for g in ordered[left-1]),
                                                   union(g.bbox for g in ordered[left])):
                    left -= 1
                while right+1<len(ordered) and not self._separates(union(g.bbox for g in ordered[right]),
                                                                union(g.bbox for g in ordered[right+1])):
                    right += 1
                return [g for row in ordered[left:right+1] for g in row]
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

        block_positions = {}
        for row in self.lines:
            if _family(row[0]) == _family(glyph):
                position = _project(union(g.bbox for g in row),direction)[1]
                for block in {g.block for g in row}:
                    block_positions.setdefault(block,set()).add(position)
        block_steps = {}
        for block, positions in block_positions.items():
            ordered = sorted(positions)
            distances = [b-a for a,b in zip(ordered,ordered[1:])
                         if base_size*.3 <= b-a <= base_size*2.1]
            if distances:
                block_steps[block] = median(distances)

        def connected(a, b):
            pa, la = a; pb, lb = b
            size = max(median(g.size for g in la),median(g.size for g in lb))
            # Same-baseline candidates are separate columns/overprinted runs.
            if pb[1]-pa[1] < max(1., size*.3) or pb[1]-pa[1] > size*2.1:
                return False
            ablocks,bblocks={g.block for g in la},{g.block for g in lb}
            if not ablocks & bblocks:
                steps=[block_steps[block] for block in ablocks|bblocks if block in block_steps]
                typical=median(steps) if steps else size*1.4
                # A larger gap across extraction blocks is a paragraph/heading
                # break, even when the shorter last line aligns with it.
                if pb[1]-pa[1] > typical*1.35:
                    return False
            return not self._separates(union(g.bbox for g in la),union(g.bbox for g in lb))

        left = right = first
        while left and connected(candidates[left-1], candidates[left]):
            left -= 1
        while right+1 < len(candidates) and connected(candidates[right], candidates[right+1]):
            right += 1
        chosen = candidates[left:right+1]
        # First-line indentation and a shorter final line need not share the
        # seed line's left/right edges. Accept a continuation only inside the
        # established body margin, with the same extraction block, compatible
        # baseline spacing, and no column or painted-cell barrier.
        if len(chosen) >= 2:
            body_left = min(projected[0] for projected,_ in chosen)
            body_right = max(projected[2] for projected,_ in chosen)
            blocks = {g.block for _,row in chosen for g in row}
            selected_rows = {id(row) for _,row in chosen}
            continuations = []
            for row in self.lines:
                if id(row) in selected_rows or _family(row[0]) != _family(glyph):
                    continue
                if not all(g.block in blocks for g in row):
                    continue
                rect = union(g.bbox for g in row)
                if cell and not contains(cell, rect, .5):
                    continue
                projected = _project(rect,direction)
                size = median(g.size for g in row)
                margin = projected[0]-body_left
                before = projected[1] < chosen[0][0][1]
                tolerance = max(2.,base_size*.8)
                if (not -tolerance <= margin <= (base_size*4 if before else tolerance) or
                        projected[2]>body_right+max(2.,base_size*.8) or
                        not .67<=size/max(base_size,.1)<=1.5):
                    continue
                continuations.append((projected,row))
            earlier = [pair for pair in continuations if pair[0][1]<chosen[0][0][1]]
            for continuation in sorted(earlier,key=lambda pair:pair[0][1],reverse=True):
                if connected(continuation,chosen[0]):
                    chosen.insert(0,continuation)
                    break
            for continuation in sorted(continuations,key=lambda pair:pair[0][1]):
                if connected(chosen[-1],continuation):
                    chosen.append(continuation)
        return [g for _,line in chosen for g in line]

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
