"""Conservative identity proof for pages unaffected by a PDF transaction.

An identical graph proves identical input to the renderer without rasterizing
the page. This is deliberately not a visual similarity test. Unknown objects,
cycles, external streams and exceeded budgets return no proof, leaving the
ordinary content and pixel validators responsible for that page.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math
import zlib
from collections import OrderedDict
from threading import RLock

from .draft_control_v305 import checkpoint, DraftCancelled

from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject, BooleanObject, ByteStringObject, DictionaryObject,
    FloatObject, IndirectObject, NameObject, NullObject, NumberObject,
    StreamObject, TextStringObject,
)


class _NoProof(Exception):
    pass


class _StrictReader(PdfReader):
    """Strict parsing also forbids pypdf's automatic object-header repair."""

    def get_object(self, indirect_reference):
        reference = (IndirectObject(indirect_reference, 0, self)
                     if isinstance(indirect_reference, int) else indirect_reference)
        if reference.pdf is not self:
            raise _NoProof("Foreign reference")
        key = (reference.generation, reference.idnum)
        if self.cache_get_indirect_object(*key) is None:
            if reference.generation == 0 and reference.idnum in self.xref_objStm:
                return super().get_object(reference)
            offset = self.xref.get(reference.generation, {}).get(reference.idnum)
            if offset is None or self.xref_free_entry.get(reference.generation, {}).get(reference.idnum):
                raise _NoProof("Missing or free reference")
            position = self.stream.tell()
            try:
                self.stream.seek(offset)
                number, generation = self.read_object_header(self.stream)
                if (number, generation) != (reference.idnum, reference.generation):
                    raise _NoProof("Ambiguous object offset")
            finally:
                self.stream.seek(position)
        return super().get_object(reference)

    @staticmethod
    def _check_storage_stream(stream):
        """Never build an object graph from a repaired compressed xref/ObjStm."""
        if any(key in stream for key in ("/F", "/FFilter", "/FDecodeParms")):
            raise _NoProof("External object storage")
        filters = stream.get("/Filter")
        if isinstance(filters, ArrayObject) and len(filters) == 1:
            filters = filters[0]
        data = stream._data
        if not isinstance(data, bytes) or len(data) > 64 * 1024 * 1024:
            raise _NoProof("Object storage budget exceeded")
        if filters is None:
            return
        if filters not in ("/FlateDecode", "/Fl"):
            raise _NoProof("Unsupported object storage encoding")
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(data, 64 * 1024 * 1024 + 1)
        if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or len(decoded) > 64 * 1024 * 1024):
            raise _NoProof("Ambiguous compressed object storage")
        params = stream.get("/DecodeParms")
        if isinstance(params, ArrayObject) and len(params) == 1:
            params = params[0]
        if params is None or isinstance(params, NullObject):
            return
        allowed = {"/Predictor", "/Columns", "/Colors", "/BitsPerComponent"}
        if not isinstance(params, DictionaryObject) or set(params) - allowed:
            raise _NoProof("Unknown object storage prediction")
        if any(not isinstance(value, NumberObject) for value in params.values()):
            raise _NoProof("Ambiguous object storage prediction")
        predictor = int(params.get("/Predictor", 1))
        if predictor == 1:
            return
        columns, colors = int(params.get("/Columns", 1)), int(params.get("/Colors", 1))
        if columns <= 0 or colors <= 0 or int(params.get("/BitsPerComponent", 8)) != 8:
            raise _NoProof("Unsupported object storage prediction geometry")
        rowlength = columns * colors + (1 if 10 <= predictor <= 15 else 0)
        if len(decoded) % rowlength or predictor not in {2, 10, 11, 12, 13, 14, 15}:
            raise _NoProof("Incomplete prediction rows")
        if predictor >= 10:
            for offset in range(0, len(decoded), rowlength):
                tag = decoded[offset]
                if tag > 4 or (predictor != 15 and tag != predictor - 10):
                    raise _NoProof("Invalid prediction tag")

    def _get_object_from_stream(self, indirect_reference):
        number, _ = self.xref_objStm[indirect_reference.idnum]
        self._check_storage_stream(IndirectObject(number, 0, self).get_object())
        return super()._get_object_from_stream(indirect_reference)

    def _read_pdf15_xref_stream(self, stream):
        result = super()._read_pdf15_xref_stream(stream)
        self._check_storage_stream(result)
        return result


