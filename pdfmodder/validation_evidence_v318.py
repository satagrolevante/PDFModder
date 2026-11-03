"""Bounded, process-local evidence for exact, completely validated snapshots.

Tokens are capabilities, not serialisable assertions from the UI or recovery
files. A proof is accepted only in its originating session scope, for the same
immutable bytes and validation policy. Cache misses always use full validation.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from hashlib import sha256

_POLICY = 'pdfmodder-complete-integrity-v318-1'
_scope = ContextVar('pdfmodder_validation_evidence_v318', default=None)


@dataclass(frozen=True, eq=False)
class _Proof:
    digest: bytes
    size: int
    pages: int
    policy: str = _POLICY


class ValidationEvidenceCacheV318:
    def __init__(self, *, max_entries=32, canonical_budget=32 * 1024 * 1024):
        self.max_entries = max(1, int(max_entries))
        self.canonical_budget = max(0, int(canonical_budget))
        self.snapshots = OrderedDict()
        self.crypto = OrderedDict()
        self.canonical = OrderedDict()
        self.canonical_bytes = 0

    def clear(self):
        self.snapshots.clear()
        self.crypto.clear()
        self.canonical.clear()
        self.canonical_bytes = 0

    def _put(self, cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > self.max_entries:
            cache.popitem(last=False)


@contextmanager
def validation_scope_v318(cache):
    token = _scope.set(cache)
    try:
        yield
    finally:
        _scope.reset(token)


def _key(data):
    return sha256(data).digest(), len(data), _POLICY


def remember_validated_snapshot_v318(data, page_count=None):
    """Internal validator boundary: call ONLY after all integrity checks pass."""
    cache = _scope.get()
    if cache is None:
        return None
    if page_count is None:
        from io import BytesIO
        from pypdf import PdfReader
        page_count = len(PdfReader(BytesIO(data), strict=True).pages)
    key = _key(data)
    proof = _Proof(key[0], key[1], int(page_count))
    cache._put(cache.snapshots, key, proof)
    return proof


def validated_snapshot_v318(data):
    cache = _scope.get()
    return cache.snapshots.get(_key(data)) if cache is not None else None


def has_validated_snapshot_v318(data, proof=None):
    cache = _scope.get()
    if cache is None or not isinstance(proof, _Proof):
        return False
    key = _key(data)
    registered = cache.snapshots.get(key)
    if registered is not proof or proof.policy != _POLICY:
        return False
    cache.snapshots.move_to_end(key)
    return True


def validated_result_v318(function):
    """Decorate a COMPLETE engine operation returning (candidate, report).

    This belongs outside every semantic, accessibility and rendering validator;
    decorating a low-level syntax check would issue evidence too early.
    """
    @wraps(function)
    def call(*args, **kwargs):
        result = function(*args, **kwargs)
        if (isinstance(result, tuple) and len(result) == 2
                and isinstance(result[0], bytes)):
            # No-op branches are often intentionally cheap and unvalidated.
            # They may retain existing evidence, but cannot mint new evidence.
            source = args[0] if args else kwargs.get('data')
            if isinstance(source, bytes) and result[0] == source:
                return result
            remember_validated_snapshot_v318(result[0])
        return result
    return call


def canonical_snapshot_v318(data, prepare):
    """Reuse a complete, independently validated signing preparation."""
    cache = _scope.get()
    key = _key(data)
    if cache is not None and key in cache.canonical:
        cache.canonical.move_to_end(key)
        return cache.canonical[key]
    result = bytes(prepare())
    if cache is not None and len(result) <= cache.canonical_budget:
        cache.canonical[key] = result
        cache.canonical_bytes += len(result)
        while (cache.canonical_bytes > cache.canonical_budget
               or len(cache.canonical) > 2):
            _, removed = cache.canonical.popitem(last=False)
            cache.canonical_bytes -= len(removed)
    return result


def remember_crypto_v318(data, certificate_sha256, report):
    cache = _scope.get()
    if cache is not None:
        cache._put(cache.crypto, (_key(data), certificate_sha256), dict(report))


def crypto_evidence_v318(data, certificate_sha256):
    cache = _scope.get()
    if cache is None or not certificate_sha256:
        return None
    key = (_key(data), certificate_sha256)
    result = cache.crypto.get(key)
    if result is not None:
        cache.crypto.move_to_end(key)
        return dict(result)
    return None
