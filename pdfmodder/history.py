"""Immutable snapshots, cached bytes and atomic local recovery checkpoints."""
from pathlib import Path
import tempfile
import uuid
import hashlib
import json
import os
import shutil
import time


def atomic_bytes(path,data):
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.checkpoint-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class History:
    def __init__(self,original:bytes,directory=None,max_states=40,max_bytes=512*1024*1024,
                 persistent_root=None,metadata=None):
        self.folder=None if persistent_root else tempfile.TemporaryDirectory(prefix='pdfmodder-history-',dir=directory)
        self.root=Path(persistent_root) if persistent_root else Path(self.folder.name)
        self.persistent=bool(persistent_root)
        self.max_states=max_states
        self.max_bytes=max_bytes
        self.states=[None]
        self.reports=[None]
        self.base_reports=[]
        self.index=0
        self.dropped=0
        self._current=original;self._original=original
        self.metadata=dict(metadata or {});self.pending_path=None;self.pending_report=None
        self._lock=None
        self._original_durable=True
        self.digests=[self.metadata.get('original_digest') or hashlib.sha256(original).hexdigest()];self.sizes=[len(original)]

    @classmethod
    def from_file(cls,source,directory=None,max_states=40,max_bytes=512*1024*1024,
                  persistent_root=None,metadata=None):
        """Capture immutable bytes on disk without retaining a document-sized buffer.

        A PDF engine may keep seeking the same file long after opening. Never
        point it at the user's mutable original: copying also protects reading
        and comparison when another application replaces that original.
        """
        obj=cls(b'',directory,max_states,max_bytes,persistent_root,metadata)
        obj.root.mkdir(parents=True,exist_ok=True)
        destination=obj.root/'original.pdf'
        fd,name=tempfile.mkstemp(prefix='.opening-',dir=obj.root)
        digest=hashlib.sha256();size=0
        try:
            with os.fdopen(fd,'wb') as outgoing,open(source,'rb') as incoming:
                before=os.fstat(incoming.fileno())
                cloned=False
                try:
                    # Linux filesystems with copy-on-write can capture a large
                    # PDF without duplicating its data blocks before rendering.
                    import fcntl
                    fcntl.ioctl(outgoing.fileno(),0x40049409,incoming.fileno())
                    cloned=True
                except (ImportError,OSError):
                    outgoing.seek(0);outgoing.truncate(0)
                while True:
                    block=incoming.read(1024*1024)
                    if not block:break
                    if not cloned:outgoing.write(block)
                    digest.update(block);size+=len(block)
                outgoing.flush()
                after=os.fstat(incoming.fileno());named=os.stat(source)
            identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
            if identity(before)!=identity(after) or identity(after)!=identity(named) or size!=before.st_size:
                from .model import EditError
                raise EditError('El archivo cambió mientras se abría. Vuelve a abrirlo cuando termine de guardarse.')
            os.replace(name,destination)
            value=digest.hexdigest()
            obj.states=[destination];obj.digests=[value];obj.sizes=[size]
            obj._current=obj._original=None
            obj._original_durable=False
            obj.metadata.update(original_digest=value,saved_digest=value)
            return obj
        except Exception:
            obj.close()
            raise
        finally:
            if os.path.exists(name):os.unlink(name)

    @property
    def current_source(self):
        """A stable file for reading; byte materialisation remains opt-in."""
        return self._current if self._current is not None else self.states[self.index]

    @property
    def original_source(self):
        return self._original if self._original is not None else self.root/'original.pdf'

    @property
    def current(self):
        if self._current is None:
            path=self.states[self.index]
            self._current=self.original if path.name=='original.pdf' else path.read_bytes()
        return self._current

    @property
    def revision(self):return self.digests[self.index]

    @property
    def original(self):
        if self._original is None:
            self._original=(self._current if self._current is not None and self.states[self.index] is not None
                            and self.states[self.index].name=='original.pdf' else (self.root/'original.pdf').read_bytes())
        return self._original

    def materialize(self):
        self.root.mkdir(parents=True,exist_ok=True)
        if self.persistent and self._lock is None:
            from .recovery_v200 import RecoveryLock
            self._lock=RecoveryLock(self.root)
        if self.states[0] is None:
            path=self.root/'original.pdf';atomic_bytes(path,self.original);self.states[0]=path
        if not self._original_durable:
            # Reading needs stable bytes, while recovery needs durable bytes.
            # Complete durability before publishing the first checkpoint.
            # Windows requires a writable handle for FlushFileBuffers.
            with (self.root/'original.pdf').open('r+b') as original:os.fsync(original.fileno())
            self._original_durable=True

    @property
    def has_checkpoint(self):
        return self.persistent and (self.root/'session.json').exists()

    def _manifest(self,states=None,reports=None,index=None,base_reports=None,dropped=None,
                  digests=None,sizes=None,metadata=None,pending_path=None,pending_report=None):
        states=self.states if states is None else states
        return {'format':1,'updated':time.time(),'states':[p.name for p in states],
            'reports':self.reports if reports is None else reports,'index':self.index if index is None else index,
            'base_reports':self.base_reports if base_reports is None else base_reports,
            'dropped':self.dropped if dropped is None else dropped,
            'digests':self.digests if digests is None else digests,'sizes':self.sizes if sizes is None else sizes,
            'metadata':self.metadata if metadata is None else metadata,
            'pending':pending_path.name if pending_path else None,'pending_report':pending_report}

    def _publish(self,manifest):
        if self.persistent:atomic_bytes(self.root/'session.json',json.dumps(manifest,ensure_ascii=False).encode('utf-8'))

    def checkpoint(self,metadata=None,pending=None,pending_report=None):
        if not self.persistent:return
        self.materialize()
        new_metadata={**self.metadata,**(metadata or {})}
        path=self.root/(uuid.uuid4().hex+'.pdf') if pending is not None else None
        if path:atomic_bytes(path,pending)
        try:self._publish(self._manifest(metadata=new_metadata,pending_path=path,pending_report=pending_report))
        except Exception:
            if path:path.unlink(missing_ok=True)
            raise
        old=self.pending_path
        self.pending_path=path;self.pending_report=pending_report;self.metadata=new_metadata
        if old:old.unlink(missing_ok=True)

    def push(self,data,report):
        self.materialize()
        path=self.root/(uuid.uuid4().hex+'.pdf');atomic_bytes(path,data)
        states=self.states[:self.index+1]+[path];reports=self.reports[:self.index+1]+[report]
        digests=self.digests[:self.index+1]+[hashlib.sha256(data).hexdigest()]
        sizes=self.sizes[:self.index+1]+[len(data)];base=list(self.base_reports);dropped=self.dropped
        while len(states)>2 and (len(states)>self.max_states or sum(sizes)>self.max_bytes):
            states.pop(0);previous=reports.pop(0);digests.pop(0);sizes.pop(0)
            if previous:base.append(previous)
            dropped+=1
        try:self._publish(self._manifest(states,reports,len(states)-1,base,dropped,digests,sizes))
        except Exception:path.unlink(missing_ok=True);raise
        old=set(self.states);old.discard(None)
        self.states,self.reports,self.digests,self.sizes=states,reports,digests,sizes
        self.base_reports,self.dropped,self.index=base,dropped,len(states)-1;self._current=data
        for unused in old-set(states):
            if unused.name!='original.pdf':unused.unlink(missing_ok=True)
        if self.pending_path:self.pending_path.unlink(missing_ok=True)
        self.pending_path=self.pending_report=None

    def _navigate(self,index):
        if index!=self.index:
            self._publish(self._manifest(index=index));self.index=index;self._current=None
        return self.current

    def undo(self):
        return self._navigate(max(0,self.index-1))

    def redo(self):
        return self._navigate(min(len(self.states)-1,self.index+1))

    def suspend(self):
        # File-backed reading already has an immutable snapshot. Durability
        # and the recovery lock are only necessary when publishing work.
        if self.states[0] is None:self.materialize()
        self._current=self._original=None

    @classmethod
    def restore(cls,root,manifest):
        obj=cls.__new__(cls);obj.root=Path(root);obj.folder=None;obj.persistent=True
        obj.max_states=40;obj.max_bytes=512*1024*1024
        obj.states=[obj.root/name for name in manifest['states']]
        obj.reports=manifest['reports'];obj.base_reports=manifest.get('base_reports',[])
        obj.index=manifest['index'];obj.dropped=manifest.get('dropped',0)
        obj.digests=manifest['digests'];obj.sizes=manifest['sizes'];obj.metadata=manifest['metadata']
        obj.pending_path=obj.root/manifest['pending'] if manifest.get('pending') else None
        obj.pending_report=manifest.get('pending_report');obj._current=obj._original=None
        obj._original_durable=True
        from .recovery_v200 import RecoveryLock
        obj._lock=RecoveryLock(obj.root)
        return obj

    def close(self):
        if self._lock:self._lock.close();self._lock=None
        if self.folder:self.folder.cleanup()
        elif self.root.exists():shutil.rmtree(self.root)
