"""Consultation sessions save safely without editing a signed source."""
from collections import OrderedDict
from pathlib import Path

import pymupdf as fitz
import pytest

from pdfmodder import worker
from pdfmodder.model import EditError
from test_merge_copies_v319 import ordinary_pdf, widget_pdf


@pytest.fixture
def merge_worker(monkeypatch):
    monkeypatch.setattr(worker, '_sessions', OrderedDict())
    monkeypatch.setattr(worker, '_session', None)
    monkeypatch.setattr(worker, '_prepared_sessions_v318', OrderedDict())
    yield worker
    worker.dispatch('close_all')


def sources(tmp_path):
    first, second = tmp_path/'signed.pdf', tmp_path/'added.pdf'
    first.write_bytes(widget_pdf(signed=True))
    second.write_bytes(ordinary_pdf())
    return first, second


def opened(api, path, tmp_path, *, reading=True):
    return api.dispatch('open', {'path':str(path), 'reading':reading,
        'config_path':str(tmp_path/'fonts.json'), 'recovery_root':str(tmp_path/'recovery')})


def test_signed_reading_merge_is_new_dirty_session_and_can_save_suggested_name(merge_worker, tmp_path):
    api=merge_worker
    first, second=sources(tmp_path)
    original={p:p.read_bytes() for p in (first,second)}
    before=opened(api,first,tmp_path)
    old=api._session
    result=api.dispatch('merge',{'session_id':before['state']['session_id'],
                               'paths':[str(second)],'as_copy':True})
    new=api._session
    assert result['new_session'] and new is not old
    assert len(api._sessions)==2 and old.history.current==original[first]
    assert not old._editing_prepared
    assert result['state']['dirty'] and not result['state']['undo']
    assert result['state']['page_count']==2 and not result['state']['issues']
    assert result['report']['source_paths']==[str(first),str(second)]
    assert new.path==str(new.history.root/'original.pdf')
    for source in original:
        with pytest.raises(EditError):new.save(source)
    destination=Path(result['state']['path'])
    assert destination.name=='signed_combinado.pdf' and not destination.exists()
    saved=new.save(destination)
    assert not saved['state']['dirty'] and destination.exists()
    with fitz.open(destination) as check:
        assert len(check)==2 and not check.is_form_pdf and check.get_sigflags()<=0
    assert all(p.read_bytes()==data for p,data in original.items())


def test_existing_editable_merge_keeps_undo_and_protected_sources(merge_worker,tmp_path):
    api=merge_worker
    first=tmp_path/'current.pdf';added=tmp_path/'signed.pdf'
    first.write_bytes(ordinary_pdf());added.write_bytes(widget_pdf(signed=True))
    start=opened(api,first,tmp_path,reading=False)
    session=api._session
    result=api.dispatch('merge',{'session_id':session.session_id,'paths':[str(added)],'as_copy':True})
    assert api._session is session and result['state']['session_id']==start['state']['session_id']
    assert result['state']['history_index']==1 and result['state']['original_pages']==[0,None]
    assert str(added.resolve()) in session.history.metadata['protected_paths']
    with pytest.raises(EditError):session.save(added)
    session.navigate_history()
    assert session.history.current==first.read_bytes()


def test_failed_copy_reports_source_name_without_replacing_active_session(merge_worker,tmp_path):
    api=merge_worker
    first,second=sources(tmp_path)
    bad=tmp_path/'archivo-roto.pdf';bad.write_bytes(b'not a PDF')
    opened(api,first,tmp_path)
    source=api._session
    with pytest.raises(EditError,match='archivo-roto.pdf'):
        api.dispatch('merge',{'paths':[str(bad)],'as_copy':True})
    assert api._session is source and len(api._sessions)==1
    assert source.history.index==0 and source.pending is None


def test_independent_combine_retains_open_session_and_uses_requested_new_id(merge_worker,tmp_path):
    api=merge_worker
    first,second=sources(tmp_path)
    opened(api,first,tmp_path)
    source=api._session
    result=api.dispatch('combine',{'paths':[str(first),str(second)],'as_copy':True,
        'retain_existing':True,'session_id':'combined-id',
        'config_path':str(tmp_path/'fonts.json'),'recovery_root':str(tmp_path/'recovery')})
    assert result['new_session'] and result['state']['session_id']=='combined-id'
    assert source.session_id in api._sessions and len(api._sessions)==2
    assert result['state']['dirty']


def test_merge_cannot_discard_an_unapplied_draft(merge_worker,tmp_path):
    api=merge_worker
    first,second=sources(tmp_path)
    opened(api,first,tmp_path)
    source=api._session
    source.history.metadata['draft']={'kind':'test-only'}
    with pytest.raises(EditError,match='borrador'):
        api.dispatch('merge',{'paths':[str(second)],'as_copy':True})
    assert api._session is source and len(api._sessions)==1


def test_form_flags_follow_merge_and_undo_revision(merge_worker,tmp_path):
    api=merge_worker
    first=tmp_path/'form.pdf';second=tmp_path/'plain.pdf'
    first.write_bytes(widget_pdf());second.write_bytes(ordinary_pdf())
    opened(api,first,tmp_path,reading=False)
    assert api._session.state()['has_form_fields']
    merged=api.dispatch('merge',{'paths':[str(second)],'as_copy':True})
    assert not merged['state']['has_form_fields']
    assert api._session.navigate_history()['state']['has_form_fields']


def test_unsaved_combined_copy_recovers_name_bytes_and_source_protection(merge_worker,tmp_path):
    api=merge_worker
    first,second=sources(tmp_path)
    result=api.dispatch('combine',{'paths':[str(first),str(second)],'as_copy':True,
        'config_path':str(tmp_path/'fonts.json'),'recovery_root':str(tmp_path/'recovery')})
    original=api._session
    identifier=original.recovery_id
    digest=original.history.revision
    original._close_documents()
    # Emulate process termination: release the lock but retain its checkpoint.
    original.history._lock.close();original.history._lock=None
    api._sessions.clear();api._session=None
    entries=api.dispatch('list_recovery',{'recovery_root':str(tmp_path/'recovery')})['entries']
    assert entries[0]['path']==result['state']['path']
    recovered=api.dispatch('recover',{'recovery_id':identifier,
        'config_path':str(tmp_path/'fonts.json'),'recovery_root':str(tmp_path/'recovery')})
    assert recovered['state']['path']==result['state']['path']
    assert recovered['state']['dirty'] and api._session.history.revision==digest
    for source in (first,second):
        with pytest.raises(EditError):api._session.save(source)
    api._session.save(tmp_path/'recovered.pdf')
