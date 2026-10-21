"""Read-only text search with one navigable result per logical occurrence.

Only MuPDF's text extraction runs here. No font inventory, editable page model,
PDF rewrite or OCR is required. Geometry stays in unrotated page coordinates.
"""
import math
import unicodedata

import pymupdf as fitz

from .model import EditError
from .draft_control_v305 import checkpoint


MAX_QUERY_LENGTH = 4096
CONTEXT_BEFORE = 45
CONTEXT_AFTER = 70


def _plain(text):
    return ' '.join(unicodedata.normalize('NFKC', text).replace('\u00ad', '').split())


def _normalized(units):
    """Normalize a grapheme together, retaining every source glyph it covers."""
    text, references = [], []
    cluster = []

    def flush():
        if not cluster:
            return
        normalized = unicodedata.normalize('NFKC', ''.join(c for c, _ in cluster)).replace('\u00ad', '')
        ids = tuple(dict.fromkeys(i for _, i in cluster if i is not None))
        for char in normalized:
            if char.isspace():
                if not text or text[-1] == ' ':
                    continue
                char = ' '
            text.append(char)
            references.append(ids)
        cluster.clear()

    for char, reference in units:
        if cluster and not unicodedata.category(char).startswith('M'):
            # Canonical composition can also cross characters whose combining
            # class is zero, notably decomposed Hangul and half-width kana.
            previous = ''.join(c for c, _ in cluster)
            joins = (not (previous.isascii() and char.isascii())
                     and unicodedata.normalize('NFKC', previous + char)
                     != unicodedata.normalize('NFKC', previous) + unicodedata.normalize('NFKC', char))
            if not joins:
                flush()
        cluster.append((char, reference))
    flush()
    if text and text[-1] == ' ':
        text.pop()
        references.pop()
    return ''.join(text), references


def _line_separator(previous, current):
    """Do not invent a phrase across columns MuPDF puts in one text block."""
    if previous is None:
        return ''
    before = [c for s in previous.get('spans', []) for c in s.get('chars', [])]
    after = [c for s in current.get('spans', []) for c in s.get('chars', [])]
    if not before or not after:
        return ' '
    direction = current.get('dir', (1., 0.))
    old_direction = previous.get('dir', (1., 0.))
    if abs(direction[0] - old_direction[0]) + abs(direction[1] - old_direction[1]) > .05:
        return '\x00'
    origin_before, origin_after = before[-1]['origin'], after[0]['origin']
    baseline_gap = abs(-direction[1] * (origin_after[0] - origin_before[0])
                       + direction[0] * (origin_after[1] - origin_before[1]))
    def project(bounds):
        x0, y0, x1, y1 = bounds
        return [direction[0] * x + direction[1] * y for x, y in ((x0,y0),(x1,y0),(x0,y1),(x1,y1))]
    inline_gap = min(project(after[0]['bbox'])) - max(project(before[-1]['bbox']))
    size = max((s.get('size', 10.) for s in current.get('spans', [])), default=10.)
    if baseline_gap < max(1., size * .1) and inline_gap > max(24., size * 2.5):
        return '\x00'
    return ' '


def _block_text(block, number):
    units, glyphs = [], []
    previous = None
    for line_number, line in enumerate(block.get('lines', [])):
        if line_number and line_number % 64 == 0:
            checkpoint()
        try:
            separator = _line_separator(previous, line)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise EditError('La página contiene posiciones de texto no válidas para buscar.') from exc
        if units and separator:
            units.append((separator, None))
        previous = line
        direction = line.get('dir', (1., 0.))
        if len(direction) != 2 or not all(math.isfinite(v) for v in direction):
            raise EditError('La página contiene direcciones de texto no válidas para buscar.')
        for span in line.get('spans', []):
            for char in span.get('chars', []):
                value = char.get('c', '')
                bounds = tuple(char.get('bbox', ()))
                if (not value or len(bounds) != 4 or not all(math.isfinite(v) for v in bounds)
                        or bounds[2] < bounds[0] or bounds[3] < bounds[1]):
                    raise EditError('La página contiene posiciones de texto no válidas para buscar.')
                origin = char.get('origin', (bounds[0], bounds[3]))
                if len(origin) != 2 or not all(math.isfinite(v) for v in origin):
                    raise EditError('La página contiene posiciones de texto no válidas para buscar.')
                # DEHYPHENATE can combine physical lines into one extracted line.
                # The normal projection of its baseline keeps their highlights
                # separate, including text written vertically or on a slant.
                baseline = -direction[1] * origin[0] + direction[0] * origin[1]
                fragment = (number, line_number, round(baseline, 1))
                index = len(glyphs)
                if index and index % 4096 == 0:
                    checkpoint()
                glyphs.append((bounds, fragment))
                units.extend((c, index) for c in value)
    text, references = _normalized(units)
    return text, references, glyphs


