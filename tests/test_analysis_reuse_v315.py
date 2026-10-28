"""Only exact, successful native resource probes can be reused per command."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream, NameObject, DictionaryObject, IndirectObject

from pdfmodder.analysis_reuse_v315 import (AnalysisCacheV315, analysis_scope_v315,
                                          page_operations_v315)
from pdfmodder.clipping import operator_glyph_map, _signature
from pdfmodder.draft_control_v305 import (DraftCancelled, DraftControl,
                                        controlled_draft)
from pdfmodder.engine import extract_page
from pdfmodder.model import EditError


def source():
    with fitz.open() as doc:
        page = doc.new_page(width=240, height=180)
        page.insert_text((20, 50), 'Native resource probe')
        data = doc.tobytes()
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0)
    return data, model


def counted_probe(monkeypatch):
    import pdfmodder.clipping as clipping
    original = clipping._serialize
    calls = []

    def serialize(operations):
        calls.append(True)
        return original(operations)

    monkeypatch.setattr(clipping, '_serialize', serialize)
    return calls


def test_annotation_reuses_evidence_but_never_mutable_pdf_objects(monkeypatch):
    data, model = source()
    calls = counted_probe(monkeypatch)
    with analysis_scope_v315():
        first = operator_glyph_map(data, 0, model)
        enriched = replace(model, glyphs=[replace(g, font_xref=first[3][g.id]['font_xref'],
                                                 font_resource=first[3][g.id]['font_resource'])
                                         for g in model.glyphs])
        first[1].clear()
        first[2][0]['font'][NameObject('/BaseFont')] = NameObject('/Tampered')
        first[2][0]['glyphs'].clear()
        first[3].clear()
        second = operator_glyph_map(data, 0, enriched)
        assert second[1]
        assert second[2][0]['font']['/BaseFont'] == '/Helvetica'
        assert second[2][0]['glyphs'][0] is enriched.glyphs[0]
        assert len(second[3]) == len(model.glyphs)
    assert len(calls) == 1
    # The command lifetime has ended; no proof remains in global state.
    with analysis_scope_v315():
        operator_glyph_map(data, 0, model)
    assert len(calls) == 2


def test_changed_bytes_or_trace_model_require_a_new_probe(monkeypatch):
    data, model = source()
    calls = counted_probe(monkeypatch)
    with analysis_scope_v315():
        operator_glyph_map(data, 0, model)
        changed = replace(model, glyphs=[replace(g, seqno=g.seqno + 1)
                                        for g in model.glyphs])
        operator_glyph_map(data, 0, changed)
        with fitz.open(stream=data, filetype='pdf') as doc:
            doc.set_metadata({'title': 'New immutable revision'})
            newer = doc.tobytes()
        operator_glyph_map(newer, 0, model)
    assert len(calls) == 3


def test_failed_resource_probe_is_never_remembered(monkeypatch):
    data, model = source()
    calls = counted_probe(monkeypatch)
    wrong = replace(model, glyphs=[replace(g, origin=(g.origin[0] + 10, g.origin[1]))
                                  for g in model.glyphs])
    with analysis_scope_v315():
        for _ in range(2):
            with pytest.raises(EditError, match='sondeo no conserva'):
                operator_glyph_map(data, 0, wrong)
        operator_glyph_map(data, 0, model)
    assert len(calls) == 3


def test_a_cached_probe_still_obeys_immediate_draft_cancellation(monkeypatch):
    data, model = source()
    calls = counted_probe(monkeypatch)
    control = DraftControl()
    try:
        with analysis_scope_v315(), controlled_draft(control.ticket()):
            operator_glyph_map(data, 0, model)
            control.invalidate()
            with pytest.raises(DraftCancelled):
                operator_glyph_map(data, 0, model)
            # controlled_draft checks on exit, too.
            raise DraftCancelled('Cancelled at the next safe checkpoint')
    except DraftCancelled:
        pass
    finally:
        control.close()
    assert len(calls) == 1


def syntax_source(contents):
    with fitz.open() as doc:
        page = doc.new_page(width=240, height=180)
        xref = doc.get_new_xref()
        doc.update_object(xref, '<<>>')
        doc.update_stream(xref, contents)
        page.set_contents(xref)
        return doc.tobytes()


def count_syntax(monkeypatch):
    calls = []
    original = ContentStream._parse_content_stream

    def parse(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContentStream, '_parse_content_stream', parse)
    return calls


def test_primitive_syntax_snapshot_restores_independent_exact_operands(monkeypatch):
    data = syntax_source(b'q 1.123456789123 0 0 1 -4.5 20 cm\n'
                         b'/Span << /ActualText <FEFF0041> /Data [true false null 45] >> BDC\n'
                         b'BT /F1 12 Tf [(text) <00FF> -4.3456789123] TJ ET EMC Q')
    calls = count_syntax(monkeypatch)
    with analysis_scope_v315():
        first = page_operations_v315(data, 0, PdfReader(BytesIO(data), strict=True))
        expected = _signature(first)
        first[0][0].append(NameObject('/Corruption'))
        first[-2][0].clear()
        second = page_operations_v315(data, 0, PdfReader(BytesIO(data), strict=True))
        assert _signature(second) == expected
    assert len(calls) == 1


def test_reader_bound_indirect_syntax_is_never_cached(monkeypatch):
    import pdfmodder.analysis_reuse_v315 as reuse
    data, _ = source()
    calls = []

    class ReferenceSyntax:
        # Current pypdf rejects indirect refs in stream syntax. This guard
        # also covers a future parser which accepts reader-bound operands.
        def __init__(self, stream, reader):
            self.reader = reader
            self.boundary=b'PDFModderScopeBoundaryV316' in stream.get_data()

        def get_data(self):
            return b'Reader-bound operand test'

        @property
        def operations(self):
            calls.append(self.boundary)
            return [([NameObject('/Span'), DictionaryObject({NameObject('/Reference'):
                     IndirectObject(1, 0, self.reader)})], b'BDC')]

    monkeypatch.setattr(reuse, 'ContentStream', ReferenceSyntax)
    with analysis_scope_v315():
        first_reader = PdfReader(BytesIO(data), strict=True)
        first = page_operations_v315(data, 0, first_reader)
        second_reader = PdfReader(BytesIO(data), strict=True)
        second = page_operations_v315(data, 0, second_reader)
        assert first[0][0][1].raw_get('/Reference').pdf is first_reader
        assert second[0][0][1].raw_get('/Reference').pdf is second_reader
    assert calls.count(False) == 2


def test_syntax_budget_falls_back_to_fresh_parser(monkeypatch):
    import pdfmodder.analysis_reuse_v315 as reuse
    data, _ = source()
    calls = count_syntax(monkeypatch)
    monkeypatch.setattr(reuse, '_MAX_AST_NODES', 1)
    with analysis_scope_v315():
        page_operations_v315(data, 0, PdfReader(BytesIO(data), strict=True))
        first_count=len(calls)
        page_operations_v315(data, 0, PdfReader(BytesIO(data), strict=True))
    # The cached boundary summary cannot replace fresh operand parsing when
    # the AST exceeds its budget. Initial boundary verification is separate.
    assert len(calls)==first_count+1


def test_permissive_syntax_cannot_satisfy_strict_validation(monkeypatch):
    data=syntax_source(b'/Span << /ActualText (first) /ActualText (second) >> BDC EMC')
    calls=count_syntax(monkeypatch)
    with analysis_scope_v315():
        page_operations_v315(data,0,PdfReader(BytesIO(data),strict=False))
        page_operations_v315(data,0,PdfReader(BytesIO(data),strict=True))
    assert len(calls)==2


def test_explicit_session_cache_survives_commands_and_releases_on_clear(monkeypatch):
    data, model = source()
    calls = counted_probe(monkeypatch)
    cache = AnalysisCacheV315()
    for _ in range(2):
        with analysis_scope_v315(cache):
            operator_glyph_map(data, 0, model)
    assert len(calls) == 1
    cache.clear()
    with analysis_scope_v315(cache):
        operator_glyph_map(data, 0, model)
    assert len(calls) == 2
