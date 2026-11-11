"""Candidate structure is rebuilt while exact unchanged page syntax is reused."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject, DictionaryObject

from pdfmodder import tagged
from pdfmodder.model import EditError
from pdfmodder.tagged_reuse_v318 import LazyPageOperationsV318
from tagged_corpus import make_tagged_pdf


@pytest.fixture(autouse=True)
def clear_caches():
    tagged.clear_readonly_cache()
    yield
    tagged.clear_readonly_cache()


def test_candidate_uses_own_reader_and_reuses_only_unchanged_pages():
    source = make_tagged_pdf()
    original = tagged.analyze_readonly(source)
    with fitz.open(stream=source, filetype='pdf') as document:
        document[0].insert_text((40, 350), 'Unmarked artifact')
        stream = document[0].get_contents()[-1]
        document.update_stream(stream, b'/Artifact BMC\n' + document.xref_stream(stream) + b'\nEMC\n')
        output = document.tobytes(garbage=0)
    candidate = tagged.analyze_readonly(output)
    assert candidate.reader is not original.reader
    assert candidate.reused_semantic_pages_v318 == {1}
    assert isinstance(candidate.operations[1], LazyPageOperationsV318)
    assert candidate.operations[1].reader is candidate.reader
    assert candidate.operations[1]._operations is None
    assert list(candidate.operations[1]) == list(original.operations[1])


def test_global_accessibility_changes_are_detected_even_when_all_pages_are_proven():
    source = make_tagged_pdf()
    tagged.analyze_readonly(source)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    writer.root_object['/StructTreeRoot']['/K']['/K'][0].get_object()[NameObject('/Alt')] = TextStringObject('Changed semantics')
    result = BytesIO(); writer.write(result)
    output = result.getvalue()
    candidate = tagged.analyze_readonly(output)
    # The first page's image has conservative unsupported filter metadata;
    # the control page still takes the proof path. The tree always rebuilds.
    assert 1 in candidate.reused_semantic_pages_v318
    with pytest.raises(EditError, match='cambios ajenos'):
        tagged.assert_structure(source, output)


def test_readonly_semantic_snapshot_is_private_to_each_consumer():
    structure = tagged.analyze_readonly(make_tagged_pdf())
    expected = structure.semantic()
    altered = structure.semantic()
    altered['marks'][0].clear()
    assert structure.semantic() == expected


def test_semantic_snapshots_contain_no_pdf_scalars_or_foreign_readers():
    structure = tagged.analyze_readonly(make_tagged_pdf(named_properties=True))
    def primitive(value):
        assert type(value) in (dict, tuple, list, str, bytes, int, float, bool, type(None))
        if isinstance(value, dict):
            for key, item in value.items():
                primitive(key); primitive(item)
        elif isinstance(value, (tuple, list)):
            for item in value: primitive(item)
    primitive(structure.semantic())


def test_reused_scope_events_preserve_the_source_state_machine_inputs():
    source = make_tagged_pdf()
    original = tagged.analyze_readonly(source)
    planner = tagged.analyze(source)
    operations = planner.operations[1]
    assert isinstance(operations, LazyPageOperationsV318)
    expected = tuple((op, str(args[0]) if op == b'Do' and args else None)
                     for args, op in original.operations[1] if op in (b'BT', b'ET', b'Do'))
    assert operations.scope_events_v318() == expected
    assert operations._operations is None


def test_over_budget_evidence_uses_full_page_parsing(monkeypatch):
    from pdfmodder import tagged_reuse_v318
    monkeypatch.setattr(tagged_reuse_v318, '_EVIDENCE_BYTES', 0)
    source = make_tagged_pdf()
    tagged.analyze_readonly(source)
    with fitz.open(stream=source, filetype='pdf') as document:
        document.set_metadata({'title': 'Same pages, fresh snapshot'})
        output = document.tobytes(garbage=0)
    assert not tagged.analyze_readonly(output).reused_semantic_pages_v318


def test_mutable_planner_has_private_tree_with_checked_source_page_evidence():
    source = make_tagged_pdf()
    original = tagged.analyze_readonly(source)
    planner = tagged.analyze(source)
    assert planner is not original and planner.reader is not original.reader
    assert 1 in planner.reused_semantic_pages_v318
    next(iter(planner.nodes.values()))[NameObject('/Alt')] = TextStringObject('Private planned update')
    assert planner.semantic() != original.semantic()


def test_global_form_changes_do_not_invalidate_page_syntax_evidence():
    from pdfmodder.page_fingerprint import PageProof
    from pdfmodder.tagged_reuse_v318 import _SyntaxProof
    source = make_tagged_pdf()
    tagged.analyze_readonly(source)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    writer.root_object[NameObject('/AcroForm')] = DictionaryObject()
    result = BytesIO(); writer.write(result)
    output = result.getvalue()
    assert not PageProof(source, output).unchanged(1)
    syntax = _SyntaxProof(source, output)
    assert syntax.unchanged(1, 1)
    with pytest.raises(TypeError, match='renderer'):
        syntax.report(1, 1)
    assert 1 in tagged.analyze_readonly(output).reused_semantic_pages_v318


def test_changed_page_with_unmarked_text_never_reuses_old_contexts():
    source = make_tagged_pdf()
    original = tagged.analyze_readonly(source)
    with fitz.open(stream=source, filetype='pdf') as document:
        document[1].insert_text((40, 350), 'Untagged unexpected text')
        output = document.tobytes(garbage=0)
    candidate = tagged.analyze_readonly(output)
    assert 1 not in candidate.reused_semantic_pages_v318
    assert len(candidate.contexts[1]) > len(original.contexts[1])
    assert {'kind':'unmarked_text','page':1,'shows':1} in candidate.source_irregularities
    assert candidate.semantic()==original.semantic()
