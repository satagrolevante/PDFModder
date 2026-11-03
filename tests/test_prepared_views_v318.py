"""Exact revision reuse, on-demand inventories and bounded tab preparation."""
from hashlib import sha256
from pathlib import Path

import pymupdf as fitz
import pytest

from pdfmodder.model import EditError
from pdfmodder.worker import Session


def pdf(text='Alpha',second='Omega'):
    with fitz.open() as document:
        document.new_page().insert_text((50,70),text)
        document.new_page().insert_text((50,70),second)
        return document.tobytes()


@pytest.fixture
def session(tmp_path):
    path=tmp_path/'source.pdf';path.write_bytes(pdf())
    current=Session(path,config_path=tmp_path/'fonts.json',history_dir=tmp_path)
    yield current
    current.close()


def test_pending_commit_undo_and_tab_visit_reuse_only_exact_models(session,monkeypatch):
    import pdfmodder.worker as worker
    real=worker.extract_page;calls=[]
    def extract(document,number,data=None):
        calls.append((sha256(data).hexdigest() if data else None,number))
        return real(document,number,data)
    monkeypatch.setattr(worker,'extract_page',extract)
    original=session.page(0,lazy=True)
    candidate=pdf('Bravo')
    session._put_preview(candidate,{'operation':'synthetic_test'})
    pending=session.page(0,lazy=True)
    assert pending['model'].revision!=original['model'].revision
    session.commit()
    assert session.page(0,lazy=True)['model'] is pending['model']
    session.suspend();session.resume()
    assert session.page(0,lazy=True)['model'] is pending['model']
    session.navigate_history()
    restored=session.page(0,lazy=True)
    assert restored['model'] is original['model']
    assert restored['png']==original['png'] and restored['png']!=pending['png']
    assert len(calls)==2
    assert session.history.revision==original['model'].revision


def test_original_view_cache_uses_mapped_source_page(session):
    first=session.page(0,original=True,lazy=True)
    # Identical original bytes are now compared with a reordered document.
    session.history.push(session.history.current,{'_page_keys':[1,0]})
    mapped=session.page(0,original=True,lazy=True)
    assert mapped['png']!=first['png']
    assert mapped['model'].text([g.id for g in mapped['model'].glyphs])=='Omega'


def test_nearby_zoom_values_do_not_restore_another_view_scale(session):
    first=session.page(0,zoom=1.2501,lazy=True)
    second=session.page(0,zoom=1.2502,lazy=True)
    assert first['zoom']==1.2501 and second['zoom']==1.2502
    assert session.page(0,zoom=1.2501,lazy=True)['zoom']==first['zoom']


def test_lazy_page_defers_and_reuses_requested_inventory(session,monkeypatch):
    calls=[]
    monkeypatch.setattr(session.resolver,'inspect',lambda doc,n:calls.append('fonts') or [{'name':'font'}])
    monkeypatch.setattr('pdfmodder.media.image_items',lambda doc,n,**kwargs:calls.append('images') or [{'id':'image'}])
    page=session.page(0,lazy=True)
    assert calls==[] and page['fonts']==page['images']==[]
    revision=page['model'].revision
    images=session.page_capabilities_v318(0,revision,needs=['images'])
    assert calls==['images'] and images['inventory_ready_v318']=={'fonts':False,'images':True}
    again=session.page(0,lazy=True)
    assert again['model'] is page['model'] and again['images']==[{'id':'image'}]
    full=session.page(0)
    assert calls==['images','fonts'] and full['fonts']==[{'name':'font'}]
    with pytest.raises(EditError,match='cambió'):
        session.page_capabilities_v318(0,'wrong-revision',needs=['images'])


def test_prepared_tab_lru_evicts_fourth_without_dropping_history(session,tmp_path):
    sessions=[session]
    try:
        for index in range(3):
            path=tmp_path/f'tab{index}.pdf';path.write_bytes(pdf(str(index)))
            sessions.append(Session(path,history_dir=tmp_path,config_path=tmp_path/'fonts.json'))
        for current in sessions:current.page(0,lazy=True)
        assert not session.cache and not session._model_cache
        assert all(current.cache for current in sessions[1:])
        assert session.history.current==Path(session.path).read_bytes()
        assert session.page(0,lazy=True)['model'].glyphs
    finally:
        for current in sessions[1:]:current.close()
