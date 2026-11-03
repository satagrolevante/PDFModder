"""Guards for native clipped-text movement without rewriting accessible text.

The text's marked-content wrappers and the structure tree stay untouched. The
visual position may change; MCID membership and logical character order may not.
An artifact remains an artifact, including its pagination properties.
"""
from io import BytesIO

import pymupdf as fitz
from pypdf.generic import ContentStream

from .model import EditError
from .tagged import analyze_readonly, assert_structure, obj


class TaggedNativeMove:
    def __init__(self, data, page, model, selected, planned=None):
        self.structure = analyze_readonly(data)
        self.page = page
        self.model = model
        self.contexts = self.structure.glyph_contexts(page, model)
        self.affected = {self.contexts[g.id] for g in selected}
        # Use the same bounded layout proof as native text editing. Recognized
        # styles remain intact; only an exclusively textual, tight BBox may
        # grow. Shared classes are preserved through a direct private override.
        # Artifacts have no structure owner and retain the separate checks below.
        tagged_selected = [g for g in selected if self.contexts[g.id] is not None]
        tagged_planned = [g for g in (selected if planned is None else planned)
                          if self.contexts[g.id] is not None]
        self.layout_plan = None
        if tagged_selected:
            from .tagged import TaggedEdit
            self.layout_plan = TaggedEdit(self.structure, page, model, tagged_selected,
                tagged_planned, tagged_selected, False, native_inplace=True)
        self.expected = (self.layout_plan.expected if self.layout_plan is not None
                         else self.structure.semantic())
        for mcid in self.affected - {None}:
            mark = self.structure.marks[page][mcid]
            if '/BBox' in mark.resolved:
                raise EditError('PDF etiquetado: la marca seleccionada tiene una caja semántica que todavía no se actualiza al moverla.')

    def apply_updates(self, document):
        if self.layout_plan is not None:
            self.layout_plan.apply_updates(document)

    def validate(self, output):
        from .engine import extract_page
        # The guard already holds its independently checked source and private
        # expected snapshot. Re-reading it here would evict the checked final
        # candidate and rebuild both complete trees for a second time.
        current = analyze_readonly(output)
        if current is None or current.semantic()!=self.expected:
            raise EditError('PDF etiquetado: el movimiento alteró etiquetas, relaciones u otras propiedades accesibles.')
        with fitz.open(stream=output, filetype='pdf') as doc:
            model = extract_page(doc, self.page)
        contexts = current.glyph_contexts(self.page, model)
        # The normal movement verifier already checks every character, its
        # destination, typography and neighbours. Here additionally enforce
        # assignment and *order* for each logical marked-content item.
        for mcid in self.structure.marks[self.page]:
            before = ''.join(g.text for g in self.model.glyphs if self.contexts[g.id] == mcid)
            after = ''.join(g.text for g in model.glyphs if contexts[g.id] == mcid)
            if before != after:
                raise EditError('PDF etiquetado: el traslado cambiaría la asociación o el orden de lectura dentro de una etiqueta. Selecciona su tramo completo.')
        old_artifacts = sorted(g.text for g in self.model.glyphs if self.contexts[g.id] is None)
        new_artifacts = sorted(g.text for g in model.glyphs if contexts[g.id] is None)
        if old_artifacts != new_artifacts:
            raise EditError('PDF etiquetado: el traslado alteró la clasificación del contenido de cabecera o artefacto.')
        return {'verified': True, 'structure_preserved': True, 'logical_text_verified': True,
                'reading_order_preserved': True, 'mcids': sorted(self.affected - {None}),
                'artifact_preserved': None in self.affected,
                'layout_attribute_updates': (len(self.layout_plan.layout_updates)
                                             if self.layout_plan is not None else 0),
                'scope': 'MCID, ParentTree, etiquetas y texto lógico conservados; no certificación PDF/UA.'}


def clip_scope(operations, target, destinations, resources, page_matrix, page_bounds, allowed):
    """Find a text-only scope whose inherited clip permits the destination.

    Unlike the older one-show path, this accepts repeated cell rectangles and
    neighbouring shows inside the same q/Q. The clone contains selected codes
    only; all other text advances still execute. No BDC/EMC is cloned, so MCID
    identities never duplicate and the enclosing semantic wrapper is retained.
    """
    from .clipped_layout import _state_at
    stack, scopes = [], []
    for index, (_, operator) in enumerate(operations):
        if operator == b'q':
            stack.append(index)
        elif operator == b'Q':
            if not stack:
                raise EditError('El ámbito gráfico contiene un cierre sin apertura.')
            begin = stack.pop()
            if begin < target < index:
                scopes.append((begin, index))
    for begin, end in sorted(scopes, reverse=True):
        ops = [op for _, op in operations[begin:end+1]]
        clips = sum(op in (b'W', b'W*') for op in ops)
        if (not clips or any(op not in allowed for op in ops)
                or ops.count(b're') != clips or ops.count(b'BT') != ops.count(b'ET')
                or ops.count(b'BT') != ops.count(b'Tm')):
            continue
        if any(ops[i+1:i+3] not in ([b'W', b'n'], [b'W*', b'n'])
               for i, op in enumerate(ops) if op == b're'):
            continue
        parent = _state_at(operations, begin, resources)
        inherited = parent['clip'] * page_matrix if parent['clip'] is not None else page_bounds
        if parent['unknown'] or any(not inherited.contains(fitz.Rect(g.bbox)) for g in destinations):
            continue
        return begin, end
    raise EditError('PDF etiquetado: no hay un ámbito de recorte aislable sin duplicar etiquetas, cambiar el orden de lectura o modificar otros gráficos.')
