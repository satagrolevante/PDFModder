"""Small pickle target: a spawned PDF process must not import the Qt window.

The process starts with no sessions. Recovery listing can read local metadata
without loading PDF parsers, font inventory, image libraries or UI DLLs. Once
the real worker exists it remains the sole owner of all session operations.
"""
import sys


def dispatch_pdf_worker(command, payload=None):
    if command == 'list_recovery' and 'pdfmodder.worker' not in sys.modules:
        from .recovery_v200 import list_recovery
        return list_recovery((payload or {}).get('recovery_root'))
    from .worker import dispatch
    return dispatch(command, payload)
