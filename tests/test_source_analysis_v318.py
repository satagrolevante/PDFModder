"""Complete worker writes retain source evidence without reparsing candidates."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from pdfmodder import tagged, tagged_insert
from pdfmodder.clipboard_ops_v170 import apply_clipboard_v170
from pdfmodder.composition import AddTextRequest
from pdfmodder.model import EditError, EditRequest
from pdfmodder.worker import Session
from tagged_corpus import make_tagged_pdf


@pytest.fixture(autouse=True)
def private_tagged_cache():
    tagged.clear_readonly_cache()
    yield
    tagged.clear_readonly_cache()


def create_session(tmp_path, *, reading=False):
    source = tmp_path/'tagged.pdf'
    source.write_bytes(make_tagged_pdf())
    return Session(source, reading=reading, history_dir=tmp_path/'history',
                   config_path=tmp_path/'fonts.json')


def selected_word(session):
    model = session.page(0)['model']
    text = ''.join(g.text for g in model.glyphs)
    start = text.index('PALABRA')
    return [g.id for g in model.glyphs[start:start+len('PALABRA')]]


@pytest.mark.parametrize('operation', ['move', 'delete', 'insert', 'image'])
def test_actual_worker_writes_parse_each_exact_candidate_once(tmp_path, monkeypatch, operation):
    session = create_session(tmp_path)
    original = session.history.current
    ids = selected_word(session)
    source_structure = tagged.analyze_readonly(original)
    calls = []
    ordinary_analyze = tagged.analyze
    # A mutable planner keeps its ordinary constructor, even if this module
    # first gets imported while the read-only cache miss counter is active.
    monkeypatch.setattr(tagged_insert, 'analyze', ordinary_analyze)
    def analyze(data):
        calls.append(bytes(data))
        return ordinary_analyze(data)
    monkeypatch.setattr(tagged, 'analyze', analyze)
    try:
        if operation == 'delete':
            result = apply_clipboard_v170(session, 'delete', 0, ids=ids,
                                          revision=session.history.revision)
            candidate = session.history.current
        else:
            if operation == 'move':
                result = session.preview(EditRequest(0, ids, dx=3, dy=3,
                    allow_overlap=True, revision=session.history.revision))
            elif operation == 'insert':
                result = session.insert_text(AddTextRequest(0, 48, 350, 240, 30,
                    'Nuevo texto', accessibility_order='page_end', revision=session.history.revision))
            else:
                buffer = BytesIO()
                Image.new('RGB', (20, 12), '#184d75').save(buffer, format='PNG')
                result = session.image_operation('add', 0, rect=(160, 260, 200, 284),
                    image_bytes=buffer.getvalue(), accessibility_order='page_end',
                    alt_text='Figura nueva', revision=session.history.revision)
            candidate = session.pending
            session.commit()
        assert result['report']['verified']
        assert candidate != original
        # Each output still receives an independent checked structure. Repeated
        # semantic/accessibility checks and state publication share that graph.
        assert calls.count(candidate) == 1
        # Mutable TaggedAddition planners remain outside this read-only cache
        # miss counter and continue to reconstruct their private source trees.
        assert original not in calls
        assert tagged._readonly_cache[1].data == candidate
        assert tagged._readonly_cache[1].reader is not source_structure.reader
        assert tagged._pinned_source_cache[1] is source_structure
        assert session._analysis_source_revision_v305 == sha256(original).hexdigest()
        assert session.history.index == 1
        assert Path(session.path).read_bytes() == original
    finally:
        session.close()
    # Closing a committed revision must release its earlier source pin too.
    assert tagged._pinned_source_cache is None
    assert tagged._readonly_cache is None


@pytest.mark.parametrize('operation', ['move', 'delete', 'insert', 'image', 'object'])
def test_reading_rejects_writes_before_any_source_analysis(tmp_path, monkeypatch, operation):
    session = create_session(tmp_path, reading=True)
    def unexpected(*args, **kwargs):
        pytest.fail('Reading and rejected writes must not analyze the tagged source')
    monkeypatch.setattr(tagged, 'pin_source_analysis', unexpected)
    try:
        assert session.page(0, reading=True)['model'].glyphs
        with pytest.raises(EditError, match='Activa las herramientas'):
            if operation == 'move':
                session.preview(EditRequest(0, [0], dx=3))
            elif operation == 'delete':
                apply_clipboard_v170(session, 'delete', 0, ids=[0])
            elif operation == 'insert':
                session.insert_text(AddTextRequest(0, 48, 350, 240, 30, 'Nuevo texto'))
            elif operation == 'image':
                session.image_operation('add', 0)
            else:
                session.object_operation(0, 'group', items=[])
        assert session.history.index == 0 and session.pending is None
    finally:
        session.close()


def test_invalid_write_releases_active_pin_without_committing(tmp_path):
    session = create_session(tmp_path)
    original = session.history.current
    try:
        with pytest.raises(EditError, match='desconocida'):
            session.image_operation('invalid', 0)
        assert tagged._active_source_pin.get() is None
        assert session.history.current == original and session.history.index == 0
        assert session.pending is None
    finally:
        session.close()
    assert tagged._pinned_source_cache is None


def test_ineligible_source_keeps_the_complete_independent_fallback(tmp_path, monkeypatch):
    from pdfmodder.source_analysis_v318 import session_source_analysis_v318
    session = create_session(tmp_path)
    monkeypatch.setattr(tagged, '_READONLY_CACHE_BUDGET', 0)
    tagged.clear_readonly_cache()
    try:
        with session_source_analysis_v318(session):
            assert tagged._active_source_pin.get() is None
            assert tagged._pinned_source_cache is None
            assert tagged.analyze_readonly(session.history.current).data == session.history.current
        assert tagged._readonly_cache is None
    finally:
        session.close()
