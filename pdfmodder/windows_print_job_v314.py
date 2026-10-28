"""Cancel only the application's uniquely identified Windows spooler job."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class WindowsSpoolerV314:
    """Small Winspool adapter, loaded only on Windows; no queue-wide actions."""

    def __init__(self):
        if os.name != 'nt':
            raise OSError('La cola nativa de Windows no está disponible.')
        self.dll = ctypes.WinDLL('winspool.drv', use_last_error=True)
        self.dll.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
        self.dll.OpenPrinterW.restype = wintypes.BOOL
        self.dll.ClosePrinter.argtypes = [wintypes.HANDLE]
        self.dll.ClosePrinter.restype = wintypes.BOOL
        self.dll.EnumJobsW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        self.dll.EnumJobsW.restype = wintypes.BOOL
        self.dll.GetJobW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.dll.GetJobW.restype = wintypes.BOOL
        self.dll.SetJobW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD]
        self.dll.SetJobW.restype = wintypes.BOOL

    def _open(self, name):
        handle = wintypes.HANDLE()
        if not self.dll.OpenPrinterW(name, ctypes.byref(handle), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    @staticmethod
    def _job_type():
        class SYSTEMTIME(ctypes.Structure):
            _fields_ = [(name, wintypes.WORD) for name in
                        ('year', 'month', 'weekday', 'day', 'hour', 'minute', 'second', 'milliseconds')]
        class JOB_INFO_1W(ctypes.Structure):
            _fields_ = [('JobId', wintypes.DWORD), ('pPrinterName', wintypes.LPWSTR),
                        ('pMachineName', wintypes.LPWSTR), ('pUserName', wintypes.LPWSTR),
                        ('pDocument', wintypes.LPWSTR), ('pDatatype', wintypes.LPWSTR),
                        ('pStatus', wintypes.LPWSTR), ('Status', wintypes.DWORD),
                        ('Priority', wintypes.DWORD), ('Position', wintypes.DWORD),
                        ('TotalPages', wintypes.DWORD), ('PagesPrinted', wintypes.DWORD),
                        ('Submitted', SYSTEMTIME)]
        return JOB_INFO_1W

    def jobs(self, name):
        handle = self._open(name)
        try:
            for _ in range(3):
                needed, count = wintypes.DWORD(), wintypes.DWORD()
                ok = self.dll.EnumJobsW(handle, 0, 4096, 1, None, 0,
                                       ctypes.byref(needed), ctypes.byref(count))
                if not needed.value:
                    if ok:
                        return []
                    raise ctypes.WinError(ctypes.get_last_error())
                if needed.value > 8 * 1024 * 1024:
                    raise OSError('La consulta de la cola supera el límite permitido.')
                buffer = ctypes.create_string_buffer(needed.value)
                if not self.dll.EnumJobsW(handle, 0, 4096, 1, buffer, len(buffer),
                                         ctypes.byref(needed), ctypes.byref(count)):
                    if ctypes.get_last_error() == 122:
                        continue
                    raise ctypes.WinError(ctypes.get_last_error())
                size = ctypes.sizeof(self._job_type())
                if count.value * size > len(buffer):
                    raise OSError('La cola ha devuelto un inventario de trabajos no válido.')
                rows = ctypes.cast(buffer, ctypes.POINTER(self._job_type()))
                return [{'id': int(rows[i].JobId), 'document': rows[i].pDocument or '',
                         'printer': rows[i].pPrinterName or '', 'user': rows[i].pUserName or ''}
                        for i in range(count.value)]
            raise OSError('La cola cambió mientras se consultaba.')
        finally:
            self.dll.ClosePrinter(handle)

    def cancel(self, name, job_id, expected_document):
        handle = self._open(name)
        try:
            needed = wintypes.DWORD()
            self.dll.GetJobW(handle, job_id, 1, None, 0, ctypes.byref(needed))
            if not needed.value:
                return False
            if needed.value > 1024 * 1024:
                raise OSError('La información del trabajo supera el límite permitido.')
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.dll.GetJobW(handle, job_id, 1, buffer, len(buffer), ctypes.byref(needed)):
                raise ctypes.WinError(ctypes.get_last_error())
            row = ctypes.cast(buffer, ctypes.POINTER(self._job_type())).contents
            # Revalidate immediately before SetJob: an ID may have disappeared
            # or been reused after the preceding enumeration.
            if int(row.JobId) != job_id or row.pDocument != expected_document:
                return False
            if not self.dll.SetJobW(handle, job_id, 0, None, 3):  # JOB_CONTROL_CANCEL
                raise ctypes.WinError(ctypes.get_last_error())
            return True
        finally:
            self.dll.ClosePrinter(handle)


class WindowsPrintJobV314:
    """Track one exact queue/document token; never cancel unrelated jobs."""

    def __init__(self, printer_name, document_token, *, api=None):
        self.printer_name = printer_name
        self.document_token = document_token
        self.api = api if api is not None else WindowsSpoolerV314()
        self.job_id = None
        self.error = ''
        self.status = 'waiting'
        self._prior_ids = {job['id'] for job in self.api.jobs(self.printer_name)}

    def observe(self):
        matches = [job for job in self.api.jobs(self.printer_name)
                   if job.get('document') == self.document_token and job.get('id') not in self._prior_ids]
        if len(matches) > 1:
            self.error = 'La cola devolvió varios trabajos para el identificador de impresión.'
            self.status = 'ambiguous'
            return None
        if matches:
            self.job_id = matches[0]['id']
            self.status = 'identified'
        return self.job_id

    def cancel(self):
        try:
            self.observe()
            if self.status == 'ambiguous':
                return False
            if self.job_id is None:
                self.status = 'not_found'
                self.error = 'No se pudo localizar el trabajo propio para confirmar su cancelación.'
                return False
            ok = self.api.cancel(self.printer_name, self.job_id, self.document_token)
            self.status = 'cancelled' if ok else 'not_found'
            if not ok:
                self.error = 'El trabajo ya no figura con ese identificador en la cola.'
            return bool(ok)
        except OSError as exc:
            self.status = 'error'
            self.error = 'No se pudo cancelar el trabajo en la cola de Windows: ' + str(exc)
            return False


def normalize_windows_settings_v314(name, settings, *, api=None):
    """Ask the driver to normalize common DEVMODE fields, without saving them.

    This is a negotiation check against queue defaults, not a physical-printer
    acknowledgement and not a replacement for Qt's private vendor DEVMODE.
    """
    if os.name != 'nt' and api is None:
        return None
    class PrintFields(ctypes.Structure):
        _fields_ = [(field, ctypes.c_short) for field in
                    ('orientation', 'paper_size', 'paper_length', 'paper_width',
                     'scale', 'copies', 'source', 'quality')]
    class ModePrefix(ctypes.Structure):
        # DEVMODEW has fixed Windows-width fields, also in software tests
        # hosted on systems whose native wchar_t/unsigned long are wider.
        _fields_ = [('device', ctypes.c_uint16 * 32), ('spec', ctypes.c_uint16),
                    ('version', ctypes.c_uint16), ('size', ctypes.c_uint16),
                    ('extra', ctypes.c_uint16), ('fields', ctypes.c_uint32),
                    ('print', PrintFields), ('color', ctypes.c_short),
                    ('duplex', ctypes.c_short), ('y_resolution', ctypes.c_short),
                    ('tt_option', ctypes.c_short), ('collate', ctypes.c_short)]
    api = api if api is not None else WindowsSpoolerV314()
    doc_properties = api.dll.DocumentPropertiesW
    doc_properties.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR,
                               ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    doc_properties.restype = wintypes.LONG
    handle = api._open(name)
    try:
        size = doc_properties(None, handle, name, None, None, 0)
        if not ctypes.sizeof(ModePrefix) <= size <= 1024 * 1024:
            raise OSError('El controlador no devolvió una configuración válida de impresión.')
        candidate = ctypes.create_string_buffer(size)
        if doc_properties(None, handle, name, candidate, None, 2) != 1:  # DM_OUT_BUFFER
            raise OSError('No se pudieron consultar las preferencias del controlador.')
        mode = ctypes.cast(candidate, ctypes.POINTER(ModePrefix)).contents
        if mode.size < ctypes.sizeof(ModePrefix) or mode.size + mode.extra > size:
            raise OSError('El controlador devolvió una configuración de impresión incompleta.')
        raw_duplex = getattr(settings.get('duplex', 0), 'value', settings.get('duplex', 0))
        if raw_duplex in (0, 2, 3):
            mode.duplex = {0: 1, 2: 2, 3: 3}[raw_duplex]
            mode.fields |= 0x1000  # DM_DUPLEX
        color = getattr(settings.get('color', 1), 'value', settings.get('color', 1))
        mode.color = 2 if color else 1
        mode.fields |= 0x800  # DM_COLOR
        mode.print.copies = int(settings.get('copies', 1))
        mode.fields |= 0x100
        mode.collate = int(bool(settings.get('collate', True)))
        mode.fields |= 0x8000
        if settings.get('orientation') in (1, 2):
            mode.print.orientation = int(settings['orientation'])
            mode.fields |= 1
        if settings.get('paper') in (1, 2, 3) and not settings.get('driver_layout'):
            mode.print.paper_size = {1: 9, 2: 8, 3: 1}[settings['paper']]
            mode.fields |= 2
        output = ctypes.create_string_buffer(size)
        if doc_properties(None, handle, name, output, candidate, 10) != 1:  # IN|OUT, no prompt/update
            raise OSError('El controlador rechazó la combinación de opciones de impresión.')
        result = ctypes.cast(output, ctypes.POINTER(ModePrefix)).contents
        if result.size < ctypes.sizeof(ModePrefix) or result.size + result.extra > size:
            raise OSError('El controlador devolvió una configuración normalizada no válida.')
        return {'duplex': {1: 0, 2: 2, 3: 3}.get(int(result.duplex)),
                'color': 1 if result.color == 2 else 0,
                'copies': int(result.print.copies), 'collate': bool(result.collate),
                'paper_windows_id': int(result.print.paper_size),
                'orientation': int(result.print.orientation)}
    finally:
        api.dll.ClosePrinter(handle)


def check_windows_driver_settings_v314(name, settings, *, normalizer=None):
    """Reject driver-normalized simplex/color/copy fallbacks explicitly."""
    normalize = normalizer or normalize_windows_settings_v314
    result = normalize(name, settings)
    if result is None:
        return None
    requested = getattr(settings.get('duplex', 0), 'value', settings.get('duplex', 0))
    if requested in (0, 2, 3) and result['duplex'] != requested:
        raise ValueError('El controlador de Windows no ha aceptado la opción de caras elegida.')
    color = getattr(settings.get('color', 1), 'value', settings.get('color', 1))
    if result['color'] != color:
        raise ValueError('El controlador de Windows no ha aceptado la opción de color elegida.')
    if result['copies'] != int(settings.get('copies', 1)):
        raise ValueError('El controlador de Windows no ha aceptado el número de copias elegido.')
    if int(settings.get('copies', 1)) > 1 and result['collate'] != bool(settings.get('collate', True)):
        raise ValueError('El controlador de Windows no ha aceptado la agrupación de copias elegida.')
    return result
