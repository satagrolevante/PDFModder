"""Recognize exact rectangular PDF clipping paths without changing their paint.

The current path is independent of the q/Q graphics-state stack. Coordinates
are transformed when their segments are constructed, as required by PDF.
Curves, skewed polygons and unions with holes retain the unknown-state guard.
"""
import math

import pymupdf as fitz


class RectanglePath:
    def __init__(self):
        self.subpaths = []
        self.current = None
        self.invalid = False

    @staticmethod
    def _point(x, y, matrix):
        x, y = float(x), float(y)
        a, b, c, d, e, f = map(float, matrix)
        point = (a*x+c*y+e, b*x+d*y+f)
        if not all(math.isfinite(v) for v in point):
            raise ValueError('Non-finite clipping coordinate')
        return point

    def add(self, args, operator, matrix):
        try:
            if operator == b'm':
                self.current = [self._point(*args, matrix)]
                self.subpaths.append(self.current)
            elif operator == b'l':
                if self.current is None:
                    self.invalid = True
                else:
                    self.current.append(self._point(*args, matrix))
            elif operator == b'h':
                if self.current is None:
                    self.invalid = True
                elif self.current[-1] != self.current[0]:
                    self.current.append(self.current[0])
            elif operator == b're':
                x, y, width, height = map(float, args)
                self.current = [self._point(px, py, matrix) for px, py in
                                ((x, y), (x+width, y), (x+width, y+height), (x, y+height), (x, y))]
                self.subpaths.append(self.current)
            else:
                self.invalid = True
        except (TypeError, ValueError, OverflowError):
            self.invalid = True

    @staticmethod
    def _rectangle(points):
        # PDF fill/clip implicitly closes open subpaths. Remove redundant
        # vertices, but never replace an arbitrary path by its bounding box.
        clean = []
        for point in points:
            if not clean or point != clean[-1]:
                clean.append(point)
        if len(clean) > 1 and clean[-1] == clean[0]:
            clean.pop()
        changed = True
        while changed and len(clean) > 4:
            changed = False
            for index in range(len(clean)):
                previous, point, following = clean[index-1], clean[index], clean[(index+1)%len(clean)]
                if ((previous[0] == point[0] == following[0] and
                     min(previous[1], following[1]) <= point[1] <= max(previous[1], following[1])) or
                    (previous[1] == point[1] == following[1] and
                     min(previous[0], following[0]) <= point[0] <= max(previous[0], following[0]))):
                    del clean[index]
                    changed = True
                    break
        if len(clean) != 4:
            return None
        xs, ys = sorted({point[0] for point in clean}), sorted({point[1] for point in clean})
        if len(xs) != 2 or len(ys) != 2 or set(clean) != {(x, y) for x in xs for y in ys}:
            return None
        if any(a[0] != b[0] and a[1] != b[1] for a, b in zip(clean, clean[1:]+clean[:1])):
            return None
        area = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(clean, clean[1:]+clean[:1]))
        if not area:
            return None
        return (xs[0], ys[0], xs[1], ys[1]), (1 if area > 0 else -1)

    def rectangle(self, *, even_odd=False):
        if self.invalid or not self.subpaths or len(self.subpaths) > 32:
            return None
        rectangles = [self._rectangle(points) for points in self.subpaths]
        if any(rectangle is None for rectangle in rectangles):
            return None
        if len(rectangles) == 1:
            return fitz.Rect(rectangles[0][0])
        xs = sorted({v for rect, _ in rectangles for v in (rect[0], rect[2])})
        ys = sorted({v for rect, _ in rectangles for v in (rect[1], rect[3])})
        filled = set()
        for ix, (left, right) in enumerate(zip(xs, xs[1:])):
            for iy, (bottom, top) in enumerate(zip(ys, ys[1:])):
                x, y = (left+right)/2, (bottom+top)/2
                signs = [sign for rect, sign in rectangles if rect[0] < x < rect[2] and rect[1] < y < rect[3]]
                if (len(signs)%2 if even_odd else sum(signs)):
                    filled.add((ix, iy))
        if not filled:
            return fitz.Rect(0, 0, 0, 0)
        left, right = min(ix for ix, _ in filled), max(ix for ix, _ in filled)
        bottom, top = min(iy for _, iy in filled), max(iy for _, iy in filled)
        if len(filled) != (right-left+1)*(top-bottom+1):
            return None
        return fitz.Rect(xs[left], ys[bottom], xs[right+1], ys[top+1])
