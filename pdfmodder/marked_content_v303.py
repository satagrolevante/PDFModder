"""Check surviving marked-content scopes without discarding their operators."""
from io import BytesIO
from math import isfinite

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import (BooleanObject, ContentStream, DictionaryObject,
                           NameObject)

from .model import EditError


MARKED_ISSUE = 'Página con contenido marcado o capas sin estructura accesible verificable.'
_SPECIAL_TAGS = {'/OC', '/ReversedChars', '/PMT', '/PMParagraph'}
_PLAIN_TAGS = {'/Span', '/P', '/H', '/H1', '/H2', '/H3', '/H4', '/H5', '/H6',
               '/Div', '/Sect', '/Document', '/Part', '/Art', '/BlockQuote',
               '/Caption', '/L', '/LI', '/Lbl', '/LBody', '/Table', '/TR', '/TH',
               '/TD', '/THead', '/TBody', '/TFoot', '/Figure', '/Formula', '/Link',
               '/Note', '/Reference', '/BibEntry', '/Code', '/Quote', '/NonStruct',
               '/Private', '/Artifact'}


def _resolve(value):
    return value.get_object() if hasattr(value, 'get_object') else value


def _reject():
    # Keep the established issue exact: verified, editor-owned typography has
    # its own stricter ownership proof before removing this page-level issue.
    raise EditError(MARKED_ISSUE)


def _properties(tag, operand, resources):
    if isinstance(operand, NameObject):
        catalog = _resolve(resources.get('/Properties', {}))
        if not isinstance(catalog, dict) or operand not in catalog:
            _reject()
        operand = catalog[operand]
    props = _resolve(operand)
    if not isinstance(props, (dict, DictionaryObject)):
        _reject()
    allowed = {'/MCID'}
    if '/PMInstanceID' in props:
        # Passive temporary identity for a locally isolated Form. It grants
        # no ownership or editing waiver; the final repacker verifies every
        # identity against the original invocation graph and removes it.
        import re
        if not isinstance(props['/PMInstanceID'],str) or not re.fullmatch(r'\d+(?:\.\d+)*',props['/PMInstanceID']):
            _reject()
        allowed.add('/PMInstanceID')
    if tag == '/Artifact':
        allowed |= {'/Type', '/Subtype', '/Attached', '/BBox'}
        if '/Type' in props and (not isinstance(_resolve(props['/Type']),NameObject) or
                _resolve(props['/Type']) not in ('/Pagination', '/Layout', '/Page', '/Background')):
            _reject()
        if '/Subtype' in props and (not isinstance(_resolve(props['/Subtype']),NameObject) or
                _resolve(props['/Subtype']) not in ('/Header', '/Footer', '/Watermark')):
            _reject()
        if '/Attached' in props:
            attached = _resolve(props['/Attached'])
            if (not isinstance(attached, (list, tuple)) or not attached or
                    any(not isinstance(_resolve(v), NameObject) or
                        _resolve(v) not in ('/Top', '/Bottom', '/Left', '/Right')
                        for v in attached)):
                _reject()
        if '/BBox' in props:
            box = _resolve(props['/BBox'])
            if (not isinstance(box, (list,tuple)) or len(box)!=4 or
                    any(isinstance(_resolve(v),(bool,BooleanObject)) or
                        not isinstance(_resolve(v),(int,float)) or
                        not isfinite(float(_resolve(v))) for v in box) or
                    float(box[0])>=float(box[2]) or float(box[1])>=float(box[3])):
                _reject()
    # ActualText, Alt, E, OC, BBox and unknown properties have meaning beyond
    # an orphan structure association; their existing safety gates remain.
    if set(props) - allowed:
        _reject()
    if '/MCID' in props:
        mcid = _resolve(props['/MCID'])
        if isinstance(mcid, (bool, BooleanObject)) or not isinstance(mcid, int) or mcid < 0:
            _reject()
    elif tag not in _PLAIN_TAGS:
        _reject()
    return props


