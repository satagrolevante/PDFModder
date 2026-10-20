"""Cooperative cancellation shared by the GUI and its single PDF process.

Only a tiny private ticket crosses this channel. PDF data, request fields and
validation results never do. Removing the ticket makes older work obsolete
without sending another command to the occupied serial worker.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import multiprocessing
import os
from pathlib import Path
import tempfile
import uuid


class DraftCancelled(Exception):
    """A superseded draft stopped at a safe checkpoint; not an editing error."""


_active = ContextVar('pdfmodder_draft_control_v305', default=None)


class DraftControl:
    """GUI-owned bounded channel; one fresh nonce for each window lifetime."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix='pdfmodder-draft-')
        self._directory = Path(self._temporary.name)
        self._path = None
        self._nonce = uuid.uuid4().hex
        self._serial = 0
        self._closed = False

    def invalidate(self):
        if self._closed:
            return
        self._serial += 1
        if self._path is not None:
            self._path.unlink(missing_ok=True)
            self._path = None

    def ticket(self):
        if self._closed:
            raise RuntimeError('El canal de borradores ya está cerrado.')
        self.invalidate()
        self._path = self._directory / f'{self._nonce}-{self._serial}.ticket'
        descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        return {'path': str(self._path), 'nonce': self._nonce, 'serial': self._serial}

    def close(self):
        if not self._closed:
            self._closed = True
            # A missing channel cancels a running draft at its next checkpoint.
            self._temporary.cleanup()


def checkpoint():
    """Raise only within a controlled preview; never interrupts a commit."""
    control = _active.get()
    if control is None:
        return
    parent = multiprocessing.parent_process()
    if parent is not None and not parent.is_alive():
        # A crashed GUI can no longer advance its ticket. The worker must not
        # finish expensive previews for an owner that no longer exists.
        path = Path(control['path'])
        if (path.name == f"{control['nonce']}-{control['serial']}.ticket"
                and path.parent.name.startswith('pdfmodder-draft-')):
            try:
                path.unlink(missing_ok=True)
                path.parent.rmdir()
            except OSError:
                pass
        raise DraftCancelled('La ventana propietaria del borrador se ha cerrado.')
    try:
        path = Path(control['path'])
        # No open descriptor is held while the GUI removes a marker. This
        # avoids Windows file-sharing conflicts during rapid cancellation.
        valid = (path.name == f"{control['nonce']}-{control['serial']}.ticket" and path.is_file())
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise DraftCancelled('Borrador sustituido por una edición más reciente.')


@contextmanager
def controlled_draft(control):
    """Install a job-local ticket, reset even if validation raises or cancels."""
    if (not isinstance(control, dict) or set(control) != {'path', 'nonce', 'serial'}
            or not isinstance(control['path'], str)
            or not isinstance(control['nonce'], str) or len(control['nonce']) != 32
            or not isinstance(control['serial'], int) or control['serial'] < 1):
        raise DraftCancelled('El control del borrador ya no es válido.')
    token = _active.set(dict(control))
    try:
        checkpoint()
        yield
        checkpoint()
    finally:
        _active.reset(token)
