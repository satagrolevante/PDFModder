"""Reference-preserving proof for immutable PDF object transactions.

Dictionary order and stream compression are serialization choices. Indirect
references, typed PDF values and decoded stream bytes are document identity.
Object-stream and xref-stream containers are storage, but may be disregarded
only when neither document's logical graph references them.
"""
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
import math

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject, BooleanObject, ByteStringObject, DictionaryObject, FloatObject,
    IndirectObject, NameObject, NullObject, NumberObject, StreamObject,
    TextStringObject,
)

from .model import EditError


_STORAGE_TYPES = {'/ObjStm', '/XRef'}
_STREAM_ENCODING_KEYS = {'/Length', '/Filter', '/DecodeParms'}
_LOSSLESS_FILTERS = {'/FlateDecode','/Fl','/LZWDecode','/LZW','/ASCIIHexDecode','/AHx',
                     '/ASCII85Decode','/A85','/RunLengthDecode','/RL'}
_TRAILER_STORAGE_KEYS = {'/Size', '/Prev', '/XRefStm'}
_MAX_OBJECTS = 250_000
_MAX_VALUES = 2_000_000
_MAX_DEPTH = 128


def _stream_encoding_keys(stream):
    """Only fully decoded lossless encodings may change representation.

Pypdf returns JPEG/JPX/JBIG2 payloads without interpreting their pixels. Their
filters and parameters can change rendering while get_data() stays identical,
so opaque codec declarations remain part of the strict typed identity.
"""
    filters=stream.get('/Filter')
    if filters is None:
        return _STREAM_ENCODING_KEYS
    filters=filters.get_object()
    filters=list(filters) if isinstance(filters,ArrayObject) else [filters]
    if all(isinstance(item.get_object(),NameObject) and str(item.get_object()) in _LOSSLESS_FILTERS
           for item in filters):
        return _STREAM_ENCODING_KEYS
    return {'/Length'}


def _fail():
    raise EditError('La operación alteró un recurso original compartido; transacción cancelada.')


class _Document:
    def __init__(self, data):
        try:
            with fitz.open(stream=data, filetype='pdf') as doc:
                if not doc.is_pdf or doc.is_repaired or doc.is_encrypted or doc.needs_pass:
                    raise ValueError('unverifiable PDF')
            self.reader = PdfReader(BytesIO(data), strict=True)
            if self.reader.is_encrypted:
                raise ValueError('encrypted PDF')
            self.references = {
                (number, generation)
                for generation, items in self.reader.xref.items()
                for number in items
                if number and not self.reader.xref_free_entry.get(generation, {}).get(number, False)
            }
            self.references.update((number, 0) for number in self.reader.xref_objStm)
            if len(self.references) > _MAX_OBJECTS:
                raise ValueError('too many PDF objects')
        except Exception as exc:
            raise EditError('No se pudo verificar el PDF y sus referencias con un lector estricto.') from exc
        self.objects = {}
        self.snapshots = {}
        self.value_count = 0
        self.reachable = self._reachable()

    def load(self, key):
        if key not in self.references:
            _fail()
        if key not in self.objects:
            try:
                value = self.reader.get_object(IndirectObject(*key, self.reader))
                if value is None:
                    raise ValueError('missing indirect object')
                self.objects[key] = value
            except Exception as exc:
                raise EditError('No se pudo verificar un recurso PDF original con el lector estricto.') from exc
        return self.objects[key]

    def _direct_references(self, value):
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > _MAX_DEPTH:
                _fail()
            self.value_count += 1
            if self.value_count > _MAX_VALUES:
                _fail()
            if isinstance(item, IndirectObject):
                yield (item.idnum, item.generation)
            elif isinstance(item, DictionaryObject):
                pending.extend((item.raw_get(key), depth + 1) for key in item)
            elif isinstance(item, ArrayObject):
                pending.extend((entry, depth + 1) for entry in item)

    def _reachable(self):
        pending = list(self._direct_references(self.reader.trailer))
        seen = set()
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            if len(seen) >= _MAX_OBJECTS:
                _fail()
            seen.add(key)
            pending.extend(self._direct_references(self.load(key)))
        return seen

    def snapshot(self, value, *, excluded=(), depth=0):
        if depth > _MAX_DEPTH:
            _fail()
        self.value_count += 1
        if self.value_count > _MAX_VALUES:
            _fail()
        if isinstance(value, IndirectObject):
            return ('reference', value.idnum, value.generation)
        if isinstance(value, NullObject):
            return ('null',)
        if isinstance(value, BooleanObject):
            return ('boolean', value.value)
        if isinstance(value, NameObject):
            return ('name', str(value))
        if isinstance(value, TextStringObject):
            return ('text', str(value))
        if isinstance(value, ByteStringObject):
            return ('bytes', bytes(value))
        if isinstance(value, (NumberObject, FloatObject)):
            if not math.isfinite(value):
                _fail()
            return ('number', Decimal(str(value)))
        if isinstance(value, DictionaryObject):
            ignored = set(excluded)
            if isinstance(value, StreamObject):
                ignored.update(_stream_encoding_keys(value))
            return ('stream' if isinstance(value, StreamObject) else 'dictionary', tuple(
                (str(key), self.snapshot(value.raw_get(key), depth=depth + 1))
                for key in sorted(value) if str(key) not in ignored
            ))
        if isinstance(value, ArrayObject):
            return ('array', tuple(self.snapshot(item, depth=depth + 1) for item in value))
        _fail()

    def object_snapshot(self, key, excluded=()):
        cache_key = key, frozenset(excluded)
        if cache_key not in self.snapshots:
            self.snapshots[cache_key] = self.snapshot(self.load(key), excluded=excluded)
        return self.snapshots[cache_key]


