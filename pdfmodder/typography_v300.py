"""OpenType shaping with explicit PDF Unicode/cluster correspondence.

HarfBuzz owns glyph substitutions and positions. Unicode bidi owns the visual
order. PDF operators stay at the original paint position; original neighbouring
codes and their text cursor advances remain intact. No font fallback is used.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import copy
import json
import math
import struct
import unicodedata
from pathlib import Path

import pymupdf as fitz
from fontTools.ttLib import TTFont, TTLibError
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ByteStringObject, DictionaryObject, NameObject, TextStringObject

from .fonts import FontError, FontResolver, _check_characters, _check_embedding, _font_metadata
from .model import EditError, Glyph, intersects, union

KEY = 'PDFModderTypography'
SCHEMA = 1


def requires_shaping(runs):
    """The native simple path remains suitable for base14/plain legacy text."""
    for run in runs:
        text = str(run.get('text', ''))
        from fontTools.unicodedata import script
        if (run.get('font_axes') or run.get('font_features') or run.get('direction') == 'rtl'
                or any(unicodedata.combining(c) or unicodedata.bidirectional(c) in ('R', 'AL', 'AN')
                       or script(c) not in ('Latn', 'Grek', 'Cyrl', 'Hani', 'Hira', 'Kana', 'Hang', 'Zyyy', 'Zinh', 'Zzzz') for c in text)
                or run.get('font_file') and any(part in text for part in ('fi', 'fl', 'ff'))):
            return True
    return False


def preflight_shaping(data, page, ids):
    """Capability of one Unicode cluster selection, without changing a PDF."""
    from .engine import extract_page
    from .clipping import operator_glyph_map
    from .validation import document_issues, content_widget_issues
    result = dict(status='blocked', label='Composición avanzada no disponible', reasons=[],
                  actions=[], resolution_ids=[], fonts={}, unicode_verified=False)
    try:
        from .form_instances_v200 import isolate_selected_forms
        from .model import EditRequest
        isolated = isolate_selected_forms(data, EditRequest(page, list(ids)))
        if isolated is not None:
            local, current, evidence = isolated
            result = preflight_shaping(local, page, current.ids)
            result['form_isolation'] = evidence
            return result
        with fitz.open(stream=data, filetype='pdf') as doc:
            issues = document_issues(data, doc, operation='content')
            model = extract_page(doc, page, data)
            selected = model.selected(ids)
            if not selected or len(selected) != len(set(ids)):
                raise EditError('Selecciona un clúster de texto del documento actual.')
            issues.extend(content_widget_issues(doc[page], [g.bbox for g in selected]))
            if issues:
                result['reasons'] = issues
                return result
            from .clipping import CLIP_ISSUE
            if any(issue != CLIP_ISSUE for issue in model.issues):
                result['reasons'] = [issue for issue in model.issues if issue != CLIP_ISSUE]
                return result
            if any(g.mode != 0 or g.layer or abs(g.direction[0]-1)+abs(g.direction[1]) > 1e-5 for g in selected):
                raise EditError('La orientación o pintura original requiere el editor de objetos.')
            _, operations, shows, mapping = operator_glyph_map(data, page, model)
            chosen = set(ids)
            for show in shows:
                if any(g.id in chosen for g in show['glyphs']):
                    _code_groups(show, operations)
            result['unicode_verified'] = True
            missing = []
            for xref in {g.font_xref for g in selected}:
                if not xref:
                    missing.append('Fuente original no identificada.')
                    continue
                name, _, _, fontdata = doc.extract_font(xref)
                metadata = _font_metadata(fontdata, name) if fontdata else {}
                text = ''.join(g.text for g in selected if g.font_xref == xref and g.text != '\ufffd')
                try:
                    _check_embedding(metadata, name, subset=bool(metadata.get('subset')))
                    with TTFont(BytesIO(fontdata)):
                        pass
                    if metadata.get('outline_format') != 'TrueType':
                        raise FontError('La composición avanzada requiere contornos TrueType TTF/OTF.')
                    _check_characters(fitz.Font(fontbuffer=fontdata), text, name)
                    result['fonts'][name] = dict(metadata, shaping='HarfBuzz')
                except (FontError, TTLibError, ValueError, RuntimeError) as exc:
                    missing.append(f'{name}: necesita un archivo TTF/OTF completo para recomponer.')
            result.update(status='conditional' if missing else 'available',
                          label='Elegir fuente completa' if missing else 'Composición avanzada disponible',
                          reasons=missing, actions=['Abrir editor por fragmentos y elegir una fuente TTF/OTF completa.'] if missing else [],
                          resolution_ids=['rich_editor', 'choose_font'] if missing else ['rich_editor'])
    except (EditError, ValueError, RuntimeError, KeyError) as exc:
        result['reasons'] = [str(exc)]
        result['actions'] = ['Abrir el editor de objetos para conservar la pintura original.']
        result['resolution_ids'] = ['object_editor']
    return result


def source_clusters(data, page, model, ids):
    """Expand selected PDF codes, retaining independently extracted Unicode."""
    from .clipping import operator_glyph_map
    selected = model.selected(ids)
    if not any(not g.reliable or unicodedata.combining(g.text) or unicodedata.bidirectional(g.text) in ('R', 'AL', 'AN') for g in selected):
        return selected, False
    _, operations, shows, mapping = operator_glyph_map(data, page, model)
    chosen = set(ids)
    normalized = {}
    for show in shows:
        if not any(g.id in chosen for g in show['glyphs']):
            continue
        _, groups = _code_groups(show, operations)
        for code, members in groups:
            if any(g.id in chosen for g in members):
                if any(g.text == '\ufffd' for g in members):
                    raise EditError('La codificación original no proporciona Unicode verificable para este clúster.')
                bounds = union(g.bbox for g in members)
                for g in members:
                    normalized[g.id] = replace(g, bbox=bounds, line=members[0].line, block=members[0].block)
    if not chosen <= set(normalized):
        raise EditError('La fuente de la selección no tiene un operador verificable.')
    return [normalized[i] for i in sorted(normalized)], True


def _verified_records(doc, number, model):
    """Private records only authorize glyphs with matching Unicode and font bytes."""
    records = _records(doc, number)
    if not records:
        return []
    verified = []
    traces = [(span, ch) for span in doc[number].get_texttrace() for ch in span['chars']]
    glyph_index, trace_index, font_hashes, unicode_maps, gid_maps = {}, {}, {}, {}, {}
    def key(text, font, point):
        return text, font, math.floor(point[0]*10), math.floor(point[1]*10)
    for glyph in model.glyphs:
        glyph_index.setdefault(key(glyph.text, glyph.font, glyph.origin), []).append(glyph)
    for span, ch in traces:
        trace_index.setdefault(key(chr(ch[0]), span['font'], ch[2]), []).append((span, ch))
    def nearby(index, text, font, point):
        _, _, x, y = key(text, font, point)
        return [item for dx in (-1,0,1) for dy in (-1,0,1)
                for item in index.get((text,font,x+dx,y+dy), ())]
    def font_hash(xref):
        if xref not in font_hashes:
            font_hashes[xref] = sha256(doc.extract_font(xref)[3]).hexdigest()
        return font_hashes[xref]
    def encoding_matches(xref, saved):
        if 'cid' not in saved:
            return True
        if xref not in unicode_maps:
            from pypdf._cmap import _parse_to_unicode
            from pypdf.generic import DecodedStreamObject
            _, value = doc.xref_get_key(xref, 'ToUnicode')
            try:
                stream = DecodedStreamObject()
                stream.set_data(doc.xref_stream(int(value.split()[0])))
                unicode_maps[xref] = _parse_to_unicode(DictionaryObject({NameObject('/ToUnicode'):stream}))[0]
                _, descendants = doc.xref_get_key(xref, 'DescendantFonts')
                descendant = int(descendants.strip('[] ').split()[0])
                kind, value = doc.xref_get_key(descendant, 'CIDToGIDMap')
                gid_maps[xref] = doc.xref_stream(int(value.split()[0])) if kind == 'xref' else b''
            except (ValueError, TypeError, RuntimeError):
                unicode_maps[xref], gid_maps[xref] = {}, b''
        code = saved['cid']
        logical = unicode_maps[xref].get(chr(code))
        mapping = gid_maps[xref]
        start = code*2
        return (logical == saved.get('logical_unicode') and len(mapping) >= start+2
                and int.from_bytes(mapping[start:start+2], 'big') == saved.get('paint_gid'))
    globally_matched_ids = set()
    for record in records:
        value = record.get('text', '')
        if ''.join(r.get('text', '') for r in record.get('runs', [])) != value:
            continue
        if record.get('paragraph_id') and record.get('paragraph_text', '')[
                record.get('paragraph_offset', 0):record.get('paragraph_offset', 0)+len(value)] != value:
            continue
        unicode_valid = True
        for cluster in record.get('clusters', []):
            try:
                actual_text = ''.join(record['glyphs'][i]['text'] for i in cluster['physical_indices']
                                      if not record['glyphs'][i].get('auxiliary'))
                if actual_text != cluster['text'].replace('\t', ' ') or value[cluster['start']:cluster['end']] != cluster['text']:
                    unicode_valid = False
            except (KeyError, IndexError, TypeError):
                unicode_valid = False
        if not unicode_valid:
            continue
        actual = []
        matched_ids = set(globally_matched_ids)
        for saved in record.get('glyphs', []):
            candidates = [g for g in nearby(glyph_index, saved['text'], saved['font'], saved['origin'])
                          if g.id not in matched_ids and _same(g, saved)]
            if not candidates:
                actual = []
                break
            g = candidates[0]
            if 'gid' in saved and not any(ch[1] == saved['gid'] and chr(ch[0]) == g.text
                    and span['font'] == g.font and all(abs(a-b) < .035 for a, b in zip(ch[2], g.origin))
                    for span, ch in nearby(trace_index, g.text, g.font, g.origin)):
                actual = []
                break
            if saved.get('font_sha256'):
                if not g.font_xref:
                    references = [(item[0], item[4]) for item in doc[number].get_fonts()]
                    exact = [(xref, name) for xref, name in references if xref and
                             font_hash(xref) == saved['font_sha256'] and encoding_matches(xref, saved)]
                    if not exact:
                        actual = []
                        break
                    g = replace(g, font_xref=exact[0][0], font_resource='/'+exact[0][1])
                if font_hash(g.font_xref) != saved['font_sha256']:
                    actual = []
                    break
                if not encoding_matches(g.font_xref, saved):
                    actual = []
                    break
            actual.append(g)
            matched_ids.add(g.id)
        if actual:
            verified.append((record, actual))
            globally_matched_ids.update(g.id for g in actual)
    return verified


def _only_owned_marks(doc, number, records):
    """Do not remove a page incompatibility when any unrelated mark remains."""
    from collections import Counter
    from pypdf.generic import ContentStream, DecodedStreamObject
    stream = DecodedStreamObject()
    stream.set_data(b'\n'.join(doc.xref_stream(xref) for xref in doc[number].get_contents()))
    expected = Counter(c['text'] for record in records for c in record.get('clusters', []))
    expected_paragraphs = {r['paragraph_id']: r['paragraph_text'] for r in records if r.get('paragraph_tag')}
    actual_paragraphs = {}
    actual = Counter()
    depth = 0
    for args, op in ContentStream(stream, None).operations:
        if op in (b'BMC', b'BDC'):
            if op != b'BDC' or len(args) != 2 or not isinstance(args[1], dict):
                return False
            if str(args[0]) == '/PMT' and set(args[1]) == {'/ActualText'} and depth <= 1:
                actual[str(args[1]['/ActualText'])] += 1
            elif (str(args[0]) == '/PMParagraph' and set(args[1]) == {'/ActualText', '/PDFModderID'} and depth == 0):
                identity = str(args[1]['/PDFModderID'])
                if identity in actual_paragraphs:
                    return False
                actual_paragraphs[identity] = str(args[1]['/ActualText'])
            else:
                return False
            depth += 1
        elif op == b'EMC':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and actual == expected and actual_paragraphs == expected_paragraphs


def _records(doc, page):
    kind, value = doc.xref_get_key(doc[page].xref, KEY)
    if kind != 'string':
        return []
    try:
        data = json.loads(value)
        return data.get('records', []) if isinstance(data, dict) and data.get('schema') == SCHEMA else []
    except (TypeError, ValueError):
        return []


def _same(glyph, saved):
    return (glyph.text == saved.get('text') and glyph.font == saved.get('font')
            and abs(glyph.size - saved.get('size', -1)) < .002
            and all(abs(a-b) < .035 for a, b in zip(glyph.origin, saved.get('origin', (1e9, 1e9))))
            and all(abs(a-b) < .035 for a, b in zip(glyph.trace_bbox, saved.get('trace_bbox', glyph.trace_bbox))))


def insertion_anchor_ids(before, after):
    """Widget appearances need not follow the page contents in paint order."""
    remaining = list(before.glyphs)
    added = []
    for glyph in after.glyphs:
        matched = next((i for i, original in enumerate(remaining) if _same(glyph, asdict(original))), None)
        if matched is None:
            added.append(glyph.id)
        else:
            remaining.pop(matched)
    if remaining or len(added) != 1:
        raise EditError('No se pudo preparar un único punto de inserción sin alterar el contenido existente.')
    return added


def normalize_typography_model(doc, number, model):
    """Restore cluster hit geometry only for an entirely matching owned record.

    The stored string never replaces the PDF's independently extracted Unicode.
    A stale/moved record is ignored, so metadata cannot bless unrelated glyphs.
    """
    glyphs = list(model.glyphs)
    verified = False
    validated = _verified_records(doc, number, model)
    logical_runs = {}
    for record, actual in validated:
        verified = True
        by_index = {saved['physical_index']: g for saved, g in zip(record['glyphs'], actual)}
        identity = record.get('paragraph_id') or str(id(record))
        logical = logical_runs.setdefault(identity, dict(text=record.get('paragraph_text', record['text']),
                                                         paragraph_id=identity, clusters=[]))
        for cluster in record.get('clusters', []):
            members = [by_index[i] for i in cluster['physical_indices'] if i in by_index]
            if len(members) != len(cluster['physical_indices']):
                continue
            bounds = tuple(cluster['bbox'])
            for g in members:
                glyphs[g.id] = replace(g, reliable=True, bbox=bounds,
                                       block=record.get('block', g.block), line=cluster['line'])
            logical['clusters'].append(dict(cluster, ids=[g.id for g in members],
                start=record.get('paragraph_offset', 0)+cluster['start'],
                end=record.get('paragraph_offset', 0)+cluster['end']))
    issues = list(model.issues)
    if verified and _only_owned_marks(doc, number, [r for r, _ in validated]):
        # Owned ActualText wrappers have an independently checked Unicode map.
        issues = [issue for issue in issues if issue != 'Página con contenido marcado o capas sin estructura accesible verificable.']
    return replace(model, glyphs=glyphs, issues=issues, logical_text_runs=list(logical_runs.values()))


def logical_model_text(model, ids):
    """Copy original characters and owned cluster ranges in logical order."""
    selected = set(ids)
    entries, owned = {}, set()
    for run in model.logical_text_runs:
        clusters = sorted((c for c in run['clusters'] if selected.intersection(c['ids'])), key=lambda c: c['start'])
        if not clusters:
            continue
        chosen_ids = {i for c in clusters for i in c['ids']} & selected
        owned.update(chosen_ids)
        pieces, previous = [], None
        for cluster in clusters:
            if previous is not None:
                gap = run['text'][previous:cluster['start']]
                if gap and not gap.strip():
                    pieces.append(gap)
            pieces.append(run['text'][cluster['start']:cluster['end']])
            previous = cluster['end']
        entries[min(chosen_ids)] = ''.join(pieces)
    result, previous = [], None
    for glyph in model.selected(ids):
        if glyph.id in owned and glyph.id not in entries:
            continue
        if previous and (glyph.block != previous.block or glyph.line != previous.line):
            result.append('\n')
        result.append(entries.get(glyph.id, glyph.text))
        previous = glyph
    return ''.join(result)


def logical_order(model):
    """Stable logical ranks for verified text, preserving every paint ID."""
    ranks = {}
    for run in model.logical_text_runs:
        position = 0
        for cluster in sorted(run['clusters'], key=lambda c: c['start']):
            for index in cluster['ids']:
                ranks[index] = (run['paragraph_id'], position)
                position += 1
    return ranks


def selection_payload(data, page, ids, resolver=None):
    """Return None for unowned text; otherwise restore logical cluster ranges."""
    from .engine import extract_page
    resolver = resolver or FontResolver()
    with fitz.open(stream=data, filetype='pdf') as doc:
        records = _records(doc, page)
        if not records:
            return None
        model = extract_page(doc, page, data)
        selected = model.selected(ids)
        verified_records = []
        chosen_ids = {g.id for g in selected}
        for record, actual in _verified_records(doc, page, model):
            record = copy.deepcopy(record)
            for saved, g in zip(record['glyphs'], actual):
                saved['runtime_id'] = g.id
            verified_records.append(record)
        records = [r for r in verified_records if chosen_ids.intersection(g['runtime_id'] for g in r['glyphs'])]
        if len(records) > 1 and len({r.get('paragraph_id') for r in records}) == 1 and records[0].get('paragraph_id'):
            records = [_merge_paragraph_records([r for r in verified_records if r.get('paragraph_id') == records[0]['paragraph_id']])]
        if len(records) != 1:
            return None
        record = records[0]
        clusters = [c for c in record['clusters'] if any(record['glyphs'][i]['runtime_id'] in chosen_ids for i in c['physical_indices'])]
        if not clusters:
            return None
        begin, end = min(c['start'] for c in clusters), max(c['end'] for c in clusters)
        cluster_ids = {record['glyphs'][i]['runtime_id'] for c in clusters for i in c['physical_indices']}
        chosen = [g for g in model.glyphs if g.id in cluster_ids]
        runs = []
        offset = 0
        previews = []
        for run in record['runs']:
            stop = offset + len(run['text'])
            a, b = max(offset, begin), min(stop, end)
            if a < b:
                style = dict(run, text=run['text'][a-offset:b-offset])
                # The exact static instance is embedded in the PDF. A local
                # source file is useful only while deliberately changing axes.
                if style.get('font_file') and (not style.get('font_axes') or not Path(style['font_file']).is_file()):
                    style['font_file'] = None
                    style['font_axes'] = None
                matching = next((g for g in chosen if g.font == style.get('font_name')), None)
                if matching:
                    style.update(font_xref=matching.font_xref, font_resource=matching.font_resource)
                runs.append(style)
            offset = stop
        for g in chosen:
            if any(p['font_xref'] == g.font_xref for p in previews):
                continue
            if g.font_xref:
                name, _, _, buffer = doc.extract_font(g.font_xref)
                if buffer:
                    previews.append(dict(font_name=g.font, font_xref=g.font_xref, buffer=buffer,
                                         metadata=_font_metadata(buffer, name), source='instancia incrustada verificada'))
        carets = []
        for c in clusters:
            for index in range(c['start'], c['end']):
                carets.append(dict(index=index-begin, text=record['text'][index],
                                   origin=c['origin'], end=c['end_origin'], bbox=c['bbox'],
                                   cluster_start=c['start']-begin, cluster_end=c['end']-begin, rtl=c['rtl']))
        if clusters:
            last = max(clusters, key=lambda c: c['end'])
            carets.append(dict(index=end-begin, text='', origin=last['end_origin'], bbox=last['bbox']))
        return dict(page=page, ids=[g.id for g in chosen], runs=runs, rect=union(c['bbox'] for c in clusters),
                    text=record['text'][begin:end], revision=model.revision,
                    paragraphs=record.get('paragraphs', []) if begin == 0 else [],
                    carets=carets, font_previews=previews, typography=True,
                    clusters=[dict(c, start=c['start']-begin, end=c['end']-begin) for c in clusters])


def _merge_paragraph_records(records):
    """Range editing can split storage records while retaining one paragraph."""
    ordered = sorted(records, key=lambda r: r.get('paragraph_offset', 0))
    first = ordered[0]
    glyphs, clusters, runs = [], [], []
    cursor = 0
    for record in ordered:
        begin = record.get('paragraph_offset', 0)
        if begin > cursor:
            style = dict(runs[-1] if runs else record['runs'][0], text=first['paragraph_text'][cursor:begin])
            runs.append(style)
        base = len(glyphs)
        glyphs.extend(dict(g, physical_index=base+i) for i, g in enumerate(record['glyphs']))
        clusters.extend(dict(c, start=begin+c['start'], end=begin+c['end'],
                             physical_indices=[base+i for i in c['physical_indices']]) for c in record['clusters'])
        runs.extend(copy.deepcopy(record['runs']))
        cursor = begin+len(record['text'])
    return dict(first, text=first['paragraph_text'], paragraph_offset=0, glyphs=glyphs,
                clusters=sorted(clusters, key=lambda c: c['start']), runs=runs,
                rect=union(c['bbox'] for c in clusters))


def _face(doc, page, run, text, resolver):
    name = run.get('font_name') or 'Helvetica'
    axes = run.get('font_axes') or None
    if run.get('font_file'):
        return (resolver.resolve_explicit(name, text, run['font_file'], font_axes=axes) if axes
                else resolver.resolve_explicit(name, text, run['font_file']))
    xref = run.get('font_xref')
    if xref:
        extracted_name, _, _, data = doc.extract_font(xref)
        if data:
            from .fonts import ResolvedFont, instantiate_variable_font
            metadata = _font_metadata(data, extracted_name)
            _check_embedding(metadata, extracted_name, subset=bool(metadata.get('subset')))
            if metadata.get('variable'):
                data, evidence = instantiate_variable_font(data, axes)
                metadata = _font_metadata(data, extracted_name)
                metadata.update(evidence)
            font = fitz.Font(fontbuffer=data)
            _check_characters(font, text, extracted_name)
            return ResolvedFont(font.name, font, data, None, 'programa PDF verificado', metadata)
    return (resolver.resolve_explicit(name, text, font_axes=axes) if axes else resolver.resolve_explicit(name, text))


def _bidi_levels(text, base_direction=None):
    from bidi.algorithm import (get_empty_storage, get_base_level, get_embedding_levels,
                                explicit_embed_and_overrides, resolve_weak_types,
                                resolve_neutral_types, resolve_implicit_levels,
                                reorder_resolved_levels)
    storage = get_empty_storage()
    storage['base_level'] = {'ltr': 0, 'rtl': 1}.get(base_direction, get_base_level(text))
    storage['base_dir'] = ('L', 'R')[storage['base_level']]
    get_embedding_levels(text, storage, False, False)
    for i, item in enumerate(storage['chars']):
        item['source_index'] = i
    explicit_embed_and_overrides(storage, False)
    resolve_weak_types(storage, False)
    resolve_neutral_types(storage, False)
    resolve_implicit_levels(storage, False)
    levels = {item['source_index']: item['level'] for item in storage['chars']}
    reorder_resolved_levels(storage, False)
    visual = [item['source_index'] for item in storage['chars']]
    return levels, visual


def _shape_line(chars, direction=None, tab_stops=None, tab_interval=36):
    """Shape logical style/direction items, then order their clusters visually."""
    import uharfbuzz as hb
    if not chars:
        return [], 0.
    text = ''.join(c['char'] for c in chars)
    levels, visual = _bidi_levels(text, direction)
    visual_position = {i: pos for pos, i in enumerate(visual)}
    items = []
    for index, char in enumerate(chars):
        from fontTools.unicodedata import script
        writing = script(char['char'])
        if writing in ('Zyyy', 'Zinh', 'Zzzz'):
            writing = items[-1]['key'][-2] if items else next(
                (script(c['char']) for c in chars[index+1:] if script(c['char']) not in ('Zyyy', 'Zinh', 'Zzzz')), 'Latn')
        # The panel's diff can split a run into individual characters. Equal
        # formatting still belongs to one shaping item: a storage boundary
        # must neither break a ligature nor separate its combining marks.
        style = (char['face_key'], char['size'], char['color'], char['spacing'],
                 char['opacity'], char['underline'], tuple(sorted(char['features'].items())))
        key = (style, writing, levels.get(index, 0) % 2)
        if (unicodedata.combining(char['char']) and items and items[-1]['key'] != key):
            raise EditError('Una marca combinante cruza un cambio de formato. Aplica la misma fuente y tamaño al clúster completo.')
        if items and items[-1]['key'] == key:
            items[-1]['chars'].append((index, char))
        else:
            items.append(dict(key=key, chars=[(index, char)]))
    clusters = []
    for item in items:
        first = item['chars'][0][1]
        face = first['face']
        buffer = bytes(face.buffer or face.font.buffer)
        font = hb.Font(hb.Face(buffer))
        hb.ot_font_set_funcs(font)
        font.scale = (font.face.upem, font.face.upem)
        value = ''.join(c['char'] for _, c in item['chars'])
        buf = hb.Buffer()
        buf.add_codepoints([ord(' ' if c == '\t' else c) for c in value])
        buf.guess_segment_properties()
        buf.script = item['key'][-2]
        buf.direction = 'rtl' if item['key'][-1] else 'ltr'
        features = first.get('features') or {}
        hb.shape(font, buf, features)
        infos, positions = buf.glyph_infos, buf.glyph_positions
        if any(info.codepoint == 0 for info in infos):
            raise EditError('La fuente elegida no puede componer un glifo de esta escritura; selecciona una fuente completa.')
        starts = sorted({info.cluster for info in infos})
        stop = {a: b for a, b in zip(starts, starts[1:] + [len(value)])}
        shaped = {}
        cursor = 0.
        scale = first['size'] / font.face.upem
        for info, pos in zip(infos, positions):
            glyph = dict(gid=info.codepoint, x=cursor + pos.x_offset*scale,
                         y=-pos.y_offset*scale, advance=pos.x_advance*scale)
            cursor += pos.x_advance*scale
            shaped.setdefault(info.cluster, []).append(glyph)
        for start in starts:
            end = stop[start]
            members = item['chars'][start:end]
            indices = [i for i, _ in members]
            glyphs = shaped[start]
            left = min(g['x'] for g in glyphs)
            right = max(g['x'] + g['advance'] for g in glyphs)
            width = sum(g['advance'] for g in glyphs)
            for g in glyphs:
                g['x'] -= left
            clusters.append(dict(start=members[0][1]['index'], end=members[-1][1]['index']+1,
                                 text=value[start:end], glyphs=glyphs, width=width,
                                 spacing=first['spacing'], style=first,
                                 rtl=bool(item['key'][-1]),
                                 visual=min(visual_position.get(i, i) for i in indices)))
    cursor = 0.
    for cluster in sorted(clusters, key=lambda c: c['visual']):
        cluster['x'] = cursor
        if cluster['text'] == '\t':
            stops = [v for v in (tab_stops or []) if v > cursor+.001]
            target = stops[0] if stops else (math.floor(cursor/tab_interval)+1)*tab_interval
            cluster['width'] = target-cursor
        cursor += cluster['width'] + cluster['spacing']
    if clusters:
        cursor -= max(clusters, key=lambda c: c['visual'])['spacing']
    return sorted(clusters, key=lambda c: c['start']), cursor


def _prepare(doc, request, resolver):
    from .richtext import _finite, _paragraph
    from .engine import validate_rgb
    chars, faces, runs = [], {}, []
    index = 0
    for run_index, run in enumerate(request.runs):
        run = copy.deepcopy(run)
        run['text'] = unicodedata.normalize('NFC', str(run.get('text', '')).replace('\r\n', '\n').replace('\r', '\n'))
        text = run['text']
        if any(unicodedata.category(c).startswith('C') and c not in '\n\t\u200c\u200d' for c in text):
            raise EditError('El texto contiene controles no admitidos. La dirección se elige en el párrafo.')
        printable = ''.join(c for c in text if c not in '\n\u2028\t\u200c\u200d')
        try:
            face = _face(doc, request.page, run, printable, resolver)
        except FontError as exc:
            raise EditError(str(exc)) from exc
        key = sha256(bytes(face.buffer or face.font.buffer)).hexdigest()
        try:
            with TTFont(BytesIO(bytes(face.buffer or face.font.buffer))) as program:
                if 'glyf' not in program:
                    raise EditError('Esta composición requiere contornos TrueType TTF/OTF. Elige una fuente completa con esos contornos; CFF conserva la edición simple.')
        except TTLibError as exc:
            raise EditError('Elige una fuente TTF/OTF completa para usar composición avanzada; el recurso original no es OpenType verificable.') from exc
        faces[key] = face
        size = _finite(run.get('size', 12), 'Tamaño de letra', 1, 300)
        color = tuple(run.get('color') or (0., 0., 0.))
        validate_rgb(color)
        spacing = _finite(run.get('char_spacing', 0), 'Espaciado', -100, 300)
        opacity = _finite(run.get('opacity', 1), 'Opacidad', 0, 1)
        if opacity != 1:
            raise EditError('La composición avanzada conserva texto opaco; selecciona un fragmento con esa opacidad.')
        features = run.get('font_features') or {}
        if run.get('underline'):
            raise EditError('El subrayado de clústeres avanzados necesita una decoración aislada; retíralo antes de recomponer esta escritura.')
        if not isinstance(features, dict) or any(len(str(tag)) != 4 or not isinstance(value, (int, bool)) for tag, value in features.items()):
            raise EditError('Las funciones OpenType deben ser etiquetas de cuatro letras y valores enteros.')
        run.update(font_name=face.metadata.get('postscript_name') or face.name, size=size, color=color, char_spacing=spacing)
        if face.metadata.get('font_axes'):
            run['font_axes'] = face.metadata['font_axes']
        runs.append(run)
        for character in text:
            chars.append(dict(char=character, index=index, run=run_index, face=face, face_key=key,
                              size=size, color=color, spacing=spacing, opacity=opacity,
                              underline=bool(run.get('underline')), features=features))
            index += 1
    rect = tuple(request.rect)
    width = request.width if request.width is not None else rect[2]-rect[0]
    height = request.height if request.height is not None else rect[3]-rect[1]
    _finite(width, 'Anchura', .1, 100000)
    _finite(height, 'Altura', .1, 100000)
    rect = (rect[0], rect[1], rect[0]+width, rect[1]+height)
    if not chars:
        return [], {}, [], rect, 0
    y, paragraph, line_no = rect[1], 0, 0
    laid = []
    paragraphs = []
    chunk = []
    for character in chars:
        if character['char'] in ('\n', '\u2028'):
            paragraphs.append((chunk, character['char']))
            chunk = []
        else:
            chunk.append(character)
    paragraphs.append((chunk, ''))
    natural = []
    natural_paragraph = 0
    natural_first = True
    for chunk, break_kind in paragraphs:
        settings = _paragraph(request, natural_paragraph)
        _, measured = _shape_line(chunk, settings['direction'], settings['tab_stops'], settings['tab_interval'])
        natural.append(measured+settings['left_indent']+settings['right_indent']+
                       (settings['first_indent'] if natural_first else 0))
        natural_first = break_kind == '\n'
        if break_kind == '\n':
            natural_paragraph += 1
    if request.auto_width:
        width = max(.1, *natural)
        rect = (rect[0], rect[1], rect[0]+width, rect[3])
    first_line = True
    for chunk, break_kind in paragraphs:
        settings = _paragraph(request, paragraph)
        y += settings['space_before'] if first_line else 0
        remaining = list(chunk)
        while remaining or not chunk:
            indent = settings['left_indent'] + (settings['first_indent'] if first_line else 0)
            available = width-indent-settings['right_indent']
            if available <= 0:
                raise EditError('Los márgenes del párrafo superan la anchura disponible.')
            candidates, measured = _shape_line(remaining, settings.get('direction'), settings['tab_stops'], settings['tab_interval'])
            take = len(remaining)
            if measured > available+.035:
                # Binary search complete grapheme/ligature boundaries. Each
                # final line is shaped again so contextual joins are correct.
                low, high = 1, len(candidates)
                fitted = 0
                while low <= high:
                    middle = (low+high)//2
                    end_index = candidates[middle-1]['end']
                    prefix = [c for c in remaining if c['index'] < end_index]
                    _, proposed = _shape_line(prefix, settings.get('direction'), settings['tab_stops'], settings['tab_interval'])
                    if proposed <= available+.035:
                        fitted = len(prefix); low = middle+1
                    else:
                        high = middle-1
                if not fitted:
                    raise EditError('Un clúster de escritura supera la anchura disponible. Amplía el cuadro.')
                whitespace = [i+1 for i, c in enumerate(remaining[:fitted]) if c['char'] in (' ', '\t')]
                take = max(whitespace) if whitespace else fitted
                candidates, measured = _shape_line(remaining[:take], settings.get('direction'), settings['tab_stops'], settings['tab_interval'])
            line = remaining[:take]
            asc = max([c['face'].font.ascender*c['size'] for c in line] or [12.9])
            desc = max([-c['face'].font.descender*c['size'] for c in line] or [3.6])
            baseline = y+asc
            left = rect[0]+indent
            if settings['alignment'] == 'center':
                left += (available-measured)/2
            elif settings['alignment'] == 'right':
                left += available-measured
            visual = sorted(candidates, key=lambda c: c['visual'])
            spaces = sum(c['text'] == ' ' for c in visual)
            extra = (available-measured)/spaces if settings['alignment'] == 'justify' and spaces and take<len(remaining) else 0
            added = 0.
            for cluster in visual:
                cluster['x'] += added
                if cluster['text'] == ' ':
                    added += extra
            for cluster in candidates:
                cluster.update(origin=(left+cluster['x'], baseline),
                               end_origin=(left+cluster['x']+cluster['width'], baseline),
                               bbox=(left+cluster['x'], baseline-asc, left+cluster['x']+max(cluster['width'], .01), baseline+desc),
                               line=line_no)
                laid.append(cluster)
            y += settings['line_spacing'] or max(asc+desc, max([c['size']*1.2 for c in line] or [14.4]))
            line_no += 1
            first_line = False
            remaining = remaining[take:]
            if not remaining:
                break
        if break_kind == '\n':
            y += settings['space_after']
            paragraph += 1
            first_line = True
    bottom = max([c['bbox'][3] for c in laid] or [rect[1]])
    if bottom > rect[3]+.035 and not request.auto_height:
        raise EditError('El texto supera la altura disponible. Amplía el cuadro o cambia el interlineado.')
    if request.auto_height:
        rect = (rect[0], rect[1], rect[2], max(rect[3], bottom))
    return laid, faces, runs, rect, line_no


def _cmap(mapping):
    result = [b'/CIDInit /ProcSet findresource begin', b'12 dict begin', b'begincmap',
              b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def',
              b'/CMapName /PDFModderUnicode def', b'/CMapType 2 def',
              b'1 begincodespacerange', b'<0000> <FFFF>', b'endcodespacerange']
    items = sorted(mapping.items())
    for offset in range(0, len(items), 100):
        batch = items[offset:offset+100]
        result.append(f'{len(batch)} beginbfchar'.encode())
        for code, text in batch:
            result.append(f'<{code:04X}> <{text.encode("utf-16-be").hex().upper()}>'.encode())
        result.append(b'endbfchar')
    result.extend((b'endcmap', b'CMapName currentdict /CMap defineresource pop', b'end', b'end'))
    return b'\n'.join(result)


def _embed(doc, page_number, clusters, faces):
    """Assign distinct CIDs per (glyph, logical cluster) without mutating glyphs."""
    resources, evidence = {}, {}
    for key, face in faces.items():
        data = bytes(face.buffer or face.font.buffer)
        base = 'PMT' + key[:12]
        existing = {item[4] for item in doc[page_number].get_fonts()}
        name = base
        serial = 1
        while name in existing:
            name = base + str(serial)
            serial += 1
        resource = '/' + name
        xref = doc[page_number].insert_font(fontname=name, fontbuffer=data)
        kind, value = doc.xref_get_key(xref, 'DescendantFonts')
        descendant = int(value.strip('[] ').split()[0])
        gids = [0]
        mapping = {}
        entries = {}
        widths = []
        with TTFont(BytesIO(data), lazy=False) as tt:
            order = tt.getGlyphOrder()
            units = tt['head'].unitsPerEm
            metrics = tt['hmtx'].metrics
            for cluster in clusters:
                if cluster['style']['face_key'] != key:
                    continue
                for i, glyph in enumerate(cluster['glyphs']):
                    logical = cluster['text'] if i == 0 else ''
                    identity = (glyph['gid'], logical)
                    if identity not in entries:
                        cid = len(gids)
                        if cid > 65535:
                            raise EditError('La composición supera los códigos disponibles en un recurso de fuente.')
                        entries[identity] = cid
                        gids.append(glyph['gid'])
                        mapping[cid] = logical
                        widths.append((cid, metrics[order[glyph['gid']]][0]*1000/units))
                    glyph.update(cid=entries[identity], resource=resource,
                                 natural=metrics[order[glyph['gid']]][0]*1000/units)
        gid_xref = doc.get_new_xref()
        doc.update_object(gid_xref, '<<>>')
        doc.update_stream(gid_xref, b''.join(struct.pack('>H', gid) for gid in gids))
        cmap_xref = doc.get_new_xref()
        doc.update_object(cmap_xref, '<<>>')
        doc.update_stream(cmap_xref, _cmap(mapping))
        doc.xref_set_key(descendant, 'CIDToGIDMap', f'{gid_xref} 0 R')
        doc.xref_set_key(descendant, 'W', '['+' '.join(f'{code} [{width:.8f}]' for code, width in widths)+']')
        doc.xref_set_key(xref, 'ToUnicode', f'{cmap_xref} 0 R')
        resources[key] = dict(resource=resource, xref=xref, name=face.name, data=data)
        evidence[resource] = dict(face.metadata, source=face.source, shaping='HarfBuzz',
                                 cmap_verified=True, cluster_mapping=True)
    return resources, evidence


def _code_groups(show, operations):
    """One source code can decode to several virtual Unicode characters."""
    from .clipping import _raw, _strings
    from pypdf._cmap import _parse_to_unicode
    unit = 2 if show['font'].get('/Subtype') == '/Type0' and show['font'].get('/Encoding') == '/Identity-H' else 1
    if unit == 1 and show['font'].get('/Subtype') not in ('/TrueType', '/Type1'):
        raise EditError('La codificación de esta fuente no tiene límites de código verificables.')
    cmap, _ = _parse_to_unicode(show['font'])
    raw = b''.join(_raw(value) for _, value in _strings(*operations[show['operation']]))
    if len(raw) % unit:
        raise EditError('La codificación termina en un código incompleto.')
    groups, position = [], 0
    for offset in range(0, len(raw), unit):
        code = int.from_bytes(raw[offset:offset+unit], 'big')
        logical = cmap.get(chr(code))
        count = len(logical) if isinstance(logical, str) and logical else 1
        members = show['glyphs'][position:position+count]
        if len(members) != count:
            raise EditError('El mapa Unicode y los glifos físicos de esta selección no coinciden.')
        if isinstance(logical, str) and logical and ''.join(g.text for g in members) != logical.replace('\t', ' '):
            raise EditError('El mapa Unicode no coincide con los caracteres extraídos del código PDF.')
        groups.append((code, members))
        position += count
    if position != len(show['glyphs']):
        raise EditError('El mapa Unicode no cubre todos los caracteres de la selección.')
    return unit, groups


def _surviving_typography_records(record, selected):
    """Retain untouched cluster ranges without resurrecting deleted logical text."""
    remaining = []
    for cluster in record['clusters']:
        members = [record['glyphs'][i] for i in cluster['physical_indices']]
        if not any(_same(g, saved) for g in selected for saved in members):
            remaining.append(cluster)
    groups = []
    for cluster in remaining:
        if groups and not any(c['start'] >= groups[-1][-1]['end'] and c['end'] <= cluster['start']
                              for c in record['clusters'] if c not in remaining):
            groups[-1].append(cluster)
        else:
            groups.append([cluster])
    result = []
    for group in groups:
        begin, end = group[0]['start'], group[-1]['end']
        physical = sorted({i for c in group for i in c['physical_indices']})
        index_map = {old: new for new, old in enumerate(physical)}
        glyphs = [dict(record['glyphs'][i], physical_index=index_map[i]) for i in physical]
        runs = []
        offset = 0
        for run in record['runs']:
            stop = offset + len(run['text'])
            a, b = max(offset, begin), min(stop, end)
            if a < b:
                runs.append(dict(run, text=run['text'][a-offset:b-offset]))
            offset = stop
        result.append(dict(record, text=record['text'][begin:end], runs=runs, glyphs=glyphs,
                           clusters=[dict(c, start=c['start']-begin, end=c['end']-begin,
                                          physical_indices=[index_map[i] for i in c['physical_indices']]) for c in group],
                           rect=union(c['bbox'] for c in group),
                           paragraph_offset=record.get('paragraph_offset', 0)+begin))
    return result


def edit_shaped_pdf(data, request, resolver=None):
    """Native transaction for a shaped paragraph, validated against its source."""
    from .engine import extract_page, full_write, _safe_selection, _safe_native_consolidation
    from .clipping import CLIP_ISSUE, _raw, _serialize, operator_glyph_map
    from .clipped_layout import _state_at
    from .native_layout import _number, _compact_adjustments
    from .richtext import _validate, _drop_affected_groups
    from .validation import document_issues, trace_chars
    from .richmodels import RichTextRequest
    from .form_instances_v200 import isolate_selected_forms
    from .tagged import analyze, TaggedEdit, ref
    if isinstance(request, dict):
        request = RichTextRequest(**request)
    resolver = resolver or FontResolver()
    if request.revision and request.revision != sha256(data).hexdigest():
        raise EditError('El documento cambió desde la selección. Selecciona el texto de nuevo.')
    # Adding non-MCID ActualText wrappers to an existing structure would alter
    # its accessibility contract; keep that operation explicit and unavailable.
    if analyze(data) is not None:
        raise EditError('La composición avanzada de un PDF etiquetado requiere actualizar su estructura accesible; conserva la composición o trabaja sobre una copia sin etiquetas.')
    isolated = isolate_selected_forms(data, request) if request.ids else None
    if isolated is not None:
        local, current, evidence = isolated
        output, report = edit_shaped_pdf(local, current, resolver)
        report['form_isolation'] = evidence
        return output, report
    with fitz.open(stream=data, filetype='pdf') as doc:
        issues = document_issues(data, doc, operation="content")
        if issues:
            raise EditError('\n'.join(issues))
        model = extract_page(doc, request.page, data)
        selected = model.selected(request.ids)
        if len(selected) != len(set(request.ids)):
            raise EditError('La selección pertenece a otra revisión del documento.')
        if not selected:
            # A temporary anchor is removed through the same operator route.
            if not request.rect:
                raise EditError('Define el cuadro donde quieres añadir el texto.')
            doc[request.page].insert_text((request.rect[0], request.rect[1]+10), '|', fontsize=8, fontname='helv')
            anchored = doc.tobytes(garbage=0)
            anchor_model = extract_page(doc, request.page)
            anchor_ids = insertion_anchor_ids(model, anchor_model)
            output, report = edit_shaped_pdf(anchored, replace(request, ids=anchor_ids, revision=None), resolver)
            # Validate again against the actual input; the anchor cannot remain.
            planned = [Glyph(**g) for g in report['glyphs']]
            checked = _validate(data, output, request.page, model.glyphs+planned, planned, [], [], None)
            report.update(checked, source_regions=[], original='', added_text=True)
            return output, report
        clean = replace(model, issues=[issue for issue in model.issues if issue != CLIP_ISSUE])
        if clean.issues:
            raise EditError('\n'.join(clean.issues))
        # Native insertion keeps the original paint position. Owned clusters
        # have verified geometry even when extraction labels them bidi/virtual.
        owned_auxiliary = {g.id for record, actual in _verified_records(doc, request.page, model)
                           for saved, g in zip(record['glyphs'], actual) if saved.get('auxiliary') or g.text in ('\t','\u200c','\u200d')}
        if any(g.mode != 0 for g in selected):
            raise EditError('Selecciona texto visible para cambiar su composición.')
        rect = tuple(request.rect or union(g.bbox for g in selected))
        request = replace(request, rect=rect)
        clusters, faces, runs, rect, line_count = _prepare(doc, request, resolver)
        rotation = doc[request.page].rotation
        doc[request.page].set_rotation(0)
        page_matrix = doc[request.page].transformation_matrix
        bounds = fitz.Rect(0, 0, doc[request.page].cropbox.width, doc[request.page].cropbox.height)
        doc[request.page].set_rotation(rotation)
        old_records = _records(doc, request.page)
        resources, font_evidence = _embed(doc, request.page, clusters, faces)
        embedded_hashes = {key: sha256(doc.extract_font(value['xref'])[3]).hexdigest()
                           for key, value in resources.items()}
        prepared = doc.tobytes(garbage=0)
    reader, operations, shows, mapping = operator_glyph_map(data, request.page, model)
    byop = {show['operation']: show for show in shows}
    chosen = {g.id for g in selected}
    others = [g for g in model.glyphs if g.id not in chosen]
    logical_text = ''.join(run['text'] for run in runs)
    parent_id = 'P' + sha256(data + json.dumps(runs, sort_keys=True).encode()).hexdigest()[:20]
    parent_text = logical_text
    parent_offset = 0
    adopted = None
    owning_records = [r for r in old_records if any(_same(g, saved) for g in selected for saved in r['glyphs'])]
    if owning_records:
        identities = {r.get('paragraph_id') for r in owning_records}
        if len(identities) != 1 or None in identities or not all(
                any(_same(g, saved) for r in owning_records for saved in r['glyphs']) for g in selected):
            raise EditError('Selecciona un rango de un solo párrafo compuesto para conservar su texto lógico.')
        parent_id = next(iter(identities))
        all_tokens = [(r.get('paragraph_offset', 0)+c['start'], r.get('paragraph_offset', 0)+c['end'],
                       any(_same(g, r['glyphs'][i]) for i in c['physical_indices'] for g in selected))
                      for r in old_records if r.get('paragraph_id') == parent_id for c in r['clusters']]
        parent_offset = min(a for a, b, chosen_cluster in all_tokens if chosen_cluster)
        old_end = max(b for a, b, chosen_cluster in all_tokens if chosen_cluster)
        if any(a >= parent_offset and b <= old_end and not chosen_cluster for a, b, chosen_cluster in all_tokens):
            raise EditError('Selecciona un rango lógico continuo para recomponer el párrafo.')
        old_text = owning_records[0]['paragraph_text']
        parent_text = old_text[:parent_offset]+logical_text+old_text[old_end:]
        adopted = (parent_id, parent_offset, old_end, len(logical_text)-(old_end-parent_offset))
    first = selected[0]
    first_op = mapping[first.id]['operation']
    page_resources = reader.pages[request.page]['/Resources'].get_object()
    first_state = _state_at(operations, first_op, page_resources)
    matrix = first_state['matrix']
    if (first_state['unknown'] or first_state['size'] is None or first_state['size'] <= 0
            or abs(matrix.b)+abs(matrix.c) > 1e-6 or matrix.a <= 0 or matrix.d <= 0):
        raise EditError('La transformación original necesita el editor de objetos antes de recomponer el texto.')
    linear = first_state['ctm']*page_matrix
    inverse = ~linear
    clip = fitz.Rect(bounds)
    states = {}
    groups_byop = {}
    for op in {mapping[g.id]['operation'] for g in selected}:
        state = _state_at(operations, op, page_resources)
        states[op] = state
        if operations[op][1] not in (b'Tj', b'TJ') or byop[op]['render_mode'] != 0:
            raise EditError('El salto o modo de pintura original no puede aislarse para este párrafo.')
        if state['clip'] is not None:
            clip &= state['clip']*page_matrix
        unit, groups = _code_groups(byop[op], operations)
        for _, members in groups:
            if any(g.id in chosen for g in members) and not all(g.id in chosen for g in members):
                raise EditError('Selecciona el clúster completo: una ligadura o una marca comparte su código PDF con otros caracteres.')
        groups_byop[op] = (unit, groups)
    # A independently mapped Unicode code permits native RTL/ligature source
    # selection even when rawdict flags it as virtual/bidi. Own empty-Unicode
    # paint glyphs have additionally checked font bytes and positions above.
    verifiable_ids = {g.id for unit, groups in groups_byop.values() for code, members in groups
                      for g in members if g.font_xref and (g.text != '\ufffd' or g.id in owned_auxiliary)}
    safe_selected = [replace(g, reliable=True) if g.id in verifiable_ids else g for g in selected]
    with fitz.open(stream=data, filetype='pdf') as safety:
        _safe_selection(safety[request.page], clean, safe_selected, preserve_paint_order=True,
                        owned_auxiliary_ids=owned_auxiliary)
    for cluster in clusters:
        if not (bounds+(-.035, -.035, .035, .035)).contains(fitz.Rect(cluster['bbox'])) or not (clip+(-.035, -.035, .035, .035)).contains(fitz.Rect(cluster['bbox'])):
            raise EditError('El texto nuevo queda fuera de la página o del recorte original.')
        if not request.allow_overlap and any(intersects(cluster['bbox'], g.bbox, .12) for g in others):
            raise EditError('El texto se solapa con caracteres vecinos. Amplía el cuadro o permite el solapamiento.')
    # Compose each shaped glyph at its measured offset. TJ restores the text
    # cursor after every insertion so original codes after it remain untouched.
    insertion = []
    shaped_expected = []
    auxiliary = []
    paint_groups = []
    for cluster in sorted(clusters, key=lambda c: (c['line'], c['origin'][0])):
        style = cluster['style']
        key = (cluster['line'], style['face_key'], style['size'], style['color'])
        if paint_groups and paint_groups[-1][0] == key:
            paint_groups[-1][1].append(cluster)
        else:
            paint_groups.append((key, [cluster]))
    rise = 0.
    rise_stack = []
    for operands, operator in operations[:first_op]:
        if operator == b'q':
            rise_stack.append(rise)
        elif operator == b'Q':
            rise = rise_stack.pop()
        elif operator == b'Ts':
            rise = float(operands[0])
    for _, paint_group in paint_groups:
        style = paint_group[0]['style']
        group_origin = paint_group[0]['origin']
        delta = fitz.Point(group_origin[0]-first.origin[0], group_origin[1]-first.origin[1])*inverse-fitz.Point(0, 0)*inverse
        tf = first_state['size']*style['size']/first.size
        tz = 100*style['size']/(tf*matrix.a)
        insertion.extend([([], b'q'), ([_number(v) for v in (1, 0, 0, 1, delta.x, delta.y)], b'cm'),
                          ([NameObject(resources[style['face_key']]['resource']), _number(tf)], b'Tf'),
                          ([_number(0)], b'Tc'), ([_number(0)], b'Tw'), ([_number(tz)], b'Tz'),
                          ([_number(v) for v in style['color']], b'rg')])
        cursor = 0.
        for cluster in paint_group:
            face = resources[style['face_key']]
            insertion.append(([NameObject('/PMT'), DictionaryObject({NameObject('/ActualText'): TextStringObject(cluster['text'])})], b'BDC'))
            for i, glyph in enumerate(cluster['glyphs']):
                origin = (cluster['origin'][0]+glyph['x'], cluster['origin'][1]+glyph['y'])
                desired = origin[0]-group_origin[0]
                adjustment = -1000*(desired-cursor)/style['size']
                values = ArrayObject()
                if abs(adjustment) > 1e-8:
                    values.append(_number(adjustment))
                values.append(ByteStringObject(glyph['cid'].to_bytes(2, 'big')))
                insertion.extend([([_number(rise-glyph['y']/matrix.d)], b'Ts'), ([values], b'TJ')])
                cursor = desired+glyph['natural']*style['size']/1000
                shaped_expected.append(dict(gid=glyph['gid'], origin=origin, size=style['size'], font=face['name'],
                                            cluster=cluster, logical=cluster['text'] if i == 0 else '\ufffd',
                                            auxiliary=bool(i), font_sha256=embedded_hashes[style['face_key']], cid=glyph['cid'],
                                            logical_unicode=cluster['text'] if i == 0 else ''))
                if i:
                    auxiliary.append(origin)
            insertion.append(([], b'EMC'))
        insertion.extend([([ArrayObject([_number(cursor*1000/style['size'])])], b'TJ'), ([], b'Q')])
    replacements = {}
    for op, state in states.items():
        show = byop[op]
        unit, groups = groups_byop[op]
        args, operator = operations[op]
        values = args[0] if operator == b'TJ' else [args[0]]
        cursor = 0
        changed = ArrayObject()
        chunks = []
        def flush():
            nonlocal changed
            if changed:
                chunks.append(([_compact_adjustments(changed)], b'TJ'))
                changed = ArrayObject()
        for value in values:
            if isinstance(value, (str, bytes)):
                raw = _raw(value)
                for offset in range(0, len(raw), unit):
                    code, members = groups[cursor]
                    cursor += 1
                    if any(g.id == first.id for g in members):
                        flush()
                        chunks.extend(copy.deepcopy(insertion))
                    if members[0].id in chosen:
                        from .richtext import _source_width
                        step = _source_width(show['font'], code, members[0].text)+1000*state['tc']/state['size']
                        if unit == 1 and code == 32:
                            step += 1000*state['tw']/state['size']
                        changed.append(_number(-step))
                    else:
                        changed.append(ByteStringObject(raw[offset:offset+unit]))
            else:
                changed.append(copy.deepcopy(value))
        flush()
        replacements[op] = chunks
    remove_marks = set()
    mark_stack = []
    for index, (args, op) in enumerate(operations):
        if op in (b'BMC', b'BDC'):
            mark_stack.append((index, args, set()))
        elif op in (b'Tj', b'TJ'):
            for _, _, shows_in_mark in mark_stack:
                shows_in_mark.add(index)
        elif op == b'EMC' and mark_stack:
            start, args, shows_in_mark = mark_stack.pop()
            if args and str(args[0]) == '/PMT' and shows_in_mark & set(replacements):
                remove_marks.update((start, index))
            if (adopted and not parent_text and args and str(args[0]) == '/PMParagraph'
                    and str(args[1].get('/PDFModderID')) == parent_id):
                remove_marks.update((start, index))
    if adopted:
        for index, (args, op) in enumerate(operations):
            if (op == b'BDC' and args and str(args[0]) == '/PMParagraph'
                    and str(args[1].get('/PDFModderID')) == parent_id):
                changed = copy.deepcopy(args[1])
                changed[NameObject('/ActualText')] = TextStringObject(parent_text)
                operations[index] = ([args[0], changed], op)
    changed_ops = [item for op, original in enumerate(operations) if op not in remove_marks
                   for item in replacements.get(op, [copy.deepcopy(original)])]
    with fitz.open(stream=prepared, filetype='pdf') as doc:
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, _serialize(changed_ops))
        doc[request.page].set_contents(stream)
        # Independent geometry/glyph check is performed before attaching the
        # trusted metadata, using raw MuPDF glyph IDs and HarfBuzz's positions.
        traces = [(span, ch) for span in doc[request.page].get_texttrace() for ch in span['chars']]
        new_chars = []
        used = set()
        physical_index = 0
        cluster_indices = {id(c): [] for c in clusters}
        saved_evidence = []
        for expected in shaped_expected:
            matches = [(j, span, ch) for j, (span, ch) in enumerate(traces)
                       if j not in used and ch[1] == expected['gid']
                       and all(abs(a-b) < .035 for a, b in zip(ch[2], expected['origin']))
                       and abs(span['size']-expected['size']) < .002]
            if len(matches) != 1:
                raise EditError('Validación tipográfica: el glifo guardado no coincide con la forma o posición compuesta.')
            j, span, ch = matches[0]
            # A multi-Unicode CID creates one real glyph followed by virtual
            # entries. These characters are searchable and survive reopening.
            count = len(expected['logical'])
            batch = traces[j:j+count]
            if ''.join(chr(c[0]) for _, c in batch) != expected['logical'].replace('\t', ' '):
                raise EditError('Validación tipográfica: el mapa Unicode no conserva el texto del clúster.')
            for k, (sp, char) in enumerate(batch):
                used.add(j+k)
                bbox = tuple(char[3])
                new_chars.append(Glyph(-1, chr(char[0]), tuple(char[2]), bbox, bbox,
                                       sp['font'], float(sp['size']), tuple(sp['color']), float(sp['opacity']),
                                       first.block, expected['cluster']['line'], 0, tuple(sp['dir']),
                                       int(sp['type']), sp.get('layer', ''), sp['seqno'], True))
                saved_evidence.append(dict(gid=char[1], auxiliary=expected['auxiliary'],
                                           font_sha256=expected['font_sha256'],cid=expected['cid'],
                                           paint_gid=expected['gid'],logical_unicode=expected['logical_unicode']))
                cluster_indices[id(expected['cluster'])].append(physical_index)
                physical_index += 1
        _safe_native_consolidation(doc[request.page], selected, new_chars)
        # Old source text cannot survive as stale logical metadata.
        keep = [survivor for record in old_records for survivor in _surviving_typography_records(record, selected)]
        if adopted:
            for survivor in keep:
                if survivor.get('paragraph_id') == parent_id:
                    survivor['paragraph_text'] = parent_text
                    if survivor.get('paragraph_offset', 0) >= adopted[2]:
                        survivor['paragraph_offset'] += adopted[3]
        saved_clusters = []
        for cluster in clusters:
            indices = cluster_indices[id(cluster)]
            saved_clusters.append(dict(start=cluster['start'], end=cluster['end'], text=cluster['text'],
                                       origin=cluster['origin'], end_origin=cluster['end_origin'],
                                       bbox=union([new_chars[i].bbox for i in indices]+[cluster['bbox']]),
                                       line=cluster['line'], rtl=cluster['rtl'], physical_indices=indices))
        record = dict(text=''.join(run['text'] for run in runs), runs=runs, rect=rect,
                      paragraphs=request.paragraphs, block=first.block,
                      glyphs=[dict(asdict(g), physical_index=i, **saved_evidence[i]) for i, g in enumerate(new_chars)],
                      clusters=saved_clusters, fonts=font_evidence,
                      paragraph_id=parent_id, paragraph_text=parent_text, paragraph_offset=parent_offset, paragraph_tag=False)
        if new_chars:
            keep.append(record)
        doc.xref_set_key(doc[request.page].xref, KEY,
                         fitz.get_pdf_str(json.dumps(dict(schema=SCHEMA, records=keep), ensure_ascii=True)))
        removed = _drop_affected_groups(doc, request.page, selected)
        output = full_write(doc)
    # Preserve the document's accessible structure if there is one. This
    # transaction does not invent tags or silently replace an ActualText value.
    structure = analyze(data)
    tagged = TaggedEdit(structure, request.page, model, selected, new_chars, selected, True) if structure else None
    if tagged:
        with fitz.open(stream=output, filetype='pdf') as doc:
            # Reuse the tagged transaction's checked node/marker updates.
            for path, text in tagged.actual_updates.items():
                doc.xref_set_key(ref(structure.nodes[path])[0], 'ActualText', fitz.get_pdf_str(text))
            if tagged.marker_updates:
                raise EditError('Este párrafo tiene ActualText marcado; requiere conservar su propiedad antes de recomponerlo.')
            output = full_write(doc)
    report = _validate(data, output, request.page, others+new_chars, selected+new_chars, [], [],
                       tagged.expected if tagged else None)
    if tagged:
        report['accessibility'] = tagged.validate(output)
    with fitz.open(stream=output, filetype='pdf') as doc:
        payload = selection_payload(output, request.page,
                                    [g.id for g in extract_page(doc, request.page, output).glyphs
                                     if any(_same(g, saved) for saved in record['glyphs'])], resolver)
    report.update(page=request.page, rect=rect, area_width=rect[2]-rect[0], area_height=rect[3]-rect[1],
                  auto_width=request.auto_width, auto_height=request.auto_height,
                  source_regions=[g.bbox for g in selected], destination_regions=[c['bbox'] for c in saved_clusters],
                  glyphs=[asdict(g) for g in new_chars], carets=payload['carets'] if payload else [],
                  clusters=saved_clusters, line_count=line_count, fonts=font_evidence,
                  original=model.text(request.ids), replacement=record['text'], rich_text=True,
                  typography=True, shaping_engine='HarfBuzz', bidi_engine='Unicode bidi',
                  auxiliary_glyphs=len(auxiliary), removed_groups=removed)
    return output, report


def move_shaped_pdf(data, request):
    """Translate verified paint codes without reshaping or changing neighbours."""
    from .engine import extract_page, full_write, _safe_selection
    from .clipping import CLIP_ISSUE, _serialize, operator_glyph_map
    from .clipped_layout import _state_at
    from .native_layout import _number
    from .richtext import _validate, _drop_affected_groups
    from .validation import document_issues
    if request.revision and request.revision != sha256(data).hexdigest():
        raise EditError('La selección está desactualizada. Selecciona el texto de nuevo.')
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (request.dx, request.dy)):
        raise EditError('El desplazamiento debe contener coordenadas finitas.')
    with fitz.open(stream=data, filetype='pdf') as doc:
        if not _records(doc, request.page):
            return None
        model = extract_page(doc, request.page, data)
        selected = model.selected(request.ids)
        verified = _verified_records(doc, request.page, model)
        owned = {g.id for _, actual in verified for g in actual}
        if not selected or not {g.id for g in selected} <= owned:
            return None
        chosen = {g.id for g in selected}
        for record, actual in verified:
            index_ids = {saved['physical_index']: g.id for saved, g in zip(record['glyphs'], actual)}
            for cluster in record['clusters']:
                members = {index_ids[i] for i in cluster['physical_indices']}
                if chosen & members and not members <= chosen:
                    raise EditError('Selecciona el clúster completo para mover una ligadura o sus marcas.')
        issues = document_issues(data, doc, operation='content')
        if issues:
            raise EditError('\n'.join(issues))
        clean = replace(model, issues=[i for i in model.issues if i != CLIP_ISSUE])
        auxiliary = {g.id for record, actual in verified for saved, g in zip(record['glyphs'], actual) if saved.get('auxiliary') or g.text in ('\t','\u200c','\u200d')}
        dx, dy = request.dx, request.dy
        def shifted(rect):
            return tuple(v+(dx if i%2 == 0 else dy) for i, v in enumerate(rect))
        planned = [replace(g, origin=shifted(g.origin), bbox=shifted(g.bbox), trace_bbox=shifted(g.trace_bbox)) for g in selected]
        _safe_selection(doc[request.page], clean, selected, preserve_paint_order=True, owned_auxiliary_ids=auxiliary)
        _safe_selection(doc[request.page], clean, planned, preserve_paint_order=True, owned_auxiliary_ids=auxiliary)
        rotation = doc[request.page].rotation
        doc[request.page].set_rotation(0)
        matrix = doc[request.page].transformation_matrix
        bounds = fitz.Rect(0, 0, doc[request.page].cropbox.width, doc[request.page].cropbox.height)
        doc[request.page].set_rotation(rotation)
    others = [g for g in model.glyphs if g.id not in chosen]
    if not request.allow_overlap and any(intersects(g.bbox, n.bbox, .12) for g in planned for n in others):
        raise EditError('El texto movido se solapa con un vecino. Elige otra posición o permite el solapamiento.')
    reader, operations, shows, mapping = operator_glyph_map(data, request.page, model)
    resources = reader.pages[request.page]['/Resources'].get_object()
    target_ops = {mapping[g.id]['operation'] for g in selected}
    replacements = {}
    for show in shows:
        index = show['operation']
        if index not in target_ops:
            continue
        _code_groups(show, operations)
        if not all(g.id in chosen for g in show['glyphs']):
            raise EditError('El operador mezcla texto ajeno al clúster. Selecciona un fragmento completo.')
        state = _state_at(operations, index, resources)
        linear = state['ctm']*matrix
        if state['unknown'] or abs(linear.a*linear.d-linear.b*linear.c) < 1e-10:
            raise EditError('La transformación o el recorte de este clúster no pueden verificarse.')
        clip = state['clip']*matrix if state['clip'] is not None else bounds
        for g in planned:
            if g.id in {s.id for s in show['glyphs']} and (not bounds.contains(fitz.Rect(g.bbox)) or not (clip+(-.035,-.035,.035,.035)).contains(fitz.Rect(g.bbox))):
                raise EditError('El texto movido queda fuera de la página o de su recorte.')
        inverse = ~linear
        delta = fitz.Point(dx, dy)*inverse-fitz.Point(0, 0)*inverse
        replacements[index] = [([], b'q'), ([_number(v) for v in (1,0,0,1,delta.x,delta.y)], b'cm'),
                               copy.deepcopy(operations[index]), ([], b'Q')]
    changed = [item for i, original in enumerate(operations) for item in replacements.get(i, [copy.deepcopy(original)])]
    with fitz.open(stream=data, filetype='pdf') as doc:
        records = _records(doc, request.page)
        for record in records:
            affected = set()
            for saved in record['glyphs']:
                if any(_same(g, saved) for g in selected):
                    affected.add(saved['physical_index'])
                    for field in ('origin', 'bbox', 'trace_bbox'):
                        saved[field] = shifted(saved[field])
            for cluster in record['clusters']:
                if affected.intersection(cluster['physical_indices']):
                    for field in ('origin', 'end_origin', 'bbox'):
                        cluster[field] = shifted(cluster[field])
            if affected:
                record['rect'] = shifted(record['rect']) if len(affected) == len(record['glyphs']) else union(c['bbox'] for c in record['clusters'])
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, _serialize(changed))
        doc[request.page].set_contents(stream)
        doc.xref_set_key(doc[request.page].xref, KEY, fitz.get_pdf_str(json.dumps(dict(schema=SCHEMA, records=records), ensure_ascii=True)))
        removed = _drop_affected_groups(doc, request.page, selected)
        output = full_write(doc)
    report = _validate(data, output, request.page, others+planned, selected+planned, [], [], None)
    report.update(page=request.page, typography=True, rich_text_move=True,
                  source_regions=[g.bbox for g in selected], destination_regions=[g.bbox for g in planned],
                  original=model.text(request.ids), replacement=model.text(request.ids),
                  removed_groups=removed, glyphs=[asdict(g) for g in planned])
    return output, report