def _digest(kind: bytes, payload: bytes) -> bytes:
    return hashlib.sha256(kind + b"\0" + len(payload).to_bytes(8, "big") + payload).digest()


class _Graph:
    """Memoization belongs to one immutable reader, never to an xref globally."""

    _LOSSLESS = {"/FlateDecode", "/Fl", "/ASCIIHexDecode", "/AHx",
                 "/ASCII85Decode", "/A85", "/RunLengthDecode", "/RL"}
    _OPAQUE = {"/LZWDecode", "/LZW", "/DCTDecode", "/DCT", "/JPXDecode",
               "/CCITTFaxDecode", "/CCF", "/JBIG2Decode"}
    _WHITESPACE = b"\x00\x09\x0a\x0c\x0d\x20"

    def __init__(self, data, *, max_nodes, max_depth, max_stream_bytes,
                 max_total_stream_bytes):
        checkpoint()
        self.reader = _StrictReader(io.BytesIO(bytes(data)), strict=True)
        if self.reader.is_encrypted:
            raise _NoProof("Encrypted graph")
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.max_stream_bytes = max_stream_bytes
        self.max_total_stream_bytes = max_total_stream_bytes
        self.nodes = 0
        self.stream_bytes = 0
        self.references = {}
        self.dictionaries = {}
        self.active_refs = set()
        self.active_nodes = set()
        self.root = self.reader.trailer["/Root"]
        if not isinstance(self.root, DictionaryObject) or self.root.get("/Type") != "/Catalog":
            raise _NoProof("Invalid catalog")
        self.pages = self.reader.pages
        self.page_count = len(self.pages)  # Resolve page-tree inheritance first.
        self.global_hash = self.dictionary(self.root, 0, only={
            "/OCProperties", "/OutputIntents", "/AcroForm",
        })

    def check(self, depth):
        self.nodes += 1
        if self.nodes % 256 == 0:
            checkpoint()
        if self.nodes > self.max_nodes or depth > self.max_depth:
            raise _NoProof("Graph budget exceeded")

    @staticmethod
    def name(value):
        if not isinstance(value, NameObject):
            raise _NoProof("Invalid dictionary name")
        # pypdf can decode different non-ASCII name byte sequences to the same
        # Unicode string. Do not treat those ambiguous PDF names as identical.
        try:
            return str(value).encode("ascii")
        except UnicodeEncodeError as exc:
            raise _NoProof("Ambiguous name bytes") from exc

    def resolved(self, value):
        if isinstance(value, IndirectObject):
            if value.pdf is not self.reader:
                raise _NoProof("Foreign reference")
            return value.get_object()
        return value

    def value(self, value, depth=0):
        self.check(depth)
        if isinstance(value, IndirectObject):
            if value.pdf is not self.reader or value.idnum <= 0:
                raise _NoProof("Invalid reference")
            key = (value.idnum, value.generation)
            if key in self.active_refs:
                raise _NoProof("Reference cycle")
            if key in self.references:
                return self.references[key]
            self.active_refs.add(key)
            try:
                result = self.value(value.get_object(), depth + 1)
            finally:
                self.active_refs.remove(key)
            self.references[key] = result
            return result
        if isinstance(value, StreamObject):
            return self.stream(value, depth)
        if isinstance(value, DictionaryObject):
            return self.dictionary(value, depth)
        if isinstance(value, ArrayObject):
            identity = id(value)
            if identity in self.active_nodes:
                raise _NoProof("Array cycle")
            self.active_nodes.add(identity)
            try:
                payload = b"".join(self.value(item, depth + 1) for item in value)
            finally:
                self.active_nodes.remove(identity)
            return _digest(b"array", payload)
        if isinstance(value, NameObject):
            return _digest(b"name", self.name(value))
        if isinstance(value, TextStringObject):
            return _digest(b"string", value.original_bytes)
        if isinstance(value, ByteStringObject):
            return _digest(b"string", bytes(value))
        if isinstance(value, BooleanObject):
            return _digest(b"boolean", b"1" if value.value else b"0")
        if isinstance(value, NullObject):
            return _digest(b"null", b"")
        if isinstance(value, NumberObject):
            return _digest(b"integer", str(int(value)).encode("ascii"))
        if isinstance(value, FloatObject):
            if not math.isfinite(value):
                raise _NoProof("Non-finite number")
            # Lossless PDF writers routinely emit 0 instead of 0.0 and 1 instead
            # of 1.0. PDF numeric operands have identical semantics in that case.
            if float(value).is_integer():
                return _digest(b"integer", str(int(value)).encode("ascii"))
            return _digest(b"real", float(value).hex().encode("ascii"))
        raise _NoProof("Unknown object type")

    def dictionary(self, value, depth, *, omitted=frozenset(), only=None):
        self.check(depth)
        identity = id(value)
        cache_key = (identity, frozenset(omitted), None if only is None else frozenset(only))
        if identity in self.active_nodes:
            raise _NoProof("Dictionary cycle")
        if cache_key in self.dictionaries:
            return self.dictionaries[cache_key]
        self.active_nodes.add(identity)
        try:
            items = []
            for key, item in value.items():
                raw_key = self.name(key)
                if key in omitted or (only is not None and key not in only):
                    continue
                items.append((raw_key, item))
            payload = b"".join(_digest(b"key", key) + self.value(item, depth + 1)
                               for key, item in sorted(items, key=lambda pair: pair[0]))
            result = _digest(b"dictionary", payload)
        finally:
            self.active_nodes.remove(identity)
        self.dictionaries[cache_key] = result
        return result

    def _filters(self, stream):
        raw = self.resolved(stream.get("/Filter", ArrayObject()))
        filters = list(raw) if isinstance(raw, ArrayObject) else [raw]
        names = [self.name(self.resolved(item)).decode("ascii") for item in filters]
        if any(name not in self._LOSSLESS | self._OPAQUE for name in names):
            raise _NoProof("Unknown filter")
        raw_params = self.resolved(stream.get("/DecodeParms", NullObject()))
        if isinstance(raw_params, NullObject):
            params = [NullObject()] * len(names)
        elif isinstance(raw_params, ArrayObject):
            if len(raw_params) != len(names):
                raise _NoProof("Ambiguous filter parameters")
            params = [self.resolved(item) for item in raw_params]
        elif isinstance(raw_params, DictionaryObject) and len(names) == 1:
            params = [raw_params]
        else:
            raise _NoProof("Invalid filter parameters")
        opaque = any(name in self._OPAQUE for name in names)
        for name, parameter in zip(names, params):
            if isinstance(parameter, NullObject):
                continue
            if not isinstance(parameter, DictionaryObject):
                raise _NoProof("Invalid filter parameter dictionary")
            if name in {"/FlateDecode", "/Fl"}:
                allowed = {"/Predictor", "/Colors", "/BitsPerComponent", "/Columns"}
                if set(parameter) - allowed:
                    raise _NoProof("Unknown prediction parameter")
                values = {key: self.resolved(item) for key, item in parameter.items()}
                if any(not isinstance(item, NumberObject) for item in values.values()):
                    raise _NoProof("Invalid prediction number")
                # Prediction and opaque image codecs keep all encoded bytes and
                # parameters. pypdf does not fully decode every such codec.
                opaque |= int(values.get("/Predictor", 1)) != 1
            elif name in self._LOSSLESS and parameter:
                raise _NoProof("Unexpected lossless filter parameters")
        return names, opaque

    def _decoded(self, data, filters):
        for name in filters:
            if name in {"/FlateDecode", "/Fl"}:
                decoder = zlib.decompressobj()
                data = decoder.decompress(data, self.max_stream_bytes + 1)
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise _NoProof("Incomplete or over-budget Flate stream")
            elif name in {"/ASCIIHexDecode", "/AHx"}:
                compact = bytes(char for char in data if char not in self._WHITESPACE)
                if not compact.endswith(b">") or b">" in compact[:-1]:
                    raise _NoProof("Invalid ASCIIHex terminator")
                encoded = compact[:-1]
                if len(encoded) % 2:
                    encoded += b"0"
                data = bytes.fromhex(encoded.decode("ascii"))
            elif name in {"/ASCII85Decode", "/A85"}:
                compact = bytes(char for char in data if char not in self._WHITESPACE)
                if not compact.endswith(b"~>") or compact.startswith(b"<~"):
                    raise _NoProof("Invalid ASCII85 terminator")
                data = base64.a85decode(compact[:-2], adobe=False)
            elif name in {"/RunLengthDecode", "/RL"}:
                result = bytearray()
                cursor = 0
                while cursor < len(data):
                    if cursor % 65536 == 0:
                        checkpoint()
                    length = data[cursor]
                    cursor += 1
                    if length == 128:
                        break
                    count = length + 1 if length < 128 else 257 - length
                    needed = count if length < 128 else 1
                    if cursor + needed > len(data):
                        raise _NoProof("Truncated RunLength stream")
                    result.extend(data[cursor:cursor + count] if length < 128
                                  else data[cursor:cursor + 1] * count)
                    cursor += needed
                    if len(result) > self.max_stream_bytes:
                        raise _NoProof("Stream budget exceeded")
                else:
                    raise _NoProof("Missing RunLength terminator")
                data = bytes(result)
            if len(data) > self.max_stream_bytes:
                raise _NoProof("Stream budget exceeded")
        return data

    def stream(self, value, depth):
        checkpoint()
        if "/F" in value or "/FFilter" in value or "/FDecodeParms" in value:
            raise _NoProof("External stream")
        data = value._data
        if not isinstance(data, bytes) or len(data) > self.max_stream_bytes:
            raise _NoProof("Invalid or over-budget stream")
        filters, opaque = self._filters(value)
        if not opaque:
            data = self._decoded(data, filters)
        self.stream_bytes += len(data)
        if self.stream_bytes > self.max_total_stream_bytes:
            raise _NoProof("Total stream budget exceeded")
        omitted = {"/Length"} if opaque else {"/Length", "/Filter", "/DecodeParms"}
        metadata = self.dictionary(value, depth, omitted=omitted)
        kind = b"encoded_stream" if opaque else b"decoded_stream"
        return _digest(kind, metadata + _digest(b"bytes", data))

    def page(self, number):
        checkpoint()
        page = self.pages[number]
        hashes = [self.global_hash, self.dictionary(page, 0, omitted={"/Parent"})]
        ancestor = page.get("/Parent")
        visited = set()
        depth = 0
        while ancestor is not None:
            depth += 1
            self.check(depth)
            if not isinstance(ancestor, IndirectObject) or ancestor.pdf is not self.reader:
                raise _NoProof("Ambiguous page-tree parent")
            key = (ancestor.idnum, ancestor.generation)
            if key in visited:
                raise _NoProof("Page-tree cycle")
            visited.add(key)
            parent = ancestor.get_object()
            if not isinstance(parent, DictionaryObject) or parent.get("/Type") != "/Pages":
                raise _NoProof("Invalid page-tree parent")
            hashes.append(self.dictionary(parent, depth, omitted={"/Kids", "/Parent"}))
            ancestor = parent.get("/Parent")
        return _digest(b"page_graph_v1", b"".join(hashes)).hex()


