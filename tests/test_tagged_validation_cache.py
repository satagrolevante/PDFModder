"""Advisory reuse preserves revision identity and private transaction models."""
import pymupdf as fitz
import pytest

from pdfmodder import tagged
from pdfmodder.media import _isolate_existing_content
from pdfmodder.model import EditError
from pdfmodder.tagged_insert import TaggedAddition
from pdfmodder.tagged_pages import page_capabilities, preflight
from pdfmodder.validation import document_issues, page_issues
from tagged_corpus import make_tagged_pdf


@pytest.fixture(autouse=True)
def private_cache(monkeypatch):
    monkeypatch.setattr(tagged, '_readonly_cache', None)
    monkeypatch.setattr(tagged, '_readonly_verdict', None)


def counted_structures(monkeypatch):
    calls = []
    original = tagged.TaggedStructure

    def construct(data):
        calls.append(data)
        return original(data)

    monkeypatch.setattr(tagged, 'TaggedStructure', construct)
    return calls


def test_document_page_and_advisory_page_checks_share_one_analysis(monkeypatch):
    source = make_tagged_pdf(include_objr=True)
    calls = counted_structures(monkeypatch)
    with fitz.open(stream=source, filetype='pdf') as document:
        assert document_issues(source, document, operation='content') == []
    assert page_issues(source, 0) == []
    assert page_capabilities(source)['delete']
    assert preflight(source, readonly=True) is tagged.analyze_readonly(source)
    assert len(calls) == 1


def test_mutated_same_size_buffer_cannot_inherit_valid_revision(monkeypatch):
    buffer = bytearray(make_tagged_pdf())
    calls = counted_structures(monkeypatch)
    original = tagged.analyze_readonly(buffer)
    original_semantics = original.semantic()
    position = buffer.index(b'/StructParents 0')
    buffer[position:position + len(b'/StructParents 0')] = b'/StructParents 9'
    assert len(buffer) == len(original.data)
    for _ in range(2):
        with pytest.raises(EditError, match='ParentTree'):
            tagged.analyze_readonly(buffer)
    assert len(calls) == 2
    assert original.semantic() == original_semantics
    assert isinstance(tagged._readonly_cache[2], str)
    with fitz.open(stream=bytes(buffer), filetype='pdf') as document:
        assert any('ParentTree' in issue for issue in
                   document_issues(bytes(buffer), document, operation='content'))
    assert len(calls) == 2


def test_cache_keeps_only_the_latest_revision(monkeypatch):
    first = make_tagged_pdf()
    second = make_tagged_pdf(named_properties=True)
    calls = counted_structures(monkeypatch)
    earlier = tagged.analyze_readonly(first)
    latest = tagged.analyze_readonly(second)
    assert tagged._readonly_cache[1] is latest
    assert tagged.analyze_readonly(first) is not earlier
    assert len(calls) == 3


def test_mutable_addition_uses_a_private_structure():
    source = make_tagged_pdf(include_objr=True)
    cached = tagged.analyze_readonly(source)
    before = cached.semantic()
    addition = TaggedAddition(source, 0, '/P', 'page_end', text='Nuevo parrafo')
    assert addition.structure is not cached
    with fitz.open(stream=source, filetype='pdf') as document:
        _isolate_existing_content(document, document[0])
        old_contents = document[0].get_contents()
        document[0].insert_text((48, 350), 'Nuevo parrafo')
        addition.apply(document, old_contents)
    assert addition.structure.semantic() != before
    assert tagged.analyze_readonly(source) is cached
    assert cached.semantic() == before
    assert preflight(source) is not cached


def test_over_budget_analysis_is_not_retained(monkeypatch):
    first = make_tagged_pdf()
    cached = tagged.analyze_readonly(first)
    assert tagged._readonly_cache[1] is cached
    monkeypatch.setattr(tagged, '_READONLY_CACHE_BUDGET', 1)
    source = make_tagged_pdf(named_properties=True)
    calls = counted_structures(monkeypatch)
    first_large = tagged.analyze_readonly(source)
    assert tagged._readonly_size(first_large) > tagged._READONLY_CACHE_BUDGET
    assert tagged._readonly_cache is None
    assert tagged.analyze_readonly(source) is not first_large
    assert len(calls) == 2


def test_over_budget_verdict_avoids_repeated_document_and_page_analysis(monkeypatch):
    monkeypatch.setattr(tagged, '_READONLY_CACHE_BUDGET', 1)
    source = make_tagged_pdf(include_objr=True)
    calls = counted_structures(monkeypatch)
    for _ in range(2):
        with fitz.open(stream=source, filetype='pdf') as document:
            assert document_issues(source, document, operation='content') == []
        assert page_issues(source, 0) == []
    assert len(calls) == 1 and tagged._readonly_cache is None
    assert tagged.validate_tagged(source)
    # A verdict is not a structure; node-based checks still parse privately.
    assert preflight(source, readonly=True).nodes
    assert len(calls) == 2 and tagged._readonly_cache is None


def test_over_budget_invalid_verdict_is_cached_without_structure(monkeypatch):
    monkeypatch.setattr(tagged, '_READONLY_CACHE_BUDGET', 1)
    buffer = bytearray(make_tagged_pdf())
    assert tagged.validate_tagged(buffer)
    position = buffer.index(b'/StructParents 0')
    buffer[position:position + len(b'/StructParents 0')] = b'/StructParents 9'
    calls = counted_structures(monkeypatch)
    for _ in range(2):
        with pytest.raises(EditError, match='ParentTree'):
            tagged.validate_tagged(buffer)
    assert len(calls) == 1 and tagged._readonly_cache is None
    assert isinstance(tagged._readonly_verdict[2], str)


def test_cache_release_matches_only_the_requested_revision(monkeypatch):
    from hashlib import sha256
    source = make_tagged_pdf()
    structure = tagged.analyze_readonly(source)
    tagged.clear_readonly_cache('another-revision')
    assert tagged.analyze_readonly(source) is structure
    tagged.clear_readonly_cache(sha256(source).hexdigest())
    assert tagged._readonly_cache is tagged._readonly_verdict is None
    assert tagged.analyze_readonly(source) is not structure
    tagged.clear_readonly_cache()
    assert tagged._readonly_cache is tagged._readonly_verdict is None


def test_untagged_revision_remains_untagged():
    with fitz.open() as document:
        document.new_page().insert_text((50, 75), 'Ordinary text')
        source = document.tobytes()
    assert tagged.analyze_readonly(source) is None
    with pytest.raises(EditError, match='estructura accesible'):
        preflight(source, readonly=True)
