"""Prepare a larger styled draft without editing PDF bytes or session history.

Only a verified source selection supplies the surrounding characters. The
ordinary rich compositor remains responsible for links, marked-content owners,
clipping, neighbors and final validation when this draft is previewed/accepted.
"""
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import math

import pymupdf as fitz

from .engine import extract_page
from .model import EditError, union
from .richtext import selection_payload
from .selection_v300 import contains, selected_in_area, selection_index


def _fail(message):
    raise EditError('Redistribuir vecinos: '+message)


def _area(rect, width=None, height=None):
    if not isinstance(rect, (tuple, list)) or len(rect) != 4:
        _fail('el borrador necesita un área de texto válida.')
    values = tuple(rect)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        _fail('el área contiene coordenadas no válidas.')
    x0, y0, x1, y1 = values
    for value in (width, height):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value <= 0):
            _fail('la anchura y la altura deben ser positivas y finitas.')
    if width is not None:
        x1 = x0+width
    if height is not None:
        y1 = y0+height
    if x1 <= x0 or y1 <= y0:
        _fail('el área debe tener anchura y altura positivas.')
    return (float(x0), float(y0), float(x1), float(y1))


def _slice_runs(runs, begin, end):
    result, offset = [], 0
    for original in runs:
        text = original['text']
        stop = offset+len(text)
        a, b = max(begin, offset), min(end, stop)
        if a < b:
            result.append(dict(deepcopy(original), text=text[a-offset:b-offset]))
        offset = stop
    return result


def _join_soft_breaks(runs):
    text = ''.join(run['text'] for run in runs)
    result, offset = [], 0
    for original in runs:
        output = []
        for position, char in enumerate(original['text'], offset):
            if char == '\u2028':
                before = text[position-1] if position else ''
                after = text[position+1] if position+1 < len(text) else ''
                char = '' if before.isspace() or after.isspace() else ' '
            output.append(char)
        offset += len(original['text'])
        value = ''.join(output)
        if value:
            result.append(dict(deepcopy(original), text=value))
    return result


def _paragraph_settings(entries, index):
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            _fail('las opciones de párrafo no son válidas.')
        if entry.get('index', index) == index:
            result.update({key: deepcopy(value) for key, value in entry.items() if key != 'index'})
    return result


def _paragraphs(source, draft, text, begin, end, replacement):
    first = text[:begin].count('\n')
    last = first+text[begin:end].count('\n')
    new_breaks = replacement.count('\n')
    delta = new_breaks-(last-first)
    count = text.count('\n')+1+delta
    result = []
    for index in range(count):
        if index < first:
            original_index = index
        elif index > first+new_breaks:
            original_index = index-delta
        elif index == first+new_breaks and index != first:
            original_index = last
        else:
            original_index = first
        settings = _paragraph_settings(source, original_index)
        if first <= index <= first+new_breaks:
            settings.update(_paragraph_settings(draft, index-first))
        result.append(dict(settings, index=index))
    return result


def _preserve_neighbor_paragraphs(runs, text, stops, ordered_ids, by_id, index,
                                  begin, end, paragraphs):
    """Keep inferred neighboring parents distinct without changing caret offsets."""
    promoted, groups = set(), {}
    for position, (previous, following) in enumerate(zip(ordered_ids, ordered_ids[1:])):
        gap_begin, gap_end = stops[position][1], stops[position+1][0]
        breaks = [offset for offset in range(gap_begin, gap_end)
                  if text[offset] == '\u2028' and not begin <= offset < end]
        if not breaks:
            continue
        for glyph_id in (previous, following):
            if glyph_id not in groups:
                groups[glyph_id] = frozenset(index.group(by_id[glyph_id], 'paragraph'))
        before, after = groups[previous], groups[following]
        if before == after:
            continue
        if previous not in before or following not in after or before & after:
            _fail('el límite entre párrafos vecinos es ambiguo; delimita un único párrafo.')
        promoted.update(breaks)
    if not promoted:
        return runs, text, paragraphs
    result, offset = [], 0
    for original in runs:
        converted = ''.join('\n' if offset+i in promoted else char
                            for i, char in enumerate(original['text']))
        result.append(dict(deepcopy(original), text=converted))
        offset += len(original['text'])
    converted_text = ''.join(run['text'] for run in result)
    # Newly inferred parents inherit the original surrounding block settings.
    # Existing hard-paragraph settings keep their source association even when
    # an earlier soft boundary becomes an additional paragraph.
    mapped, original_index = [], 0
    settings = _paragraph_settings(paragraphs, original_index)
    mapped.append(dict(settings, index=0))
    for position, char in enumerate(converted_text):
        if char != '\n':
            continue
        if text[position] == '\n':
            original_index += 1
        settings = _paragraph_settings(paragraphs, original_index)
        mapped.append(dict(settings, index=len(mapped)))
    return result, converted_text, mapped


