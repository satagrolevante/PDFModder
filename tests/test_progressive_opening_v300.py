"""File-backed opening preserves immutable revisions and loads only requested pages."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from pdfmodder.history import History
from pdfmodder.model import EditError
from pdfmodder.worker import Session


def pdf_file(tmp_path,count=24):
    path=tmp_path/'progressive.pdf'
    with fitz.open() as document:
        for number in range(count):
            page=document.new_page(width=500+number,height=720+number)
            page.insert_text((50,75),f'Immutable page {number+1}')
        document[-1].set_rotation(90)
        path.write_bytes(document.tobytes())
    return path


def test_navigation_does_not_materialise_document_bytes(tmp_path,monkeypatch):
    path=pdf_file(tmp_path);expected=sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(Path,'read_bytes',lambda self:pytest.fail('Reading must use the immutable file, not a full PDF buffer'))
    session=Session(path,reading=True,history_dir=tmp_path)
    try:
        monkeypatch.setattr(session,'_instance_keys',lambda *a,**k:
                            pytest.fail('One-page reading must not build an identity string for every page'))
        assert session.history._original is session.history._current is None
        assert session.history.revision==expected
        assert session.state()['document_revision']==expected
        info=session.reading_info(progressive=True,pages=[0])
        assert info['page_count']==24 and set(info['geometries'])=={0}
        assert info['geometry_ready_count']==1 and not info['geometry_complete']
        assert 'page_geometries' not in info
        page=session.page(0,reading=True)
        assert page['model'].text([g.id for g in page['model'].glyphs])=='Immutable page 1'
        assert page['model'].revision==expected
        ids=[g.id for g in page['model'].glyphs]
        copied=session.copy_reading_selection(0,ids=ids,revision=expected)
        assert copied['text']=='Immutable page 1'
        assert session.history._original is session.history._current is None
        assert not session.state()['dirty']
    finally:session.close()


def test_partial_geometries_measure_only_requested_pages_and_cache_results(tmp_path,monkeypatch):
    path=pdf_file(tmp_path);session=Session(path,reading=True,history_dir=tmp_path)
    try:
        initial=session.reading_info(progressive=True,pages=[0])
        document=session._document(session._view_source(),session.history.revision)
        visited=[];original_load=type(document).load_page
        def load(document,number):visited.append(number);return original_load(document,number)
        monkeypatch.setattr(type(document),'load_page',load)
        final=session.reading_info(progressive=True,pages=[0,23])
        assert visited==[23]
        assert final['geometries'][23]=={'width':743.,'height':523.}
        assert final['geometry_ready_count']==2 and not final['geometry_complete']
        assert initial['geometry_ready_count']==1
        with pytest.raises(EditError,match='no existe'):session.reading_info(progressive=True,pages=[24])
    finally:session.close()


def test_live_source_replacement_cannot_change_reading_comparison_or_revision(tmp_path):
    path=pdf_file(tmp_path);original=path.read_bytes();session=Session(path,reading=True,history_dir=tmp_path)
    try:
        replacement=tmp_path/'replacement.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((50,75),'Different external document')
            replacement.write_bytes(document.tobytes())
        replacement.replace(path)
        for original_view in (False,True):
            page=session.page(0,reading=True,original=original_view)
            assert page['model'].text([g.id for g in page['model'].glyphs])=='Immutable page 1'
            assert page['model'].revision==sha256(original).hexdigest()
        assert session.history.original_source.read_bytes()==original
        assert session.state()['page_count']==24 and not session.state()['dirty']
        assert path.read_bytes()!=original
    finally:session.close()


def test_inactive_session_releases_buffers_and_reopens_its_snapshot(tmp_path):
    path=pdf_file(tmp_path);session=Session(path,reading=True,history_dir=tmp_path)
    try:
        session.page(0,reading=True);session.reading_info(progressive=True,pages=[0,1])
        assert session._documents and session.cache
        session.suspend()
        assert not session._documents and not session.cache and not session._reading_info_cache
        assert session.history._original is session.history._current is None
        session.resume()
        assert session.page(1,reading=True)['model'].number==1
        assert session.history._original is session.history._current is None
    finally:session.close()


def test_clean_reader_workspace_and_tab_switch_do_not_publish_recovery(tmp_path):
    session=Session(pdf_file(tmp_path),reading=True,history_dir=tmp_path)
    try:
        session.update_workspace({'page':5,'zoom':1.7})
        session.store_draft(None,{'page':5,'zoom':1.7})
        session.suspend()
        assert not session.history.has_checkpoint and session.history._lock is None
        assert not session.history._original_durable
        session.resume()
        assert session.state()['workspace']=={'page':5,'zoom':1.7}
    finally:session.close()


def test_snapshot_detects_source_change_during_capture_and_removes_partial_state(tmp_path,monkeypatch):
    import pdfmodder.history as history
    source=pdf_file(tmp_path);root=tmp_path/'capture';fstat=history.os.fstat;calls=0
    def changed(fd):
        nonlocal calls
        calls+=1
        result=fstat(fd)
        if calls>1:
            return SimpleNamespace(st_dev=result.st_dev,st_ino=result.st_ino,st_size=result.st_size+1,
                                   st_mtime_ns=result.st_mtime_ns,st_ctime_ns=result.st_ctime_ns)
        return result
    monkeypatch.setattr(history.os,'fstat',changed)
    with pytest.raises(EditError,match='cambió mientras'):History.from_file(source,persistent_root=root)
    assert not root.exists()


def test_snapshot_uses_descriptor_timestamps_when_windows_path_stat_differs(tmp_path,monkeypatch):
    import pdfmodder.history as history
    source=pdf_file(tmp_path);original=source.read_bytes();stat=history.os.stat
    def windows_path_stat(path,*args,**kwargs):
        result=stat(path,*args,**kwargs)
        if Path(path)==source:
            # CPython 3.12 on Windows exposes creation time through stat(path)
            # and metadata change time through fstat(fd).
            return SimpleNamespace(st_dev=result.st_dev,st_ino=result.st_ino,st_size=result.st_size,
                                   st_mtime_ns=result.st_mtime_ns,st_ctime_ns=result.st_ctime_ns-1_000_000_000)
        return result
    monkeypatch.setattr(history.os,'stat',windows_path_stat)
    captured=History.from_file(source,directory=tmp_path)
    try:
        assert captured.original_source.read_bytes()==original
        assert captured.revision==sha256(original).hexdigest()
        assert captured._original is captured._current is None
    finally:captured.close()


@pytest.mark.parametrize('change',['append','same_size_overwrite'])
def test_snapshot_rejects_real_in_place_write_before_descriptor_recheck(tmp_path,monkeypatch,change):
    import pdfmodder.history as history
    source=pdf_file(tmp_path);root=tmp_path/'capture';fstat=history.os.fstat;calls=0
    def changed(fd):
        nonlocal calls
        calls+=1
        if calls==2:
            initial=fstat(fd)
            with source.open('r+b') as writer:
                if change=='append':writer.seek(0,2)
                writer.write(b'X');writer.flush()
            history.os.utime(source,ns=(initial.st_atime_ns,initial.st_mtime_ns+2_000_000_000))
        return fstat(fd)
    monkeypatch.setattr(history.os,'fstat',changed)
    with pytest.raises(EditError,match='cambió mientras'):History.from_file(source,persistent_root=root)
    assert not root.exists()


@pytest.mark.parametrize('change',['replacement','removal'])
def test_snapshot_rechecks_named_source_while_original_descriptor_is_alive(tmp_path,monkeypatch,change):
    import builtins
    import pdfmodder.history as history
    source=pdf_file(tmp_path);root=tmp_path/'capture';replacement=tmp_path/'replacement.pdf'
    replacement.write_bytes(source.read_bytes());original_open=builtins.open;source_handle=None
    def changed_name(path,*args,**kwargs):
        nonlocal source_handle
        if Path(path)==source:
            if source_handle is None:
                source_handle=original_open(path,*args,**kwargs)
                return source_handle
            # Use real file descriptors for distinct files. Reopening a
            # replaced/deleted path is simulated because Windows may prohibit
            # renaming a file while its original descriptor is open.
            assert not source_handle.closed
            history.os.fstat(source_handle.fileno())
            if change=='removal':raise FileNotFoundError(str(source))
            return original_open(replacement,*args,**kwargs)
        return original_open(path,*args,**kwargs)
    monkeypatch.setattr(history,'open',changed_name,raising=False)
    with pytest.raises(EditError,match='cambió mientras'):History.from_file(source,persistent_root=root)
    assert source_handle.closed and not root.exists()


def test_file_snapshot_push_undo_and_suspend_preserve_original(tmp_path):
    path=pdf_file(tmp_path);original=path.read_bytes();history=History.from_file(path,directory=tmp_path)
    try:
        with fitz.open(stream=original) as document:
            document.set_metadata({'title':'New title'});changed=document.tobytes()
        history.push(changed,{'operation':'document_metadata'})
        assert history.current==changed and history.original==original
        assert history.undo()==original
        history.suspend()
        assert history.current_source==history.states[0]
        assert history.original==original and history.redo()==changed
    finally:history.close()


@pytest.mark.parametrize('encrypted',[False,True])
def test_clean_reading_save_preserves_exact_bytes_without_loading_pdf_buffer(tmp_path,monkeypatch,encrypted):
    path=pdf_file(tmp_path,3);password='legitimate-password' if encrypted else ''
    if encrypted:
        with fitz.open(path) as document:
            encrypted_data=document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=password,user_pw=password,permissions=fitz.PDF_PERM_COPY)
        path.write_bytes(encrypted_data)
    original=path.read_bytes();session=Session(path,password=password,reading=True,history_dir=tmp_path)
    output=tmp_path/'reading-copy.pdf'
    monkeypatch.setattr(Path,'read_bytes',lambda self:pytest.fail('Unchanged save must copy file blocks'))
    try:
        result=session.save(output)
        with output.open('rb') as copied:assert copied.read()==original
        assert result['unchanged_copy'] and result['state']['last_save_path']==str(output.resolve())
        assert not result['state']['dirty'] and session.history._original is session.history._current is None
        assert session.resolver is None and not session._editing_prepared
        with pytest.raises(EditError,match='original'):session.save(path)
    finally:session.close()


def test_failed_reading_copy_hash_keeps_existing_destination_and_removes_temporary(tmp_path):
    path=pdf_file(tmp_path,2);session=Session(path,reading=True,history_dir=tmp_path)
    destination=tmp_path/'existing.pdf';destination.write_bytes(b'previous destination bytes')
    try:
        with session.history.original_source.open('ab') as altered:altered.write(b'changed snapshot')
        with pytest.raises(EditError,match='no coincide'):session.save(destination)
        assert destination.read_bytes()==b'previous destination bytes'
        assert session.history.metadata.get('last_save_path') is None
        assert not list(tmp_path.glob('.pdfmodder-*'))
    finally:session.close()


def test_reading_copy_requires_a_clean_snapshot_after_editing(tmp_path):
    path=pdf_file(tmp_path,2);session=Session(path,history_dir=tmp_path)
    destination=tmp_path/'copy.pdf'
    try:
        assert session.save(destination,reading_copy=True)['unchanged_copy']
        assert destination.read_bytes()==path.read_bytes()
        with fitz.open(stream=session.history.current) as document:
            document.set_metadata({'title':'Pending edited document'});changed=document.tobytes()
        session._put_preview(changed,{'operation':'document_metadata'});session.commit()
        with pytest.raises(EditError,match='cambios pendientes'):session.save(destination,reading_copy=True)
        assert session.state()['dirty'] and destination.read_bytes()==path.read_bytes()
    finally:session.close()


def test_png_cache_does_not_keep_an_oversize_text_model_alive(tmp_path):
    import gc
    import weakref
    path=tmp_path/'dense.pdf'
    with fitz.open() as document:
        page=document.new_page(width=500,height=3000)
        for number in range(400):page.insert_text((10,12+number*7),'A'*100,fontsize=5)
        path.write_bytes(document.tobytes())
    session=Session(path,reading=True,history_dir=tmp_path)
    try:
        result=session.page(0,reading=True,zoom=.1)
        assert len(result['model'].glyphs)==40_000
        assert not session._model_cache and session._model_bytes==0
        reference=weakref.ref(result['model'])
        del result;gc.collect()
        assert reference() is None
        assert session.cache and session.cache_bytes>0
        result=session.page(0,reading=True,zoom=.1)
        assert len(result['model'].glyphs)==40_000
    finally:session.close()
