"""Paste availability without asking an external Windows clipboard owner for data.

Qt's Windows QMimeData queries use OLE and can wait for an unresponsive owner.
Refreshing action state must only inspect advertised Win32 formats. Actual
payload retrieval remains in the explicit Paste command.
"""
from functools import lru_cache
import sys

OBJECT_MIME_V200 = 'application/x-pdfmodder-object-v1'


@lru_cache(maxsize=1)
def _windows_probe_v200():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    available = user32.IsClipboardFormatAvailable
    available.argtypes = [wintypes.UINT]
    available.restype = wintypes.BOOL
    register = user32.RegisterClipboardFormatW
    register.argtypes = [wintypes.LPCWSTR]
    register.restype = wintypes.UINT
    # CF_TEXT, CF_UNICODETEXT, CF_BITMAP, CF_DIB, CF_DIBV5 and Qt PNG/custom.
    formats = (1, 13, 2, 8, 17)
    formats += tuple(value for name in (OBJECT_MIME_V200, 'PNG')
                     if (value := register(name)))
    return available, formats


def _windows_has_paste_v200():
    available, formats = _windows_probe_v200()
    return any(available(value) for value in formats)


def clipboard_has_paste_v200():
    if sys.platform == 'win32':
        try:
            return _windows_has_paste_v200()
        except (OSError, AttributeError):
            # Leave Paste available for explicit validation if metadata cannot
            # be inspected; never fall back to a blocking OLE query on refresh.
            return True
    from PySide6.QtWidgets import QApplication
    mime = QApplication.clipboard().mimeData()
    return bool(mime and (mime.hasFormat(OBJECT_MIME_V200) or mime.hasText() or mime.hasImage()))