def prepare_neighbor_draft(data, request, scope='paragraph', resolver=None, *, page_model=None):
    """Splice the current draft into one corrected paragraph/cell/explicit area."""
    draft = asdict(request) if is_dataclass(request) else deepcopy(request)
    if not isinstance(draft, dict) or draft.get('revision') != hashlib.sha256(data).hexdigest():
        _fail('el borrador pertenece a otra revisión del documento.')
    if scope not in ('paragraph', 'cell', 'area'):
        _fail('elige párrafo, celda o área explícita.')
    page_number, ids = draft.get('page'), draft.get('ids')
    if (isinstance(page_number, bool) or not isinstance(page_number, int)
            or not isinstance(ids, (list, tuple)) or not ids
            or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)
            or len(set(ids)) != len(ids)):
        _fail('la selección del borrador no es válida.')
    runs = draft.get('runs')
    if not isinstance(runs, list) or any(not isinstance(run, dict) or not isinstance(run.get('text'), str) for run in runs):
        _fail('los fragmentos de formato del borrador no son válidos.')
    with fitz.open(stream=data, filetype='pdf') as document:
        if not 0 <= page_number < len(document):
            _fail('la página del borrador no existe.')
        page = document[page_number]
        page_bounds = (0., 0., page.cropbox.width, page.cropbox.height)
        model = (page_model if page_model is not None and page_model.number == page_number
                 and page_model.revision == draft['revision'] else extract_page(document, page_number, data))
    selected = model.selected(ids)
    if len(selected) != len(ids) or any(g.mode == 3 or g.opacity <= 0 for g in selected):
        _fail('selecciona texto visible de la revisión actual.')
    original = selection_payload(data, page_number, ids, resolver, page_model=model)
    if set(original['ids']) != set(ids):
        _fail('la selección corta un clúster de texto; selecciona sus caracteres completos.')
    draft_area = _area(draft.get('rect') or original['rect'], draft.get('width'), draft.get('height'))
    if not contains(page_bounds, draft_area, .001):
        _fail('el área del borrador sale de la página.')
    index = selection_index(model)
    cell = None
    if scope == 'area':
        members = selected_in_area(model, draft_area)
        scope_ids = {g.id for g in members}
        if not set(ids) <= scope_ids:
            _fail('el área explícita no incluye la selección original completa.')
    else:
        cell = index.cell_rect(selected[0])
        if scope == 'cell' and cell is None:
            _fail('no se encontró una celda cerrada; delimita el área explícitamente.')
        scope_ids = set(index.group(selected[0], scope))
        if not set(ids) <= scope_ids:
            _fail('la selección abarca distintos párrafos o celdas.')
        for glyph in selected:
            if set(index.group(glyph, scope)) != scope_ids:
                _fail('la selección no pertenece a un único párrafo o celda.')
            if scope == 'cell' and index.cell_rect(glyph) != cell:
                _fail('la selección abarca distintos recintos de celda.')
    ordered_ids = [g.id for g in model.glyphs if g.id in scope_ids]
    positions = [i for i, glyph_id in enumerate(ordered_ids) if glyph_id in set(ids)]
    if not positions or positions != list(range(positions[0], positions[-1]+1)):
        _fail('el borrador contiene fragmentos separados; redistribuye un tramo continuo.')
    expanded = selection_payload(data, page_number, ordered_ids, resolver, page_model=model)
    if expanded.get('revision') != draft['revision'] or expanded['ids'] != ordered_ids:
        _fail('el alcance ampliado no conserva una correspondencia verificable con los caracteres originales.')
    full_text = ''.join(run['text'] for run in expanded['runs'])
    carets = {}
    for caret in expanded.get('carets', []):
        if 'id' not in caret:
            continue
        glyph_id, logical_index = caret['id'], caret.get('index')
        if (glyph_id in carets or not isinstance(logical_index, int) or isinstance(logical_index, bool)
                or not 0 <= logical_index <= len(full_text)):
            _fail('los cursores del texto no tienen una correspondencia única verificable.')
        carets[glyph_id] = caret
    if any(glyph_id not in carets for glyph_id in ordered_ids):
        _fail('el texto usa clústeres sin cursores por carácter verificables para ampliar el borrador.')
    by_id = {g.id: g for g in model.glyphs}
    stops = []
    for glyph_id in ordered_ids:
        caret = carets[glyph_id]
        text = caret.get('text')
        if not isinstance(text, str) or text != by_id[glyph_id].text or full_text[caret['index']:caret['index']+len(text)] != text:
            _fail('un cursor no corresponde al carácter original del PDF.')
        stops.append((caret['index'], caret['index']+len(text)))
    if any(a[1] > b[0] for a, b in zip(stops, stops[1:])):
        _fail('el orden lógico de los caracteres es ambiguo para redistribuirlos.')
    begin, end = stops[positions[0]][0], stops[positions[-1]][1]
    if set(ids) == scope_ids:
        begin, end = 0, len(full_text)
    if full_text[begin:end] != ''.join(run['text'] for run in original['runs']):
        _fail('el intervalo lógico del borrador no coincide con su selección original.')
    source_runs, source_paragraphs = expanded['runs'], expanded.get('paragraphs', [])
    if scope in ('cell', 'area'):
        source_runs, full_text, source_paragraphs = _preserve_neighbor_paragraphs(
            source_runs, full_text, stops, ordered_ids, by_id, index, begin, end,
            source_paragraphs)
    replacement = ''.join(run['text'] for run in runs)
    paragraphs = _paragraphs(source_paragraphs, draft.get('paragraphs', []),
                             full_text, begin, end, replacement)
    output_runs = _join_soft_breaks(_slice_runs(source_runs, 0, begin)+deepcopy(runs)
                                   +_slice_runs(source_runs, end, len(full_text)))
    scope_bounds = union(g.bbox for g in model.selected(ordered_ids))
    area = draft_area if scope == 'area' else union((scope_bounds, draft_area))
    if cell is not None:
        if not contains(cell, draft_area, .001):
            _fail('el área del borrador sale de la celda delimitada.')
        # Metric boxes may overhang a known edge by the selection tolerance;
        # the compositor still proves the original and planned painted ink.
        if not contains(cell, area, .5):
            _fail('el alcance ampliado sale de la celda delimitada.')
        area = (max(area[0], cell[0]), max(area[1], cell[1]),
                min(area[2], cell[2]), min(area[3], cell[3]))
    if not contains(page_bounds, area, .001):
        _fail('el alcance ampliado sale de la página.')
    expanded.update(page=page_number, ids=ordered_ids, runs=output_runs,
                    text=''.join(run['text'] for run in output_runs), paragraphs=paragraphs,
                    rect=list(area), width=area[2]-area[0], height=area[3]-area[1],
                    auto_width=False, auto_height=bool(draft.get('auto_height', False)) if cell is None else False,
                    allow_overlap=bool(draft.get('allow_overlap', False)), carets=[],
                    _explicit_area_v300=True,
                    neighbor_layout_info={'neighbor_count': len(ordered_ids)-len(ids), 'scope': scope})
    return expanded
