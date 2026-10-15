"""Remove verified fill/stroke code pairs without reconstructing their paint.

MuPDF exposes Tr=2 twice, once per paint, while PDF stores one character code.
A discarded Tr=0 probe binds that single code; the exported stream retains
every original rendering mode, graphics state, clip and neighbouring cursor.
Replacement, recolouring and reflow remain on their existing guarded routes.
"""
from dataclasses import replace
from io import BytesIO
import copy
import hashlib
import math
import time

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, NumberObject, NameObject, TextStringObject

from .model import EditError, intersects, union


def _pure_deletion(request):
    if hasattr(request, 'runs'):
        return not any(str(run.get('text', '')) for run in request.runs)
    return (request.text == '' and not request.dx and not request.dy
            and getattr(request, 'ocr_mode', 'visible') == 'visible')


def _paired_geometry(fill, stroke):
    return (fill.text == stroke.text and fill.font == stroke.font
            and abs(fill.size-stroke.size) < .001
            and fill.direction == stroke.direction and fill.layer == stroke.layer
            and all(abs(a-b) < .001 for a, b in zip(fill.origin, stroke.origin))
            and all(abs(a-b) < .001 for a, b in zip(fill.bbox, stroke.bbox)))


def try_delete_paired_text(data, request, model=None):
    """Return a validated deletion, or None when no selected code uses Tr=2.

    Accept either panel/Supr EditRequest or an empty RichTextRequest. Selecting
    either paint removes its proven companion. Ordinary visible text may also
    be deleted in the same request, but standalone Tr=1, OCR, text clips and
    unbound/ambiguous paint pairs never acquire this authorization.
    """
    if not request.ids or not _pure_deletion(request):
        return None
    from .engine import extract_page, full_write, _safe_selection
    from .clipping import CLIP_ISSUE, _raw, _serialize, _signature, _strings, operator_glyph_map
    from .clipped_layout import _state_at, _assert_typography
    from .native_layout import _compact_adjustments, _number
    from .richtext import _unit, _source_width, _validate, _drop_affected_groups, _read_metadata, _match
    from .tagged import analyze_readonly, TaggedEdit
    from .tagged_artifacts import verified_artifact_selection
    from .validation import document_issues

    started = time.perf_counter()
    digest = hashlib.sha256(data).hexdigest()
    if request.revision and request.revision != digest:
        raise EditError('El documento cambió desde la selección. Selecciona el texto de nuevo.')
    with fitz.open(stream=data, filetype='pdf') as source:
        model = (model if model is not None and model.number == request.page
                 and model.revision == digest else extract_page(source, request.page, data))
        selected = model.selected(request.ids)
        if len(selected) != len(set(request.ids)):
            raise EditError('La selección pertenece a una revisión anterior.')
        if not any(g.mode == 1 for g in model.glyphs):
            return None
        reader, operations, shows, mapping = operator_glyph_map(data, request.page, model)
        selected_modes = {mapping.get(g.id, {}).get('render_mode') for g in selected}
        if 2 not in selected_modes:
            return None
        if selected_modes - {0, 2}:
            raise EditError('El borrado mezcla texto trazado, invisible o recortado que no puede aislarse conjuntamente.')
        issues = document_issues(data, source, operation='content')
        if issues:
            raise EditError('\n'.join(issues))

        pairs, omitted = {}, set()
        for show in shows:
            if show['render_mode'] != 2:
                continue
            args, operator = operations[show['operation']]
            if operator not in (b'Tj', b'TJ'):
                raise EditError('El texto con contorno utiliza un salto no compatible con su borrado nativo.')
            strings = [_raw(value) for _, value in _strings(args, operator)]
            # Empty SHOWs may still contain TJ cursor adjustments. They own no
            # character pair and stay byte-for-byte equivalent in changed_ops.
            # Never treat missing glyphs as evidence that nonempty codes are inert.
            if not show['glyphs'] and not any(strings):
                continue
            fill = [g for g in show['glyphs'] if g.mode == 0]
            stroke = [g for g in show['glyphs'] if g.mode == 1]
            if (not fill or len(fill) != len(stroke)
                    or len(show['glyphs']) != 2*len(fill)
                    or any(not _paired_geometry(a, b) for a, b in zip(fill, stroke))):
                raise EditError('No se pudo verificar cada pareja de relleno y contorno del texto.')
            unit = _unit(show)
            if (any(len(value) % unit for value in strings)
                    or sum(map(len, strings)) != unit*len(fill)):
                raise EditError('No hay correspondencia uno a uno entre códigos, relleno y contorno.')
            for a, b in zip(fill, stroke):
                pairs[a.id] = (a.id, b.id)
                pairs[b.id] = (a.id, b.id)
                omitted.add(b.id)

        removed = set(request.ids)
        for glyph in selected:
            if mapping[glyph.id]['render_mode'] == 2:
                removed.update(pairs[glyph.id])
        selected = model.selected(removed)
        if any(g.opacity <= 0 for g in selected):
            raise EditError('El borrado del contorno requiere que ambos componentes sean visibles.')
        if any(g.mode == 3 and any(intersects(g.bbox, old.bbox) for old in selected)
               for g in model.glyphs if g.id not in removed):
            raise EditError('La selección tiene OCR invisible superpuesto; corrige esa capa por separado.')
        # The paired source proof owns only this local safety view. Tr=2 and
        # every original glyph mode remain untouched in the actual output.
        clean = replace(model, issues=[issue for issue in model.issues if issue != CLIP_ISSUE])
        _safe_selection(source[request.page], clean,
                        [replace(g, mode=0) if g.mode == 1 else g for g in selected],
                        preserve_paint_order=True)
        if any(_match(g, saved) for record in _read_metadata(source, request.page)
               for saved in record.get('glyphs', []) for g in selected):
            raise EditError('El texto con contorno contiene formato propio del editor que necesita actualización conjunta.')

    primary = replace(model, glyphs=[g for g in model.glyphs if g.id not in omitted])
    probe_ops = [([NumberObject(0)] if op == b'Tr' and int(args[0]) == 2
                  else copy.deepcopy(args), op) for args, op in operations]
    with fitz.open(stream=data, filetype='pdf') as probe:
        stream = probe.get_new_xref()
        probe.update_object(stream, '<<>>')
        probe.update_stream(stream, _serialize(probe_ops))
        probe[request.page].set_contents(stream)
        probe_data = probe.tobytes(garbage=0, deflate=False, no_new_id=True)
    _, mapped_ops, primary_shows, primary_mapping = operator_glyph_map(probe_data, request.page, primary)
    if len(mapped_ops) != len(operations):
        raise EditError('El sondeo del contorno cambió la secuencia de operadores.')
    for original, probed in zip(operations, mapped_ops):
        if original[1] != probed[1] or (original[1] != b'Tr' and _signature(original[0]) != _signature(probed[0])):
            raise EditError('El sondeo del contorno cambió operadores ajenos al modo de pintura.')
    for glyph in primary.glyphs:
        original = mapping.get(glyph.id)
        probed = primary_mapping.get(glyph.id)
        if original is not None and (probed is None or
                (original['operation'], original['font_resource'], original['font_xref']) !=
                (probed['operation'], probed['font_resource'], probed['font_xref'])):
            raise EditError('El sondeo cambió la pertenencia de un carácter a su operador o fuente.')

    structure = analyze_readonly(data)
    if structure is not None:
        contexts = structure.glyph_contexts(request.page, model)
        if any(contexts[a] != contexts[b] for a, b in pairs.values()):
            raise EditError('El relleno y el contorno no pertenecen a la misma etiqueta accesible.')
    artifact = structure is not None and verified_artifact_selection(
        structure, request.page, list(removed), mapping, operations, model=model, planned=[])
    tagged = (TaggedEdit(structure, request.page, model, selected, [], selected,
                         True, native_inplace=True)
              if structure is not None and not artifact else None)

    resources = reader.pages[request.page]['/Resources'].get_object()
    changed_ops = copy.deepcopy(operations)
    changed_show_ids = set()
    primary_removed = removed - omitted
    byop = {show['operation']: show for show in primary_shows}
    for op in {primary_mapping[g]['operation'] for g in primary_removed}:
        show = byop[op]
        args, operator = operations[op]
        if operator not in (b'Tj', b'TJ'):
            raise EditError('El operador de texto usa un salto no compatible con el borrado de sus códigos.')
        state = _state_at(operations, op, resources)
        if (state['size'] is None or not math.isfinite(state['size']) or state['size'] <= 0
                or any(not math.isfinite(state[key]) for key in ('tc', 'tw', 'tz'))):
            raise EditError('El avance del texto con contorno no se puede verificar.')
        unit = _unit(show)
        source_array = args[0] if operator == b'TJ' else [args[0]]
        strings = [_raw(value) for value in source_array if isinstance(value, (str, bytes))]
        if (any(len(value) % unit for value in strings)
                or sum(map(len, strings)) != unit*len(show['glyphs'])):
            raise EditError('No se pudieron aislar los códigos del texto con contorno.')
        changed, position = ArrayObject(), 0
        for value in source_array:
            if isinstance(value, (str, bytes)):
                raw = _raw(value)
                for offset in range(0, len(raw), unit):
                    glyph = show['glyphs'][position]
                    code = int.from_bytes(raw[offset:offset+unit], 'big')
                    if glyph.id in primary_removed:
                        step = (_source_width(show['font'], code, glyph.text)
                                + 1000*state['tc']/state['size']
                                + (1000*state['tw']/state['size'] if unit == 1 and code == 32 else 0))
                        changed.append(_number(-step))
                    else:
                        changed.append(ByteStringObject(raw[offset:offset+unit]))
                    position += 1
            else:
                changed.append(copy.deepcopy(value))
        changed_ops[op] = ([_compact_adjustments(changed)], b'TJ')
        changed_show_ids.add(op)
    if tagged:
        for mcid, text in tagged.marker_updates.items():
            mark = structure.marks[request.page][mcid]
            props = copy.deepcopy(mark.resolved)
            props[NameObject('/ActualText')] = TextStringObject(text)
            changed_ops[mark.start] = ([changed_ops[mark.start][0][0], props], b'BDC')
    others = [g for g in model.glyphs if g.id not in removed]
    with fitz.open(stream=data, filetype='pdf') as output_doc:
        stream = output_doc.get_new_xref()
        output_doc.update_object(stream, '<<>>')
        output_doc.update_stream(stream, _serialize(changed_ops))
        output_doc[request.page].set_contents(stream)
        removed_groups = _drop_affected_groups(output_doc, request.page, selected)
        if tagged:
            tagged.apply_updates(output_doc)
        output = full_write(output_doc)
    reopened = PdfReader(BytesIO(output), strict=True)
    final_ops = ContentStream(reopened.pages[request.page].get_contents(), reopened).operations
    if len(final_ops) != len(changed_ops) or any(
            op != final_op or _signature(args) != _signature(final_args)
            for (args, op), (final_args, final_op) in zip(changed_ops, final_ops)):
        raise EditError('El guardado cambió los operadores verificados del borrado con contorno.')
    if _signature(reader.pages[request.page]['/Resources']) != _signature(reopened.pages[request.page]['/Resources']):
        raise EditError('El borrado alteró recursos originales de la página.')
    _assert_typography(output, request.page, others)
    report = _validate(data, output, request.page, others, selected, [], [],
                       tagged.expected if tagged else None)
    if tagged:
        report['accessibility'] = tagged.validate(output)
    bounds = union(g.bbox for g in selected)
    report.update(page=request.page, rect=bounds, area_width=bounds[2]-bounds[0],
                  area_height=bounds[3]-bounds[1], source_regions=[g.bbox for g in selected],
                  destination_regions=[], glyphs=[], carets=[], replacement='',
                  original=primary.text(primary_removed), rich_text=True,
                  native_paired_deletion=True, original_render_modes_preserved=True,
                  paired_characters_deleted=len(removed & omitted),
                  selected_characters=len(primary_removed), removed_paint_glyphs=len(removed),
                  untouched_characters=len(others), source_sha256=digest,
                  font_resources_unchanged=True, operators_preserved=True,
                  changed_show_count=len(changed_show_ids), fonts={}, line_count=0,
                  elapsed_seconds=round(time.perf_counter()-started, 3))
    if removed_groups:
        report['removed_groups'] = removed_groups
    return output, report
