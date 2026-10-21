"""Search uses the displayed immutable source and never changes a PDF session."""
import pymupdf as fitz
import pytest

from pdfmodder import worker
from pdfmodder.draft_control_v305 import DraftControl


@pytest.fixture
def session(tmp_path):
    path = tmp_path / 'original.pdf'
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 60), 'UNO correo@example.org UNO')
        pdf.new_page().insert_text((40, 90), 'DOS correo@example.org DOS')
        pdf.save(path)
    current = worker.Session(path, reading=True, history_dir=tmp_path / 'history',
                             config_path=tmp_path / 'fonts.json')
    yield current
    current.close()


def test_search_stays_read_only_and_uses_file_backed_source(session, monkeypatch):
    before = session.state()
    original = open(session.path, 'rb').read()
    def forbidden(*args, **kwargs):
        raise AssertionError('Searching must not materialize the full PDF or inventory fonts.')
    monkeypatch.setattr(type(session.history), 'current', property(forbidden))
    monkeypatch.setattr(worker, 'FontResolver', forbidden)
    result = session.search('correo@example.org')
    assert [match['page'] for match in result['matches']] == [0, 1]
    assert all('context' in match and match['rects'] for match in result['matches'])
    assert session.state() == before
    assert open(session.path, 'rb').read() == original
    assert session.resolver is None


def test_original_search_maps_current_order_and_duplicate_pages(session):
    session.prepare_editing()
    session.organize_pages([dict(source='current', page=1, rotation=0),
                            dict(source='current', page=0, rotation=0),
                            dict(source='current', page=0, rotation=0)])
    session.commit()
    before = session.state()
    original = session.search('UNO', original=True)
    assert [match['page'] for match in original['matches']] == [1, 1, 2, 2]
    assert [match['page'] for match in session.search('DOS', original=True)['matches']] == [0, 0]
    assert session.state() == before


def test_worker_cancellation_keeps_session_and_history(session, monkeypatch):
    monkeypatch.setattr(worker, '_session', session)
    channel = DraftControl()
    before = session.state()
    try:
        ticket = channel.ticket()
        channel.invalidate()
        result = worker.dispatch('search', {'text': 'UNO', '_search_control_v306': ticket})
        assert result == {'search_cancelled_v306': True}
        assert session.state() == before
        valid = worker.dispatch('search', {'text': 'UNO', '_search_control_v306': channel.ticket()})
        assert len(valid['matches']) == 2
        assert session.state() == before
    finally:
        channel.close()


def test_worker_options_reach_literal_search(session, monkeypatch):
    monkeypatch.setattr(worker, '_session', session)
    def search(text, **options):
        return worker.dispatch('search', dict(text=text, **options))
    assert len(search('uno')['matches']) == 2
    assert not search('uno', case_sensitive=True)['matches']
    assert search('correo', whole_word=True)['matches']
    assert not search('correo@', whole_word=True)['matches']
    assert search('UNO', original=True)['original'] is True
