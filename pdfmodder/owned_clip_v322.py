"""Fork only selected text into its own expandable clipping scope.

Every original W/W* and neighboring SHOW stays at the original location.
The fork repeats state/cursor operators but paints only the new replacement.
Thus enlarging its cell cannot reveal hidden original characters or artwork.
"""
from dataclasses import dataclass
import copy
import math

import pymupdf as fitz
from pypdf.generic import ArrayObject, ByteStringObject

from .clipped_layout import _state_at
from .clip_move_v150 import _scope
from .clipping import _raw
from .model import EditError


@dataclass
class OwnedClipPlan:
    begin: int
    end: int
    limits: object


def plan_owned_clip(operations, targets, resources, page_matrix, page_bounds):
    """Return a reproducible, text-only cell; unsupported ownership stays strict."""
    try:
        begin, end = _scope(operations, targets)
    except EditError:
        return None
    scope = operations[begin:end+1]
    operators = [op for _,op in scope]
    rectangles = [i for i,op in enumerate(operators) if op==b're']
    if (not rectangles or len(rectangles)!=sum(op in (b'W',b'W*') for op in operators)
            or any(operators[i+1:i+3] not in ([b'W',b'n'],[b'W*',b'n']) for i in rectangles)
            or any(op in (b'm',b'l',b'c',b'v',b'y',b'h') for op in operators)):
        return None
    parent = _state_at(operations, begin, resources)
    if parent['unknown']:
        return None
    limits = (parent['clip']*page_matrix if parent['clip'] is not None else page_bounds) & page_bounds
    if limits.is_empty:
        return None
    return OwnedClipPlan(begin,end,limits)


def replacement_scope(plan, operations, shows, resources, page_matrix, region, insertion, first_id):
    """Create private replacement paint while retaining all cursor advances."""
    from .richtext import _unit, _source_width
    from .native_layout import _number, _compact_adjustments
    clone = copy.deepcopy(operations[plan.begin:plan.end+1])
    for index in range(plan.begin,plan.end+1):
        args,op = operations[index]
        if op!=b're':
            continue
        state = _state_at(operations,index,resources)
        matrix = state['ctm']*page_matrix
        if (abs(matrix.b)+abs(matrix.c)>1e-6
                or not all(math.isfinite(v) for v in matrix) or abs(matrix.a*matrix.d)<1e-10):
            raise EditError('La transformación del recinto no permite ampliar su recorte de forma localizada.')
        old = fitz.Rect(float(args[0]),float(args[1]),float(args[0])+float(args[2]),float(args[1])+float(args[3]))*matrix
        expanded = (old | fitz.Rect(region))*(~matrix)
        clone[index-plan.begin] = ([_number(v) for v in (expanded.x0,expanded.y0,expanded.width,expanded.height)],b're')
    replacements = {}
    inserted = False
    for show in shows:
        index = show['operation']
        if not plan.begin < index < plan.end:
            continue
        args,op = operations[index]
        unit = _unit(show)
        state = _state_at(operations,index,resources)
        if op not in (b'Tj',b'TJ') or show['render_mode']!=0 or state['size'] is None or state['size']<=0:
            raise EditError('El recinto comparte un operador de texto que no puede aislarse para ampliar su recorte.')
        array = args[0] if op==b'TJ' else [args[0]]
        chunks, values, position = [], ArrayObject(), 0
        def flush():
            nonlocal values
            if values:
                chunks.append(([_compact_adjustments(values)],b'TJ'))
                values = ArrayObject()
        for value in array:
            if not isinstance(value,(str,bytes)):
                values.append(copy.deepcopy(value));continue
            raw = _raw(value)
            if len(raw)%unit:
                raise EditError('El recinto contiene un código de fuente incompleto.')
            for offset in range(0,len(raw),unit):
                if position>=len(show['glyphs']):
                    raise EditError('No se puede verificar el avance de los vecinos del recinto.')
                glyph = show['glyphs'][position]
                if glyph.id==first_id:
                    flush();chunks.extend(copy.deepcopy(insertion));inserted=True
                code = int.from_bytes(raw[offset:offset+unit],'big')
                step = (_source_width(show['font'],code,glyph.text)+1000*state['tc']/state['size']
                        +(1000*state['tw']/state['size'] if unit==1 and code==32 else 0))
                if not math.isfinite(step):
                    raise EditError('El avance de un vecino del recinto no es finito.')
                values.append(_number(-step));position+=1
        if position!=len(show['glyphs']):
            raise EditError('El recinto no tiene una correspondencia completa de códigos y caracteres.')
        flush();replacements[index-plan.begin]=chunks
    if not inserted:
        raise EditError('La ampliación no pudo vincular la inserción a su tramo original.')
    result=[]
    for index,item in enumerate(clone):
        result.extend(replacements.get(index,[item]))
    return result
