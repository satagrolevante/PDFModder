"""Edit existing unmarked text without assigning it to the accessible tree.

Some PDF exporters append plain headers/footers to otherwise tagged pages.
Only verified native source SHOWs outside *every* marked-content scope are
eligible here. Artifacts and semantic wrappers keep their own editing guards.
"""
import hashlib

import pymupdf as fitz

from .draft_control_v305 import checkpoint
from .tagged import SHOW, TaggedEdit, analyze_readonly, fail


def _bare_shows(operations):
    stack=[]
    result=set()
    for index, (_, operator) in enumerate(operations):
        if index % 256 == 0:checkpoint()
        if operator in (b'BMC', b'BDC'):
            stack.append(index)
        elif operator == b'EMC':
            if not stack:fail('hay un cierre EMC sin apertura.')
            stack.pop()
        elif operator in SHOW and not stack:
            result.add(index)
    if stack:fail('hay contenido marcado sin cerrar.')
    return result


def verified_unmarked_selection(structure, page, model, selected, operations, mapping):
    """Bind selected glyphs to actual unmarked SHOWs in this exact revision."""
    from .clipping import _signature
    if (structure is None or not selected or page != model.number
            or model.revision != hashlib.sha256(structure.data).hexdigest()):
        return False
    original=structure.operations[page]
    if (len(operations) != len(original)
            or any(_signature(a) != _signature(b) for a,b in zip(operations, original))):
        return False
    bare=_bare_shows(original)
    return (len({g.id for g in selected}) == len(selected)
            and all(g.id in mapping and mapping[g.id]['operation'] in bare for g in selected))


def native_text_plan(structure, page, model, selected, planned, operations, mapping,
                     *, decoration_policy=None, source_data=None,replacement_text=None):
    """Share one source-scope decision across native edit/delete/composition."""
    if structure is None:
        from .marked_text_v324 import native_marked_plan
        return (native_marked_plan(source_data,page,model,selected,planned,operations,mapping,
                                   replacement_text=replacement_text)
                if source_data is not None else None)
    if verified_unmarked_selection(structure, page, model, selected, operations, mapping):
        return UnmarkedNativeEdit(structure, page, model, selected, planned, operations, mapping)
    from .tagged_artifacts import verified_artifact_selection
    if verified_artifact_selection(structure, page, [g.id for g in selected], mapping,
                                   operations, model=model, planned=planned):
        return None
    return TaggedEdit(structure, page, model, selected, planned, selected, True,
                      native_inplace=True, decoration_policy=decoration_policy)


def _assert_membership(expected, actual):
    """Match real characters and origins, including duplicate/overlapping text."""
    if len(expected) != len(actual):
        fail('la edición cambió la asociación entre texto sin etiqueta y contenido marcado.')
    by_char={}
    for glyph in actual:by_char.setdefault(glyph.text, []).append(glyph.origin)
    for index,glyph in enumerate(expected):
        if index % 256 == 0:checkpoint()
        candidates=by_char.get(glyph.text, [])
        match=next((i for i,p in enumerate(candidates)
                    if all(abs(a-b)<=.035 for a,b in zip(p,glyph.origin))), None)
        if match is None:
            fail('la edición cambió la pertenencia o posición de texto ajeno a su ámbito.')
        candidates.pop(match)


class UnmarkedNativeEdit:
    """Final guard; the caller still validates all graphics, glyphs and bytes."""
    def __init__(self, structure, page, model, selected, planned, operations, mapping):
        self.structure=structure
        self.page=page
        self.model=model
        self.expected=structure.semantic()
        self.marker_updates={}
        self.actual_updates={}
        self.layout_updates={}
        self.affected=set()
        self.selected=selected
        self.contexts=structure.glyph_contexts(page, model)
        bare=_bare_shows(operations)
        removed={g.id for g in selected}
        self.expected_unmarked=[g for g in model.glyphs
            if mapping.get(g.id, {}).get('operation') in bare and g.id not in removed]+list(planned)

    def apply_updates(self, document):
        # Existing unmarked text stays unmarked. No tree/ParentTree changes.
        pass

    def validate(self, output):
        from .clipping import operator_glyph_map
        from .engine import extract_page
        from .page_fingerprint import PageProof
        result=analyze_readonly(output)
        if result is None or result.semantic() != self.expected:
            fail('la edición alteró etiquetas, relaciones o propiedades accesibles ajenas.')
        proof=PageProof(self.structure.data, output)
        with fitz.open(stream=self.structure.data, filetype='pdf') as source, \
                fitz.open(stream=output, filetype='pdf') as target:
            for page in range(target.page_count):
                checkpoint()
                if page != self.page and proof.unchanged(page):continue
                before=self.model if page == self.page else extract_page(source, page, self.structure.data)
                after=extract_page(target, page, output)
                old=self.contexts if page == self.page else self.structure.glyph_contexts(page, before)
                new=result.glyph_contexts(page, after)
                for mcid in self.structure.marks[page]:
                    a=[g for g in before.glyphs if old[g.id] == mcid]
                    b=[g for g in after.glyphs if new[g.id] == mcid]
                    if ''.join(g.text for g in a) != ''.join(g.text for g in b):
                        fail('la edición cambió el texto lógico de una etiqueta ajena.')
                    _assert_membership(a,b)
                if page == self.page:
                    _, operations, _, mapping=operator_glyph_map(output, page, after)
                    bare=_bare_shows(operations)
                    actual=[g for g in after.glyphs
                            if mapping.get(g.id, {}).get('operation') in bare]
                    _assert_membership(self.expected_unmarked, actual)
        return {'verified':True, 'structure_preserved':True, 'logical_text_verified':True,
                'unmarked_text_preserved':True, 'mcids':[], 'actual_text_updates':0,
                'layout_attribute_updates':0,
                'preserved_source_irregularities':list(self.structure.source_irregularities),
                'scope':'Texto sin etiqueta conservado como tal; no certificación PDF/UA.'}
