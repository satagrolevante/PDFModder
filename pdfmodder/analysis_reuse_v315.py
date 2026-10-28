"""Bounded reuse of native text/resource probes and parsed PDF syntax.

Only immutable proof records and primitive syntax snapshots cross calls.
Readers, PDF bytes, operand arrays and live Documents are never cached.
Each consumer receives fresh PDF objects bound to its own source reader.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
import hashlib
from typing import NamedTuple

from pypdf.generic import (ArrayObject, BooleanObject, ByteStringObject,
                           ContentStream, DictionaryObject, FloatObject,
                           NameObject, NullObject, NumberObject, TextStringObject,
                           DecodedStreamObject, create_string_object)

from .draft_control_v305 import checkpoint


_scope = ContextVar('pdfmodder_analysis_scope_v315', default=None)
_MAX_SOURCE_BYTES = 32 * 1024 * 1024
_MAX_GLYPHS = 30_000
_MAX_RECORD_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 4
_MAX_AST_BYTES = 64 * 1024 * 1024
_MAX_SINGLE_AST_BYTES = 32 * 1024 * 1024
_MAX_AST_NODES = 600_000
_MAX_SYNTAX_ENTRIES_V316 = 64
_MAX_SCOPE_BYTES_V316 = 2 * 1024 * 1024


class AnalysisCacheV315:
    """A session may retain this bounded cache until suspension or close."""

    def __init__(self):
        self._state = {'entries': OrderedDict(), 'bytes': 0,
                       'syntax': OrderedDict(), 'syntax_bytes': 0,
                       'scopes': OrderedDict(), 'scope_bytes': 0}

    def clear(self):
        self._state['entries'].clear()
        self._state['bytes'] = 0
        self._state['syntax'].clear()
        self._state['syntax_bytes'] = 0
        self._state['scopes'].clear()
        self._state['scope_bytes'] = 0


class _Name(NamedTuple):
    value: str


class _Text(NamedTuple):
    value: bytes


class _Binary(NamedTuple):
    value: bytes


class _Array(NamedTuple):
    value: tuple


class _Dictionary(NamedTuple):
    value: tuple
    pdf: bool


class _UnsupportedAst(Exception):
    pass


def _freeze(value, budget, depth=0):
    budget[0] += 1
    budget[1] += 40
    if (depth > 64 or budget[0] > _MAX_AST_NODES
            or budget[1] > _MAX_SINGLE_AST_BYTES):
        raise _UnsupportedAst
    if getattr(value, 'indirect_reference', None) is not None:
        raise _UnsupportedAst
    kind = type(value)
    if kind is NumberObject:
        return int(value)
    if kind is FloatObject:
        return float(value)
    if kind is NameObject:
        budget[1] += len(value) * 4
        return _Name(str(value))
    if kind is TextStringObject:
        content = value.original_bytes
        budget[1] += len(content)
        return _Text(content)
    if kind is ByteStringObject:
        budget[1] += len(value)
        return _Binary(bytes(value))
    if kind is BooleanObject:
        return bool(value.value)
    if kind is NullObject:
        return None
    if kind in (list, tuple, ArrayObject):
        budget[1] += len(value) * 8
        frozen = tuple(_freeze(item, budget, depth + 1) for item in value)
        return _Array(frozen) if kind is ArrayObject else frozen
    if kind in (dict, DictionaryObject):
        budget[1] += len(value) * 64
        return _Dictionary(tuple((_freeze(key, budget, depth + 1),
                                  _freeze(item, budget, depth + 1))
                                 for key, item in value.items()),
                           kind is DictionaryObject)
    if kind in (str, bytes, int, float, bool) or value is None:
        if kind in (str, bytes):
            budget[1] += len(value) * (4 if kind is str else 1)
        return value
    # In particular, never retain an IndirectObject and its attached reader.
    raise _UnsupportedAst


def _thaw(value):
    kind = type(value)
    if kind is int:
        return NumberObject(value)
    if kind is float:
        return FloatObject(value)
    if kind is _Name:
        return NameObject(value.value)
    if kind is _Text:
        return create_string_object(value.value)
    if kind is _Binary:
        return ByteStringObject(value.value)
    if kind is bool:
        return BooleanObject(value)
    if value is None:
        return NullObject()
    if kind is tuple:
        return [_thaw(item) for item in value]
    if kind is _Array:
        return ArrayObject([_thaw(item) for item in value.value])
    if kind is _Dictionary:
        restored = {_thaw(key): _thaw(item) for key, item in value.value}
        return DictionaryObject(restored) if value.pdf else restored
    return value


def page_operations_v315(data, number, reader):
    """Parse page syntax, reusing bounded primitive-only snapshots.

    Decoded stream identity is sufficient only for syntax without indirect
    references. Resource/graphic-state interpretation is always done using the
    caller's fresh reader. Returned operand containers and PDF scalar objects
    are newly allocated and can safely be changed by their caller.
    """
    if _scope.get() is not None and len(data)<=_MAX_SOURCE_BYTES:
        page=reader.pages[number]
        contents=page.get('/Contents')
        contents=contents.get_object() if hasattr(contents,'get_object') else contents
        sources=(list(contents) if isinstance(contents,ArrayObject)
                 else [contents] if hasattr(contents,'get_data') else [])
        if sources:
            streams=[]
            for source in sources:
                source=source.get_object() if hasattr(source,'get_object') else source
                if not hasattr(source,'get_data'):break
                raw=source.get_data()
                if stream_scope_events_v316(raw,reader,prime_syntax=True) is None:break
                streams.append(raw)
            else:
                result=[]
                for raw in streams:
                    source=DecodedStreamObject();source.set_data(raw)
                    result.extend(_syntax_operations_v316(ContentStream(source,reader),bool(reader.strict)))
                return result
    return _syntax_operations_v316(
        ContentStream(reader.pages[number].get_contents(), reader),
        bool(reader.strict), cacheable=len(data) <= _MAX_SOURCE_BYTES)


def stream_operations_v316(raw):
    """Return fresh standalone stream operands using the same bounded cache."""
    stream=DecodedStreamObject();stream.set_data(bytes(raw))
    return _syntax_operations_v316(ContentStream(stream,None),None)


def _syntax_operations_v316(stream,policy,*,cacheable=True):
    checkpoint()
    state = _scope.get()
    if state is None or not cacheable:
        return stream.operations
    decoded = stream.get_data()
    if len(decoded) > _MAX_SOURCE_BYTES:
        return stream.operations
    # Keep strict and permissive reader policies separate, including when a
    # future parser version rejects syntax that its tolerant mode accepts.
    key = policy,hashlib.sha256(decoded).digest(),len(decoded)
    cached = state['syntax'].pop(key, None)
    if cached is not None:
        state['syntax'][key] = cached
        restored = []
        for index, (arguments, operator) in enumerate(cached[0]):
            if index % 256 == 0:
                checkpoint()
            restored.append((_thaw(arguments), operator))
        checkpoint()
        return restored
    operations = stream.operations
    _remember_syntax_v316(key,operations)
    return operations


def _remember_syntax_v316(key,operations):
    state=_scope.get()
    if state is None or key in state['syntax']:return
    budget = [0, len(operations) * 64]
    try:
        records = []
        for index, (arguments, operator) in enumerate(operations):
            if index % 256 == 0:
                checkpoint()
            records.append((_freeze(arguments, budget), bytes(operator)))
        snapshot = tuple(records)
        if budget[1] > _MAX_SINGLE_AST_BYTES:
            return
    except _UnsupportedAst:
        return
    state['syntax'][key] = snapshot, budget[1]
    state['syntax_bytes'] += budget[1]
    while (len(state['syntax']) > _MAX_SYNTAX_ENTRIES_V316
           or state['syntax_bytes'] > _MAX_AST_BYTES):
        _, (_, size) = state['syntax'].popitem(last=False)
        state['syntax_bytes'] -= size
    checkpoint()


def stream_scope_events_v316(raw,reader,*,prime_syntax=False):
    """Independently parsed structural events for one complete stream.

    A sentinel detects operands or tokens split across /Contents boundaries.
    Those cases return None so the caller parses the original concatenation.
    Summaries carry no authority to skip scope/resource validation themselves.
    """
    checkpoint()
    raw=bytes(raw)
    if len(raw)>_MAX_SOURCE_BYTES:return None
    state=_scope.get()
    key=bool(reader.strict),hashlib.sha256(raw).digest(),len(raw)
    cached=state['scopes'].pop(key,None) if state is not None else None
    if cached is not None:
        state['scopes'][key]=cached
        return cached[0]
    sentinel_name=NameObject('/PDFModderScopeEndV316')
    sentinel_operator=b'PDFModderScopeBoundaryV316'
    stream=DecodedStreamObject()
    stream.set_data(raw+b'\n/PDFModderScopeEndV316 PDFModderScopeBoundaryV316\n')
    try:
        operations=ContentStream(stream,reader).operations
        if (not operations or operations[-1][1]!=sentinel_operator
                or operations[-1][0]!=[sentinel_name]):return None
        events=[]
        for index,(operands,operator) in enumerate(operations[:-1]):
            if index%256==0:checkpoint()
            if operator in (b'BT',b'ET',b'q',b'Q',b'BDC',b'BMC',b'EMC',b'W',b'W*',b'Tr',
                            b'n',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'):
                events.append((operator,None))
            elif operator==b'cm':
                values=tuple(float(item) for item in operands)
                if len(values)!=6:return None
                events.append((operator,values))
            elif operator in (b'Do',b'Tf',b'gs'):
                if not operands or not isinstance(operands[0],NameObject):return None
                events.append((operator,str(operands[0])))
        result=tuple(events)
    except Exception as error:
        from .draft_control_v305 import DraftCancelled
        if isinstance(error,DraftCancelled):raise
        return None
    checkpoint()
    if prime_syntax:_remember_syntax_v316(key,operations[:-1])
    estimate=128+sum(64+len(value or '')*(4 if isinstance(value,str) else 32) for _,value in result)
    if state is not None and estimate<=_MAX_SCOPE_BYTES_V316:
        state['scopes'][key]=(result,estimate)
        state['scope_bytes']+=estimate
        while (len(state['scopes'])>2048
               or state['scope_bytes']>_MAX_SCOPE_BYTES_V316):
            _,(_,size)=state['scopes'].popitem(last=False)
            state['scope_bytes']-=size
    return result


@contextmanager
def analysis_scope_v315(cache=None):
    """Use an explicit session cache, or an ephemeral command-local cache."""
    if _scope.get() is not None:
        yield
        return
    if cache is not None and not isinstance(cache, AnalysisCacheV315):
        raise TypeError('Expected an internal AnalysisCacheV315 instance.')
    owned = cache is None
    cache = cache if cache is not None else AnalysisCacheV315()
    token = _scope.set(cache._state)
    try:
        yield
    finally:
        if owned:
            cache.clear()
        _scope.reset(token)


def operator_key_v315(data, number, model):
    """Resource annotation is output of the probe, rather than its input."""
    if (_scope.get() is None or len(data) > _MAX_SOURCE_BYTES
            or len(model.glyphs) > _MAX_GLYPHS):
        return None
    checkpoint()
    glyphs = tuple(replace(g, font_xref=None, font_resource=None) for g in model.glyphs)
    fingerprint = hashlib.sha256(repr(glyphs).encode('utf-8')).digest()
    return hashlib.sha256(data).digest(), number, fingerprint


def operator_evidence_v315(key):
    state = _scope.get()
    if state is None or key is None:
        return None
    item = state['entries'].pop(key, None)
    if item is not None:
        state['entries'][key] = item
        return item[0]
    return None


def remember_operator_evidence_v315(key, shows):
    state = _scope.get()
    if state is None or key is None:
        return
    # Font dictionaries and Glyph instances belong to the caller. Only scalar
    # resource identities and exact member ids are retained in the proof.
    records = tuple((show['operation'], show['resource'], show['xref'],
                     show['render_mode'], tuple(g.id for g in show['glyphs']))
                    for show in shows)
    estimate = sum(256 + len(item[4]) * 32 for item in records)
    if estimate > _MAX_RECORD_BYTES:
        return
    previous = state['entries'].pop(key, None)
    if previous is not None:
        state['bytes'] -= previous[1]
    state['entries'][key] = records, estimate
    state['bytes'] += estimate
    while len(state['entries']) > _MAX_ENTRIES or state['bytes'] > _MAX_RECORD_BYTES:
        _, (_, size) = state['entries'].popitem(last=False)
        state['bytes'] -= size