def assert_compatible_unstructured_marks(reader, page, operations=None):
    """Accept only balanced, nonsemantic scopes, including invoked Forms.

    An MCID without StructTreeRoot is an inert association, including custom
    role names left by an explicit removal of tags. Neither those wrappers nor
    artifact classifications change text, visibility or cursor advances.
    Forms use their own resource namespaces and cannot close a caller's scope.
    """
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        _reject()

    def visit(ops, resources, ancestry=()):
        resources = _resolve(resources)
        if not isinstance(resources, dict):
            _reject()
        stack, seen_mcids = [], set()
        for args, operator in ops:
            if operator in (b'BMC', b'BDC', b'MP', b'DP'):
                with_props = operator in (b'BDC', b'DP')
                if len(args) != (2 if with_props else 1) or not isinstance(args[0], NameObject):
                    _reject()
                tag = str(args[0])
                if tag in _SPECIAL_TAGS:
                    _reject()
                if with_props:
                    props = _properties(tag, args[1], resources)
                    if '/MCID' in props and operator == b'BDC':
                        mcid = int(_resolve(props['/MCID']))
                        if mcid in seen_mcids:
                            _reject()
                        seen_mcids.add(mcid)
                elif tag not in _PLAIN_TAGS:
                    _reject()
                if operator in (b'BMC', b'BDC'):
                    stack.append(tag)
            elif operator == b'EMC':
                if args or not stack:
                    _reject()
                stack.pop()
            elif operator == b'Do':
                objects = _resolve(resources.get('/XObject', {}))
                if (len(args) != 1 or not isinstance(args[0], NameObject) or
                        not isinstance(objects, dict) or args[0] not in objects):
                    _reject()
                form = _resolve(objects[args[0]])
                if not isinstance(form, dict):
                    _reject()
                if form.get('/Subtype') == '/Form':
                    identity = id(form)
                    if identity in ancestry or len(ancestry) >= 32:
                        _reject()
                    # Optional-content association on a Form also controls its
                    # visibility without needing an /OC marked-content wrapper.
                    if form.get('/OC') is not None:
                        _reject()
                    visit(ContentStream(form, reader).operations,
                          form.get('/Resources', resources), (*ancestry, identity))
        if stack:
            _reject()

    ops = operations if operations is not None else ContentStream(page.get_contents(), reader).operations
    visit(ops, page.get('/Resources', {}))


def assert_unstructured_artifact_bounds(data, page_number, model, selected,
                                       planned, mapping, operations, *, expand=False):
    """Retain advisory Artifact BBoxes and prove affected text stays bounded.

    The ordinary transaction already proves every untouched artifact's glyphs
    and properties unchanged. Only edited scopes need a destination check;
    deletion inserts no new content and leaves the declared extent intact.
    """
    if not planned:
        return
    reader=PdfReader(BytesIO(data),strict=True)
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        return
    resources=_resolve(reader.pages[page_number].get('/Resources',{}))
    stack=[];boxes={};contexts={}
    for index,(args,operator) in enumerate(operations):
        if operator in (b'BMC',b'BDC'):
            box_id=None
            if operator==b'BDC' and str(args[0])=='/Artifact':
                props=_properties(str(args[0]),args[1],resources)
                if str(args[0])=='/Artifact' and '/BBox' in props:
                    box_id=index
                    boxes[index]=tuple(float(v) for v in _resolve(props['/BBox']))
            stack.append(box_id)
        elif operator==b'EMC':
            if not stack:_reject()
            stack.pop()
        contexts[index]=tuple(i for i in stack if i is not None)
    affected={contexts.get(mapping[g.id]['operation'],()) for g in selected}
    owners={i for context in affected for i in context}
    if not owners:
        return
    # Reinsertion at the first SHOW must not relocate new text into a different
    # artifact scope, including a scope mixed with ordinary body content.
    if len(affected)!=1:
        raise EditError('La sustitución mezcla cajas de artefactos; edita cada encabezado o pie por separado.')
    with fitz.open(stream=data,filetype='pdf') as doc:
        page=doc[page_number];rotation=page.rotation;page.set_rotation(0)
        matrix=page.transformation_matrix
        page.set_rotation(rotation)
    for owner in owners:
        allowed=fitz.Rect(boxes[owner])*matrix
        # Some generators declare an ink box slightly smaller than nominal
        # ascent/descent rectangles. Preserve that existing overhang exactly.
        for glyph in model.glyphs:
            item=mapping.get(glyph.id)
            if item and owner in contexts.get(item['operation'],()):
                allowed |= fitz.Rect(glyph.bbox)
        if any(not (allowed+(-.035,-.035,.035,.035)).contains(fitz.Rect(g.bbox)) for g in planned):
            members={g.id for g in model.glyphs if g.id in mapping
                     and owner in contexts.get(mapping[g.id]['operation'],())}
            if not expand or not members <= {g.id for g in selected}:
                raise EditError('El texto nuevo queda fuera de la caja del encabezado o pie de página original.')
            import copy
            from pypdf.generic import ArrayObject,FloatObject
            args,op=operations[owner]
            props=copy.deepcopy(_properties(str(args[0]),args[1],resources))
            updated=fitz.Rect(boxes[owner])
            for glyph in planned:updated |= fitz.Rect(glyph.bbox)*(~matrix)
            props[NameObject('/BBox')]=ArrayObject([FloatObject(v) for v in updated])
            operations[owner]=([args[0],props],op)
    if expand:
        from .clipping import _signature
        return [_signature(_properties(str(a[0]),a[1],resources)) for a,op in operations
                if op==b'BDC' and str(a[0])=='/Artifact']