@dataclass
class PDFObjectIdentityProof:
    original_reader: PdfReader
    candidate_reader: PdfReader
    report: dict


def _page_fonts(document, page):
    try:
        resources = document.reader.pages[page].get('/Resources', DictionaryObject()).get_object()
        fonts = resources.get('/Font', DictionaryObject()).get_object()
        if not isinstance(resources, DictionaryObject) or not isinstance(fonts, DictionaryObject):
            _fail()
        # Resolve the resource dictionary itself, retaining exact font-program
        # references. Native object edits never introduce or replace a font.
        return document.snapshot(fonts)
    except EditError:
        raise
    except Exception as exc:
        raise EditError('No se pudieron verificar las fuentes originales de la página.') from exc


def _owned_form_fonts(original,candidate,contexts):
    validated=set()
    for context in contexts:
        source_key,copy_key=tuple(context['source']),tuple(context['copy'])
        if copy_key in validated or copy_key in original.references or copy_key not in candidate.reachable:
            _fail()
        source,copy=original.load(source_key),candidate.load(copy_key)
        if not (isinstance(source,StreamObject) and isinstance(copy,StreamObject) and
                source.get('/Subtype')=='/Form' and copy.get('/Subtype')=='/Form'):
            _fail()
        if original.object_snapshot(source_key,{'/Resources'})!=candidate.object_snapshot(copy_key,{'/Resources'}):
            _fail()
        resources=copy.get('/Resources',DictionaryObject()).get_object()
        if not isinstance(resources,DictionaryObject):
            _fail()
        fonts=resources.get('/Font',DictionaryObject()).get_object()
        if not isinstance(fonts,DictionaryObject) or original.snapshot(context['fonts'])!=candidate.snapshot(fonts):
            raise EditError('La operación alteró las fuentes originales del Form; transacción cancelada.')
        validated.add(copy_key)
    for key in candidate.reachable-original.references:
        value=candidate.load(key)
        if isinstance(value,StreamObject) and value.get('/Subtype')=='/Form' and key not in validated:
            raise EditError('Un Form nuevo carece de una identidad original verificable; transacción cancelada.')
    return len(validated)


def assert_pdf_object_identity(before_data, after_data, *, allowed_dictionary_keys=None,
                               allowed_page_dictionary_keys=None,
                               require_page_fonts=None,owned_form_font_context=()):
    """Prove all original indirect objects, with explicit caller-owned keys.

    ``allowed_dictionary_keys`` maps exact ``(xref, generation)`` references to
    dictionary keys that the caller owns. ``allowed_page_dictionary_keys``
    resolves those references from original page indices, including their
    generations. No referenced object is implicitly exempted. Reader-local
    memoization ends with this proof; PDF bytes and decoded private resources
    are never retained in a process-global cache.
    """
    original, candidate = _Document(before_data), _Document(after_data)
    allowed = {key: frozenset(values) for key, values in (allowed_dictionary_keys or {}).items()}
    for page,keys in (allowed_page_dictionary_keys or {}).items():
        try:
            reference=original.reader.pages[page].indirect_reference
            key=(reference.idnum,reference.generation)
        except Exception as exc:
            raise EditError('No se pudo verificar la referencia original de la página.') from exc
        allowed[key]=allowed.get(key,frozenset())|frozenset(keys)
    if any(key not in original.references or key not in candidate.references for key in allowed):
        _fail()
    if original.reader.pdf_header != candidate.reader.pdf_header:
        _fail()
    if original.snapshot(original.reader.trailer, excluded=_TRAILER_STORAGE_KEYS) != candidate.snapshot(
            candidate.reader.trailer, excluded=_TRAILER_STORAGE_KEYS):
        _fail()
    streams = 0
    storage = []
    for key in sorted(original.references):
        value = original.load(key)
        is_storage = isinstance(value, StreamObject) and str(value.get('/Type')) in _STORAGE_TYPES
        if is_storage and key not in original.reachable and key not in candidate.reachable:
            replacement = candidate.load(key) if key in candidate.references else None
            if replacement is None or isinstance(replacement, NullObject) or (
                    isinstance(replacement, StreamObject) and str(replacement.get('/Type')) in _STORAGE_TYPES):
                storage.append(key)
                continue
        if key not in candidate.references:
            _fail()
        changed = candidate.load(key)
        excluded = allowed.get(key, ())
        if excluded and (not isinstance(value, DictionaryObject) or not isinstance(changed, DictionaryObject)):
            _fail()
        if original.object_snapshot(key, excluded) != candidate.object_snapshot(key, excluded):
            _fail()
        if isinstance(value, StreamObject):
            try:
                if value.get_data() != changed.get_data():
                    raise ValueError('changed decoded stream')
            except Exception as exc:
                raise EditError('La operación alteró un flujo original compartido; transacción cancelada.') from exc
            streams += 1
    if require_page_fonts is not None and _page_fonts(original, require_page_fonts) != _page_fonts(candidate, require_page_fonts):
        raise EditError('La operación alteró las fuentes originales de la página; transacción cancelada.')
    forms=_owned_form_fonts(original,candidate,owned_form_font_context)
    return PDFObjectIdentityProof(original.reader, candidate.reader, {
        'verified': True, 'reference_preserving': True, 'typed_values_preserved': True,
        'original_objects_checked': len(original.references) - len(storage),
        'decoded_original_streams_checked': streams,
        'unreachable_storage_containers': [list(key) for key in storage],
        'native_page_fonts_preserved': require_page_fonts is not None,
        'owned_form_font_bindings_checked':forms,
    })
