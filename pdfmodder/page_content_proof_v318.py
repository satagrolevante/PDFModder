"""Exact renderer-input proof for whole-page operations with explicit geometry.

The caller still validates page geometry, annotation/link semantics, document
catalogues and tagged structure. This proof only replaces text/vector/image
enumeration and raster comparison when all remaining page inputs are identical.
It supports mapped pages without depending on object numbers or page-tree Count.
Unknown graphs and exhausted budgets always leave the complete validator active.
"""
from __future__ import annotations

from .draft_control_v305 import checkpoint, DraftCancelled
from .page_fingerprint import _Graph, _NoProof, _digest
from pypdf.generic import DictionaryObject, IndirectObject


class _ContentGraph(_Graph):
    _SEPARATELY_CHECKED = frozenset({
        '/Parent', '/Annots', '/StructParents', '/Rotate', '/MediaBox',
        '/CropBox', '/BleedBox', '/TrimBox', '/ArtBox',
    })
    _PAGE_TREE_KEYS = frozenset({
        '/Type', '/Parent', '/Kids', '/Count', '/Resources', '/Rotate',
        '/MediaBox', '/CropBox', '/BleedBox', '/TrimBox', '/ArtBox',
    })

    def content_page(self, number):
        checkpoint()
        page = self.pages[number]
        # PdfReader resolves the standard inherited Resources/boxes/Rotate
        # into each PageObject. Reject nonstandard ancestor state rather than
        # assuming that a second renderer will ignore it in the same way.
        parent = page.get('/Parent')
        seen = set()
        while parent is not None:
            if not isinstance(parent, IndirectObject) or parent.pdf is not self.reader:
                raise _NoProof('Ambiguous page-tree parent')
            reference = parent.idnum, parent.generation
            if reference in seen:
                raise _NoProof('Page-tree cycle')
            seen.add(reference)
            self.check(len(seen))
            node = parent.get_object()
            if (not isinstance(node, DictionaryObject) or node.get('/Type') != '/Pages'
                    or set(node) - self._PAGE_TREE_KEYS):
                raise _NoProof('Unknown inherited page state')
            parent = node.get('/Parent')
        return _digest(b'mapped_page_content_resources_v318', self.global_hash +
                       self.dictionary(page, 0, omitted=self._SEPARATELY_CHECKED)).hex()


class MappedPageContentProofV318:
    """Compare content/resources for page pairs whose other inputs are checked.

    No page is certified by this object alone: annotations (including their
    appearances), geometry, semantic structure and mapped destinations belong
    to the operation's existing independent validators. No digest is accepted
    from a caller or from PDF metadata.
    """
    _graph_type = _ContentGraph
    def __init__(self, before_data, after_data, *, max_nodes=1_000_000,
                 max_depth=64, max_stream_bytes=64*1024*1024,
                 max_total_stream_bytes=256*1024*1024):
        self.before_data, self.after_data = bytes(before_data), bytes(after_data)
        self.limits = dict(max_nodes=max_nodes, max_depth=max_depth,
                           max_stream_bytes=max_stream_bytes,
                           max_total_stream_bytes=max_total_stream_bytes)
        self.graphs = [None, None]
        self.disabled = [False, False]
        self.digests = [{}, {}]
        self.results = {}

    def _page(self, side, number):
        if self.disabled[side]:
            raise _NoProof('Unprovable revision')
        if self.graphs[side] is None:
            try:
                self.graphs[side] = self._graph_type(
                    self.before_data if side == 0 else self.after_data, **self.limits)
            except DraftCancelled:
                raise
            except Exception:
                self.disabled[side] = True
                raise
        graph = self.graphs[side]
        if not 0 <= number < graph.page_count:
            raise _NoProof('Page outside revision')
        if number not in self.digests[side]:
            self.digests[side][number] = graph.content_page(number)
        return self.digests[side][number]

    def unchanged(self, before_page, after_page):
        checkpoint()
        if any(type(number) is not int or number < 0 for number in (before_page, after_page)):
            return False
        key = before_page, after_page
        if key not in self.results:
            fingerprint = None
            try:
                left, right = self._page(0, before_page), self._page(1, after_page)
                if left == right:
                    fingerprint = left
            except DraftCancelled:
                raise
            except Exception:
                pass
            self.results[key] = fingerprint
        return self.results[key] is not None

    def report(self, before_page, after_page):
        if not self.unchanged(before_page, after_page):
            return {}
        return {'verification': 'identical_content_resources_sha256',
                'fingerprint': self.results[before_page, after_page],
                'rasterized': False, 'pixel_measurements': False,
                'geometry_annotations_checked_separately': True,
                'max_channel_delta': 0, 'pixels_above_8': 0,
                'mean_channel_delta': 0, 'verified_ink_regions': []}
