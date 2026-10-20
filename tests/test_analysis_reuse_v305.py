"""Exact revision reuse retains independent validation and private evidence."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, TextStringObject

from pdfmodder import tagged, page_fingerprint as fingerprints
from pdfmodder.draft_control_v305 import DraftCancelled, DraftControl, controlled_draft
from pdfmodder.media import _isolate_existing_content
from pdfmodder.model import EditError
from pdfmodder.tagged_insert import TaggedAddition
from tagged_corpus import make_tagged_pdf
from test_page_fingerprint import corpus, numbers
from test_engine import select


@pytest.fixture(autouse=True)
def empty_evidence():
    tagged.clear_readonly_cache()
    yield
    tagged.clear_readonly_cache()


def counted_analysis(monkeypatch):
    calls=[]
    original=tagged.analyze
    def analyze(data):
        calls.append(sha256(data).digest())
        return original(data)
    monkeypatch.setattr(tagged,'analyze',analyze)
    return calls


def write_change(source, change):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    change(writer)
    stream=BytesIO();writer.write(stream)
    return stream.getvalue()


def test_different_drafts_reuse_source_without_evicting_commit_candidate(monkeypatch):
    source=make_tagged_pdf();candidate=make_tagged_pdf(named_properties=True)
    second=make_tagged_pdf(mixed_styles=True)
    calls=counted_analysis(monkeypatch)
    with tagged.pin_source_analysis(source):
        original=tagged.analyze_readonly(source)
        checked=tagged.analyze_readonly(candidate)
    assert tagged.analyze_readonly(candidate) is checked
    with tagged.pin_source_analysis(source):
        assert tagged.analyze_readonly(source) is original
        assert tagged.analyze_readonly(second) is not original
    assert calls.count(sha256(source).digest())==1
    assert len(calls)==3
    assert tagged._pinned_source_cache[1] is original


def test_new_revision_replaces_source_pin_and_budget_remains_bounded():
    assert tagged._READONLY_CACHE_BUDGET==160*1024*1024
    source=make_tagged_pdf();other=make_tagged_pdf(named_properties=True)
    with tagged.pin_source_analysis(source):
        first=tagged.analyze_readonly(source)
    with tagged.pin_source_analysis(other):
        current=tagged.analyze_readonly(other)
    assert tagged._pinned_source_cache[1] is current
    assert current is not first
    assert tagged._pinned_source_cache[0][0]==sha256(other).digest()
    assert tagged._readonly_size(current)<=tagged._READONLY_CACHE_BUDGET


def test_over_budget_source_falls_back_to_complete_analysis(monkeypatch):
    monkeypatch.setattr(tagged,'_READONLY_CACHE_BUDGET',1)
    source=make_tagged_pdf();calls=counted_analysis(monkeypatch)
    with tagged.pin_source_analysis(source):
        first=tagged.analyze_readonly(source)
        second=tagged.analyze_readonly(source)
    assert first is not second
    assert tagged._pinned_source_cache is None
    assert tagged._readonly_cache is None
    assert len(calls)==3


def test_buffer_change_and_unrelated_output_tags_cannot_inherit_source_evidence():
    source=bytearray(make_tagged_pdf())
    with tagged.pin_source_analysis(source):
        checked=tagged.analyze_readonly(source)
        position=source.index(b'/StructParents 0')
        source[position:position+len(b'/StructParents 0')]=b'/StructParents 9'
        with pytest.raises(EditError,match='ParentTree'):
            tagged.analyze_readonly(source)
        changed=write_change(checked.data,lambda w:w.root_object['/StructTreeRoot']['/K']['/K'][0].__setitem__(
            NameObject('/Alt'),TextStringObject('Changed alternate text')))
        with pytest.raises(EditError,match='cambios ajenos'):
            tagged.assert_structure(checked.data,changed)


def test_mutable_planner_and_caller_semantic_snapshot_do_not_contaminate_pin():
    source=make_tagged_pdf()
    with tagged.pin_source_analysis(source):
        checked=tagged.analyze_readonly(source)
        before=checked.semantic()
        caller_snapshot=checked.semantic()
        caller_snapshot['catalog']['/Lang']='other'
        caller_snapshot['nodes'].clear()
        addition=TaggedAddition(source,0,'/P','page_end',text='Private paragraph')
        assert addition.structure is not checked
        with fitz.open(stream=source,filetype='pdf') as document:
            _isolate_existing_content(document,document[0])
            old=document[0].get_contents()
            document[0].insert_text((48,350),'Private paragraph')
            addition.apply(document,old)
        assert addition.structure.semantic()!=before
        assert checked.semantic()==before
        model,chosen=select(source,'10/09/2026',x=100,y=100)
        guard=tagged.TaggedEdit(checked,0,model,chosen,chosen,chosen,True)
        guard.expected['nodes'].clear()
        assert checked.semantic()==before
    with tagged.pin_source_analysis(source):
        assert tagged.analyze_readonly(source).semantic()==before


def test_session_release_discards_only_matching_source_and_page_evidence():
    source=make_tagged_pdf();other=make_tagged_pdf(named_properties=True)
    with tagged.pin_source_analysis(source):
        tagged.analyze_readonly(other)
    assert fingerprints.PageProof(source,source).unchanged(1)
    tagged.clear_readonly_cache('unrelated')
    assert tagged._pinned_source_cache is not None
    assert fingerprints._page_cache
    tagged.clear_readonly_cache(sha256(source).hexdigest())
    assert tagged._pinned_source_cache is None
    assert all(key[0]!=sha256(source).digest() for key in fingerprints._page_cache)
    # The latest independently checked candidate remains available for commit.
    assert tagged._readonly_cache[0][0]==sha256(other).digest()
    tagged.clear_readonly_cache()
    assert not fingerprints._page_cache
    assert tagged._readonly_cache is tagged._readonly_verdict is None


def test_completed_page_proofs_reuse_digests_without_sharing_readers(monkeypatch):
    source=corpus();rewritten=corpus(compressed=True,garbage=7)
    calls=[];original=fingerprints._Graph.__init__
    def construct(self,*args,**kwargs):
        calls.append(self)
        original(self,*args,**kwargs)
    monkeypatch.setattr(fingerprints._Graph,'__init__',construct)
    first=fingerprints.PageProof(source,rewritten)
    assert first.unchanged(0) and first.unchanged(1)
    assert len(calls)==2
    second=fingerprints.PageProof(source,rewritten)
    assert second.unchanged(0) and second.unchanged(1)
    assert len(calls)==2
    assert all(revision.graph is None for revision in second._graphs)
    caller_report=second.report(0);caller_report['fingerprint']='forged'
    caller_report['verified_ink_regions'].append('forged')
    assert second.report(0)==first.report(0)


def test_page_proof_caller_graph_mutation_cannot_change_completed_cache():
    source=corpus()
    proof=fingerprints.PageProof(source,source)
    assert proof.unchanged(0)
    before=proof.report(0)
    proof._graphs[0].graph.pages[0][NameObject('/Rotate')]=NumberObject(90)
    reused=fingerprints.PageProof(source,source)
    assert reused.report(0)==before


@pytest.mark.parametrize('change',[
    lambda o:o['font'].__setitem__(NameObject('/Widths'),numbers(700)),
    lambda o:o['contents'].set_data(b'BT /F1 12 Tf 10 50 Td (B) Tj ET'),
    lambda o:o['parent'].__setitem__(NameObject('/MediaBox'),numbers(0,0,120,120)),
])
def test_warm_proof_detects_resource_content_and_cross_page_inheritance_changes(change):
    source=corpus(inherited=True)
    assert fingerprints.PageProof(source,source).unchanged(0)
    changed=corpus(inherited=True,mutate=change)
    proof=fingerprints.PageProof(source,changed)
    assert not proof.unchanged(0) and not proof.unchanged(1)


def test_proof_budget_options_bind_cache_and_cache_itself_is_bounded(monkeypatch):
    source=corpus()
    assert fingerprints.PageProof(source,source).unchanged(0)
    assert not fingerprints.PageProof(source,source,max_nodes=1).unchanged(0)
    monkeypatch.setattr(fingerprints,'_PAGE_CACHE_MAX_REVISIONS',2)
    monkeypatch.setattr(fingerprints,'_PAGE_CACHE_BUDGET',1800)
    for amount in range(4):
        data=corpus(garbage=amount)
        assert fingerprints.PageProof(data,data).unchanged(0)
    assert len(fingerprints._page_cache)<=2
    assert fingerprints._page_cache_bytes<=1800


def test_proof_matching_and_writable_input_use_complete_revision_identity():
    source=bytearray(corpus());frozen=bytes(source)
    proof=fingerprints.PageProof(source,source)
    assert proof.unchanged(0) and proof.matches(source,source)
    at=source.index(b'/Rotate 0') if b'/Rotate 0' in source else source.index(b'/Count 2')
    source[at:at+1]=b'!'
    assert not proof.matches(source,frozen)
    assert proof.matches(frozen,frozen)
    assert fingerprints.PageProof(frozen,frozen).unchanged(0)


def test_cancellation_is_not_swallowed_into_no_proof_or_published_partial_cache(monkeypatch):
    source=corpus()
    control=DraftControl();ticket=control.ticket()
    try:
        with controlled_draft(ticket):
            proof=fingerprints.PageProof(source,source)
            control.invalidate()
            with pytest.raises(DraftCancelled):
                proof.unchanged(0)
        assert all(not entry[1] for entry in fingerprints._page_cache.values())
    except DraftCancelled:
        pass  # The context also checks after yielding, by design.
    finally:
        control.close()
    assert fingerprints.PageProof(source,source).unchanged(0)


def test_release_inside_scope_cannot_resurrect_a_cleared_source_pin(monkeypatch):
    source=make_tagged_pdf();calls=counted_analysis(monkeypatch)
    with tagged.pin_source_analysis(source):
        original=tagged.analyze_readonly(source)
        tagged.clear_readonly_cache()
        assert tagged.analyze_readonly(source) is not original
    assert len(calls)==2 and tagged._pinned_source_cache is None


def test_cancelled_source_analysis_is_not_published_as_verified_cache(monkeypatch):
    source=make_tagged_pdf();control=DraftControl();ticket=control.ticket()
    original=tagged.analyze
    def cancelled(data):
        result=original(data)
        control.invalidate()
        return result
    monkeypatch.setattr(tagged,'analyze',cancelled)
    try:
        with pytest.raises(DraftCancelled):
            with controlled_draft(ticket):
                with tagged.pin_source_analysis(source):
                    pytest.fail('A cancelled analysis cannot enter the scope')
        assert tagged._readonly_cache is None
        assert tagged._readonly_verdict is None
        assert tagged._pinned_source_cache is None
    finally:
        control.close()