# Only completed digests are retained, never a PdfReader, graph, PDF object or
# caller-owned byte buffer. The key binds every source byte and all proof
# budgets. A cache hit is the exact same proof already obtained for that input,
# not a comparison by xref, size or an edited-page heuristic.
_PAGE_CACHE_MAX_REVISIONS = 4
_PAGE_CACHE_BUDGET = 8 * 1024 * 1024
_page_cache = OrderedDict()
_page_cache_bytes = 0
_page_cache_lock = RLock()


def clear_page_proof_cache(revision=None):
    """Release immutable page evidence, optionally for one SHA-256 revision."""
    global _page_cache_bytes
    with _page_cache_lock:
        for key in list(_page_cache):
            if revision is None or key[0].hex() == revision:
                _page_cache_bytes -= _page_cache.pop(key)[2]


def _page_cache_get(key, page=None):
    with _page_cache_lock:
        entry = _page_cache.get(key)
        if entry is None:
            return None
        _page_cache.move_to_end(key)
        return entry[0] if page is None else entry[1].get(page)


def _page_cache_put(key, count, page=None, fingerprint=None):
    global _page_cache_bytes
    # Never publish a result from work made obsolete while hashing a stream.
    checkpoint()
    with _page_cache_lock:
        entry = _page_cache.get(key)
        if entry is None:
            entry = [count, {}, 512]
            _page_cache[key] = entry
            _page_cache_bytes += entry[2]
        elif entry[0] != count:
            return  # Defensive: incompatible evidence must never be combined.
        if page is not None and page not in entry[1]:
            entry[1][page] = fingerprint
            entry[2] += 192
            _page_cache_bytes += 192
        _page_cache.move_to_end(key)
        while (_page_cache and (_page_cache_bytes > _PAGE_CACHE_BUDGET
                               or len(_page_cache) > _PAGE_CACHE_MAX_REVISIONS)):
            _, removed = _page_cache.popitem(last=False)
            _page_cache_bytes -= removed[2]