def _fold(text, case_sensitive):
    if case_sensitive:
        return text, list(range(len(text)))
    parts, indices = [], []
    for index, char in enumerate(text):
        folded = char.casefold()
        parts.append(folded)
        indices.extend([index] * len(folded))
    return ''.join(parts), indices


def _word_character(char):
    return char.isalnum() or char == '_' or unicodedata.category(char).startswith('M')


def _rectangles(references, glyphs, start, end):
    groups = {}
    seen = set()
    for indices in references[start:end]:
        for index in indices:
            if index in seen:
                continue
            seen.add(index)
            bounds, fragment = glyphs[index]
            if fragment in groups:
                previous = groups[fragment]
                groups[fragment] = (min(previous[0], bounds[0]), min(previous[1], bounds[1]),
                                    max(previous[2], bounds[2]), max(previous[3], bounds[3]))
            else:
                groups[fragment] = bounds
    return list(groups.values())


def search_document(document, text, *, case_sensitive=False, whole_word=False):
    """Return plain contextual results without changing ``document``.

    Whitespace, compatibility ligatures and canonically equivalent Unicode are
    normalized. Phrases can continue across lines inside one extracted text
    block; unrelated text blocks and columns are never joined for a match.
    ``rect`` is the union for older readers; ``rects`` keeps physical fragments.
    ``context_start``/``context_end`` identify the occurrence within ``context``.
    """
    if not isinstance(text, str):
        raise EditError('Escribe el texto que deseas buscar.')
    if len(text) > MAX_QUERY_LENGTH:
        raise EditError('El texto de búsqueda supera el máximo de 4096 caracteres.')
    if any(ord(c) < 32 and not c.isspace() for c in text):
        raise EditError('La búsqueda contiene caracteres de control no válidos.')
    query = _plain(text)
    if not query:
        return []
    needle = query if case_sensitive else query.casefold()
    flags = (fitz.TEXTFLAGS_RAWDICT | fitz.TEXT_DEHYPHENATE) & ~fitz.TEXT_PRESERVE_IMAGES
    matches = []
    for page in document:
        checkpoint()
        raw = page.get_text('rawdict', flags=flags, sort=True)
        for block_number, block in enumerate(raw.get('blocks', [])):
            if block_number and block_number % 64 == 0:
                checkpoint()
            if block.get('type') != 0:
                continue
            # Most blocks on a long document do not contain the query. Avoid
            # allocating a per-character geometry map for those blocks. The
            # permissive prefilter may cross columns; the exact pass never does.
            candidate = _plain(' '.join(''.join(c.get('c', '') for s in line.get('spans', [])
                                               for c in s.get('chars', []))
                                        for line in block.get('lines', [])))
            if needle not in (candidate if case_sensitive else candidate.casefold()):
                continue
            display, references, glyphs = _block_text(block, block_number)
            searchable, mapping = _fold(display, case_sensitive)
            offset = 0
            occurrences = 0
            while True:
                start = searchable.find(needle, offset)
                if start < 0:
                    break
                end = start + len(needle)
                offset = end
                occurrences += 1
                if occurrences % 256 == 0:
                    checkpoint()
                # Do not count half of a casefold expansion (e.g. one "s" in ß).
                if ((start and mapping[start] == mapping[start - 1])
                        or (end < len(mapping) and mapping[end] == mapping[end - 1])):
                    continue
                if whole_word and ((start and _word_character(searchable[start - 1]))
                                   or (end < len(searchable) and _word_character(searchable[end]))):
                    continue
                first, last = mapping[start], mapping[end - 1] + 1
                rectangles = _rectangles(references, glyphs, first, last)
                if not rectangles:
                    continue
                left, right = max(0, first - CONTEXT_BEFORE), min(len(display), last + CONTEXT_AFTER)
                left = max(left, display.rfind('\x00', 0, first) + 1)
                boundary = display.find('\x00', last)
                if boundary >= 0:
                    right = min(right, boundary)
                prefix, suffix = ('…' if left else ''), ('…' if right < len(display) else '')
                context = prefix + display[left:right] + suffix
                union = (min(r[0] for r in rectangles), min(r[1] for r in rectangles),
                         max(r[2] for r in rectangles), max(r[3] for r in rectangles))
                matches.append({'page': page.number, 'rect': union, 'rects': rectangles,
                                'text': display[first:last], 'context': context,
                                'context_start': len(prefix) + first - left,
                                'context_end': len(prefix) + last - left})
    return matches
