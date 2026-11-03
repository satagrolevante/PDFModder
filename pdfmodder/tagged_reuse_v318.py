"""Primitive semantic page evidence, bound to independently identical PDF graphs.

The structure tree, ParentTree, owners, attributes and object references are
always reconstructed from the candidate's own reader. Only already checked
page syntax/marked-content summaries can be reused. No PDF object from the
source reader is inserted into the candidate.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from pypdf.generic import ContentStream

from .draft_control_v305 import checkpoint
from .page_content_proof_v318 import MappedPageContentProofV318
from .page_fingerprint import _Graph, _digest


_reference = ContextVar('pdfmodder_tagged_reference_v318', default=None)
_EVIDENCE_BYTES = 16 * 1024 * 1024
_MAX_PAGES = 1000


class _SyntaxGraph(_Graph):
    # TaggedStructure._page reads only the concatenated Contents and resolved
    # Resources. Global fields, page geometry and annotation appearances do not
    # change that AST. Every structural association is checked independently
    # against the candidate's own pages/annotations/ParentTree below.
    _GLOBAL_KEYS = frozenset()

    def content_page(self, number):
        checkpoint()
        return _digest(b'tagged_syntax_inputs_v318', self.dictionary(
            self.pages[number], 0, only={'/Contents', '/Resources'})).hex()


class _SyntaxProof(MappedPageContentProofV318):
    _graph_type = _SyntaxGraph

    def report(self, *_):
        # This is intentionally NOT an appearance/rendering proof.
        raise TypeError('Tagged syntax evidence cannot certify renderer output')


@contextmanager
def page_reference_v318(structure, mapping=None):
    token = _reference.set((structure, mapping))
    try:
        yield
    finally:
        _reference.reset(token)


def has_page_reference_v318():
    return _reference.get() is not None


class LazyPageOperationsV318:
    """Parse the candidate page only if a later consumer actually needs its AST."""
    def __init__(self, reader, number, count, scope_events):
        self.reader = reader
        self.number = number
        self.count = count
        # These primitive events came from the exact proven source AST. The
        # ordinary scope validator must still run its BT/ET state machine and
        # inspect invoked Forms against this candidate's own resources.
        self._scope_events_v318 = scope_events
        self._operations = None

    def scope_events_v318(self):
        return self._scope_events_v318

    def _get(self):
        if self._operations is None:
            checkpoint()
            operations = ContentStream(self.reader.pages[self.number].get_contents(), self.reader).operations
            if len(operations) != self.count:
                from .tagged import fail
                fail('la sintaxis de una página reutilizada no coincide con su prueba independiente.')
            self._operations = operations
        return self._operations

    def __len__(self):
        return self.count

    def __iter__(self):
        return iter(self._get())

    def __getitem__(self, index):
        return self._get()[index]


@dataclass(frozen=True)
class _PageEvidence:
    marks: tuple
    contexts: tuple
    operations: int
    graphical_artifacts: frozenset
    scope_events: tuple
    estimated_bytes: int


def capture_page_evidence_v318(structure):
    """Capture bounded reader-free summaries only after full link validation."""
    from .analysis_reuse_v315 import _freeze, _UnsupportedAst
    if len(structure.marks) > _MAX_PAGES:
        return ()
    remaining = _EVIDENCE_BYTES
    result = []
    for number, marks in enumerate(structure.marks):
        checkpoint()
        budget = [0, 8 * len(structure.contexts[number]) + 192 * len(marks)]
        try:
            records = tuple((mcid, _freeze(mark.tag, budget),
                             _freeze(mark.properties, budget), _freeze(mark.resolved, budget),
                             mark.start, mark.end, mark.paints, mark.nested_actual)
                            for mcid, mark in marks.items())
            operations = structure.operations[number]
            events = (operations.scope_events_v318()
                      if isinstance(operations, LazyPageOperationsV318) else None)
            if events is None:
                events = tuple((operator, str(args[0]) if operator == b'Do' and args else None)
                               for args, operator in operations if operator in (b'BT', b'ET', b'Do'))
            budget[1] += sum(96 + (4 * len(name) if name is not None else 0)
                             for _, name in events)
            if budget[1] > remaining:
                result.append(None)
                continue
            artifacts = frozenset(item['mcid'] for item in structure.source_irregularities
                if item.get('kind') == 'detached_graphical_artifact' and item.get('page') == number)
            result.append(_PageEvidence(records, tuple(structure.contexts[number]),
                                        len(operations), artifacts, events, budget[1]))
            remaining -= budget[1]
        except _UnsupportedAst:
            # Indirect properties, unknown operand types and over-budget
            # records retain the ordinary independent parsing path.
            result.append(None)
    return tuple(result)


class PageSemanticReuseV318:
    def __init__(self, data):
        reference = _reference.get()
        if reference is None:
            # Mutable planners still get a fresh reader and structure tree.
            # Their page syntax may come from an immutable previously checked
            # source, never from another mutable planner or expected snapshot.
            from . import tagged
            pin = tagged._active_source_pin.get()
            if pin is not None and pin is tagged._pinned_source_cache:
                reference = (pin[1], None)
            elif tagged._readonly_cache is not None and tagged._readonly_cache[2] is None:
                reference = (tagged._readonly_cache[1], None)
        self.source, self.mapping = reference or (None, None)
        self.proof = None
        if self.source is not None and getattr(self.source, '_page_evidence_v318', None):
            self.proof = _SyntaxProof(self.source.data, data)

    def install(self, candidate, number, page):
        source = self.source
        source_number = number if self.mapping is None else self.mapping.get(number)
        if (self.proof is None or source_number is None
                or not 0 <= source_number < len(source._page_evidence_v318)):
            return False
        evidence = source._page_evidence_v318[source_number]
        if evidence is None or not self.proof.unchanged(source_number, number):
            return False
        from .analysis_reuse_v315 import _thaw
        from .tagged import Mark, _integer, fail
        marks = {record[0]: Mark(record[0], _thaw(record[1]), _thaw(record[2]),
                                _thaw(record[3]), *record[4:]) for record in evidence.marks}
        if marks:
            key = _integer(page.get('/StructParents'), 'StructParents de página')
            if key in candidate.page_parent_keys:
                fail('dos páginas comparten una clave StructParents.')
            candidate.page_parent_keys[key] = number
        candidate.operations.append(LazyPageOperationsV318(candidate.reader, number,
                                                          evidence.operations, evidence.scope_events))
        candidate.marks.append(marks)
        candidate.contexts.append(evidence.contexts)
        candidate._reused_graphical_artifacts_v318.update((number, mcid)
                                                        for mcid in evidence.graphical_artifacts)
        candidate.reused_semantic_pages_v318.add(number)
        return True