class _RevisionGraph:
    """A private lazy reader; shared evidence consists only of digest strings."""

    def __init__(self, data, limits):
        self.data = bytes(data)
        self.key = (hashlib.sha256(self.data).digest(), len(self.data),
                    tuple(sorted(limits.items())))
        self.limits = limits
        self.graph = None
        self.page_count = _page_cache_get(self.key)
        if self.page_count is None:
            self._open()

    def _open(self):
        if self.graph is None:
            self.graph = _Graph(self.data, **self.limits)
            self.page_count = self.graph.page_count
            _page_cache_put(self.key, self.page_count)
        return self.graph

    def page(self, page):
        checkpoint()
        if page >= self.page_count:
            raise _NoProof("Page outside document")
        result = _page_cache_get(self.key, page)
        if result is not None:
            return result
        graph = self._open()
        result = graph.page(page)
        _page_cache_put(self.key, self.page_count, page, result)
        return result


class PageProof:
    """Prove unchanged renderer inputs, independently of xref numbering.

    Completed positive page digests may be reused for exactly identical source
    bytes and proof limits. Readers and their mutable PDF objects remain local
    to this transition. Failure is local and always falls back to ordinary
    validation. Document-wide semantic validators remain necessary.
    """

    def __init__(self, before_data, after_data, *, max_nodes=1_000_000,
                 max_depth=64, max_stream_bytes=64 * 1024 * 1024,
                 max_total_stream_bytes=256 * 1024 * 1024):
        self._results = {}
        self._graphs = None
        self._revisions = None
        try:
            limits = dict(max_nodes=max_nodes, max_depth=max_depth,
                          max_stream_bytes=max_stream_bytes,
                          max_total_stream_bytes=max_total_stream_bytes)
            before, after = _RevisionGraph(before_data, limits), _RevisionGraph(after_data, limits)
            self._revisions = before.key[:2], after.key[:2]
            if before.page_count == after.page_count:
                self._graphs = before, after
        except DraftCancelled:
            raise
        except Exception:
            pass

    def matches(self, before_data, after_data):
        """Bind reuse by another validator to both complete immutable revisions."""
        checkpoint()
        if self._revisions is None:
            return False
        revisions = tuple((hashlib.sha256(bytes(data)).digest(), len(data))
                          for data in (before_data, after_data))
        return revisions == self._revisions

    def unchanged(self, page):
        checkpoint()
        if not isinstance(page, int) or isinstance(page, bool) or page < 0:
            return False
        if page not in self._results:
            fingerprint = None
            try:
                if self._graphs is not None:
                    before, after = (graph.page(page) for graph in self._graphs)
                    if before == after:
                        fingerprint = before
            except DraftCancelled:
                raise
            except Exception:
                pass
            self._results[page] = fingerprint
        return self._results[page] is not None

    def report(self, page):
        if not self.unchanged(page):
            return {}
        return {
            "verification": "identical_page_graph_sha256",
            "fingerprint": self._results[page],
            "rasterized": False,
            "pixel_measurements": False,
            "max_channel_delta": 0,
            "pixels_above_8": 0,
            "mean_channel_delta": 0,
            "verified_ink_regions": [],
        }
