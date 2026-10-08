"""Exact recovery, independently scoped documents and bounded reader caches."""
from pathlib import Path
import json
import pymupdf as fitz
import pytest
from pdfmodder.history import History
from pdfmodder.model import EditError
from pdfmodder.recovery_v200 import list_recovery,read_checkpoint
from pdfmodder.worker import Session


def make_pdf(path,text='Document one'):
    with fitz.open() as doc:
        doc.new_page().insert_text((60,80),text)
        path.write_bytes(doc.tobytes())
    return path


def modified(data,text='Document changed'):
    with fitz.open(stream=data,filetype='pdf') as doc:
        doc[0].insert_text((60,110),text)
        return doc.tobytes(garbage=4)


def test_reader_uses_immutable_snapshot_without_recovery_checkpoint_and_reuses_models(tmp_path,monkeypatch):
    import pdfmodder.worker as worker
    session=Session(make_pdf(tmp_path/'one.pdf'),reading=True,recovery_root=tmp_path/'recovery')
    calls=[];original=worker.extract_page
    monkeypatch.setattr(worker,'extract_page',lambda *args:(calls.append(1),original(*args))[1])
    try:
        assert session.history.original_source.is_file()
        assert not session.history.has_checkpoint and session.history._lock is None
        pages=[session.page(0,zoom=z) for z in (.6,1.,1.5)]
        assert len(calls)==1 and pages[0]['model'] is pages[-1]['model']
        assert session.history.current is session.history.current
        assert len(session._documents)==1 and len(session._displaylists)==1
        assert not session.history.has_checkpoint and session.history._lock is None
    finally:session.close()


def test_crash_checkpoint_restores_exact_history_preview_and_original(tmp_path):
    source=make_pdf(tmp_path/'one.pdf');root=tmp_path/'recovery'
    session=Session(source,password='NEVER_PERSIST_THIS_PASSWORD',recovery_root=root,config_path=tmp_path/'fonts.json')
    original=session.original;first=modified(original);second=modified(first,'Document next')
    session._put_preview(first,{'operation':'synthetic','page':0});session.commit()
    session._put_preview(second,{'operation':'synthetic','page':0});session.commit()
    session.navigate_history();session._put_preview(second,{'operation':'synthetic','page':0})
    session.update_workspace({'page':0,'zoom':1.3,'password':'do not persist'})
    identifier=session.recovery_id;session._close_documents()  # Simulated lost process, no clean close.
    session.history._lock.close();session.history._lock=None  # OS releases the lock after a real process crash.
    record=list_recovery(root)['entries'][0]
    assert record['recovery_id']==identifier and record['preview']
    manifest=(session.history.root/'session.json').read_text(encoding='utf-8')
    assert 'NEVER_PERSIST_THIS_PASSWORD' not in manifest and 'do not persist' not in manifest
    restored=Session.recover(identifier,recovery_root=root,config_path=tmp_path/'fonts.json')
    try:
        assert restored.history.current==first and restored.pending==second and restored.original==original
        assert restored.state()['redo'] and restored.state()['workspace']['zoom']==1.3
        restored.cancel();assert restored.history.redo()==second
        assert restored.history.undo()==first and restored.history.undo()==original
        assert source.read_bytes()==original
        with pytest.raises(EditError,match='original'):restored.save(source)
    finally:restored.close()


def test_checkpoint_failure_keeps_previous_history_and_redo(tmp_path,monkeypatch):
    import pdfmodder.history as module
    history=History(b'original',persistent_root=tmp_path/'history',metadata={'path':'source.pdf'})
    history.push(b'first',{'operation':'test'});history.push(b'second',{'operation':'test'});history.undo()
    original=module.atomic_bytes
    def fail_manifest(path,data):
        if Path(path).name=='session.json':raise OSError('Disk full')
        return original(path,data)
    monkeypatch.setattr(module,'atomic_bytes',fail_manifest)
    try:
        with pytest.raises(OSError):history.push(b'failed',{'operation':'test'})
        assert history.current==b'first' and history.index==1 and len(history.states)==3
        monkeypatch.setattr(module,'atomic_bytes',original)
        assert history.redo()==b'second'
    finally:history.close()


def test_recovery_rejects_modified_snapshot_and_path_escape(tmp_path):
    session=Session(make_pdf(tmp_path/'one.pdf'),recovery_root=tmp_path/'recovery')
    session._put_preview(modified(session.original),{'operation':'synthetic'});session.commit()
    try:
        session.history.states[-1].write_bytes(b'corrupt')
        with pytest.raises(EditError,match='dañada'):read_checkpoint(session.recovery_id,tmp_path/'recovery',verify=True)
        with pytest.raises(EditError,match='identificador'):read_checkpoint('../other',tmp_path/'recovery')
    finally:session.close()


def test_multidocument_sessions_keep_independent_history_and_suspend_caches(tmp_path,monkeypatch):
    import pdfmodder.worker as worker
    monkeypatch.setattr(worker,'_session',None);monkeypatch.setattr(worker,'_sessions',worker.OrderedDict())
    first=make_pdf(tmp_path/'one.pdf');second=make_pdf(tmp_path/'two.pdf','Document two')
    options={'history_dir':str(tmp_path),'config_path':str(tmp_path/'fonts.json')}
    try:
        one=worker.dispatch('open',{'path':str(first),**options})['state']['session_id']
        worker._session._put_preview(modified(worker._session.original),{'operation':'synthetic'})
        worker.dispatch('commit',{'session_id':one});worker.dispatch('page',{'session_id':one,'number':0})
        old=worker._session
        two=worker.dispatch('open',{'path':str(second),'retain_existing':True,**options})['state']['session_id']
        assert old.history._current is None and not old.cache and not old._documents and old.resolver is None
        assert len(worker.dispatch('list_sessions')['sessions'])==2
        active=worker.dispatch('activate_session',{'session_id':one})['state']
        assert active['dirty'] and active['undo']
        assert worker.dispatch('undo',{'session_id':one})['state']['dirty'] is False
        assert worker.dispatch('activate_session',{'session_id':two})['state']['dirty'] is False
        text=worker.dispatch('page',{'session_id':two,'number':0})['model'].text(range(100))
        assert 'Document two' in text
    finally:worker.dispatch('close_all')


def test_draft_only_recovery_and_live_lock_exclusion(tmp_path):
    source=make_pdf(tmp_path/'draft.pdf');root=tmp_path/'recovery'
    session=Session(source,recovery_root=root,config_path=tmp_path/'fonts.json')
    session.store_draft({'kind':'legacy','page':0,'ids':[0],
        'revision':session.history.revision,'text':'Unaccepted local draft','password':'never'},
        {'page':0,'zoom':1.1,'password':'never'})
    identifier=session.recovery_id
    assert list_recovery(root)['entries']==[]
    with pytest.raises(EditError,match='otra instancia'):Session.recover(identifier,recovery_root=root)
    session.history._lock.close();session.history._lock=None;session._close_documents()
    assert list_recovery(root)['entries'][0]['draft']
    restored=Session.recover(identifier,recovery_root=root,config_path=tmp_path/'fonts.json')
    try:
        assert restored.state()['recovered_draft']['text']=='Unaccepted local draft'
        assert 'password' not in restored.history.metadata['draft']
        restored.cancel();assert restored.state()['recovered_draft'] is None
        assert restored.history.metadata['draft'] is None
    finally:restored.close()
