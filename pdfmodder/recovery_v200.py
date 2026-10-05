"""Recovery catalog: passwords and private keys are never persisted."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
from .model import EditError


class RecoveryLock:
    """OS lock lives with the process; crash releases it without PID assumptions."""
    def __init__(self,folder):
        self.stream=open(Path(folder)/'owner.lock','a+b')
        try:
            self.stream.seek(0)
            if not self.stream.read(1):self.stream.write(b'0');self.stream.flush()
            self.stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close();raise EditError('Este borrador está abierto en otra instancia de PDF Modder.') from exc
    def close(self):
        if self.stream.closed:return
        self.stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()


def in_use(folder):
    try:
        lock=RecoveryLock(folder);lock.close();return False
    except EditError:return True


def recovery_root(path=None):
    return Path(path).resolve() if path else (Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PDFModder'/'recovery').resolve()


def recovery_path(identifier,root=None):
    if not re.fullmatch(r'[a-f0-9]{32}',str(identifier)):
        raise EditError('El identificador de recuperación no es válido.')
    parent=recovery_root(root);target=parent/identifier
    if target.is_symlink() or (target.exists() and target.resolve().parent!=parent):
        raise EditError('La recuperación está fuera de su carpeta local.')
    return target


def read_checkpoint(identifier,root=None,verify=False):
    folder=recovery_path(identifier,root)
    try:
        manifest=json.loads((folder/'session.json').read_text(encoding='utf-8'))
        states=manifest['states'];index=manifest['index'];metadata=manifest['metadata']
        if (manifest.get('format')!=1 or not states or not isinstance(index,int) or
            not 0<=index<len(states) or len(states)!=len(manifest['reports']) or
            len(states)!=len(manifest['digests']) or len(states)!=len(manifest['sizes']) or
            not isinstance(metadata,dict)):
            raise ValueError('Invalid manifest')
        names=[*states,'original.pdf']
        if manifest.get('pending'):names.append(manifest['pending'])
        for name in names:
            if not re.fullmatch(r'(?:original|[a-f0-9]{32})\.pdf',name):raise ValueError('Invalid snapshot name')
            file=folder/name
            if file.is_symlink() or not file.is_file() or file.resolve().parent!=folder.resolve():raise ValueError('Invalid snapshot')
        if verify:
            for name,digest in zip(states,manifest['digests']):
                if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise ValueError('Snapshot mismatch')
        return folder,manifest
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise EditError('La recuperación local está incompleta o dañada; conserva la carpeta para diagnóstico.') from exc


def list_recovery(root=None,exclude=()):
    parent=recovery_root(root);entries=[]
    if not parent.is_dir():return {'entries':entries}
    for folder in parent.iterdir():
        if folder.name in exclude or not re.fullmatch(r'[a-f0-9]{32}',folder.name):continue
        try:
            if folder.is_symlink() or in_use(folder):continue
            _,manifest=read_checkpoint(folder.name,parent)
            meta=manifest['metadata'];index=manifest['index']
            dirty=manifest['digests'][index]!=meta.get('saved_digest')
            if not dirty and not manifest.get('pending') and not meta.get('draft'):continue
            entries.append({'recovery_id':folder.name,'path':meta.get('path',''),
                'updated':manifest['updated'],'history_index':index,'history_states':len(manifest['states']),
                'dirty':dirty,'preview':bool(manifest.get('pending')),'draft':bool(meta.get('draft')),
                'workspace':meta.get('workspace',{})})
        except (EditError,OSError):continue
    entries.sort(key=lambda item:item['updated'],reverse=True)
    return {'entries':entries}


def discard_recovery(identifier,root=None):
    folder=recovery_path(identifier,root)
    if folder.exists():
        lock=RecoveryLock(folder);lock.close();shutil.rmtree(folder)
    return {'discarded':identifier}