def verify_artifact_properties(data,page,expected):
    if expected is None:return
    from .clipping import _signature
    reader=PdfReader(BytesIO(data),strict=True)
    resources=_resolve(reader.pages[page].get('/Resources',{}))
    operations=ContentStream(reader.pages[page].get_contents(),reader).operations
    actual=[_signature(_properties(str(a[0]),a[1],resources)) for a,op in operations
            if op==b'BDC' and str(a[0])=='/Artifact']
    if actual!=expected:raise EditError('El guardado alteró propiedades de los encabezados o pies de página.')


def scope_unstructured_marks_v322(data,model,selected):
    """Unrelated layered Forms must not block an ordinary page-level SHOW.

    This does not permit editing inside an unknown/semantic marked scope.
    Native transactions still preserve all other operators and validate the
    actual complete result; malformed nesting never gains an exception.
    """
    if MARKED_ISSUE not in model.issues or not selected:return model
    from dataclasses import replace
    from hashlib import sha256
    from .clipping import operator_glyph_map,SHOW
    if model.revision and model.revision!=sha256(data).hexdigest():
        raise EditError('La selección pertenece a otra revisión del documento.')
    reader,operations,shows,mapping=operator_glyph_map(data,model.number,model)
    if reader.trailer['/Root'].get('/StructTreeRoot'):return model
    if any(g.id not in mapping for g in selected):return model
    from .marked_text_v324 import native_marked_plan
    try:
        plan=native_marked_plan(data,model.number,model,list(selected),list(selected),operations,mapping,reader=reader)
        if plan is not None:
            return replace(model,issues=[i for i in model.issues if i!=MARKED_ISSUE])
    except EditError:
        pass
    targets={mapping[g.id]['operation'] for g in selected}
    resources=_resolve(reader.pages[model.number].get('/Resources',{}))
    stack=[];seen=set()
    for index,(args,op) in enumerate(operations):
        if op in (b'BMC',b'BDC'):
            safe=False
            try:
                if op==b'BDC':_properties(str(args[0]),args[1],resources)
                elif len(args)!=1 or str(args[0]) not in _PLAIN_TAGS:_reject()
                safe=str(args[0]) not in _SPECIAL_TAGS
            except EditError:pass
            stack.append(safe)
        elif op==b'EMC':
            if not stack:return model
            stack.pop()
        if index in targets:
            if op not in SHOW or not all(stack):return model
            seen.add(index)
    if stack or seen!=targets:return model
    return replace(model,issues=[i for i in model.issues if i!=MARKED_ISSUE])
