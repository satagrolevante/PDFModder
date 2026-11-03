"""Exclusive printer/painter ownership off the GUI thread.

Only one page is in flight. The controller polls small result records; neither
Qt widgets nor callbacks are used by the spool thread. The original QPrinter is
handed over exclusively, preserving private driver settings from Properties.
"""
from pathlib import Path
import queue
import threading


def release_print_pages_v318(pages):
    for page in pages:
        path = Path(page['path'])
        if (path.parent.name.startswith('pdfmodder-print-')
                and path.suffix in ('.png', '.ppm') and path.stem.isdigit()):
            try:
                path.unlink(missing_ok=True)
                path.parent.rmdir()
            except OSError:
                pass


class BackgroundPrintSpoolV318:
    def __init__(self, printer, settings, *, factory=None):
        if factory is None:
            from .printing_device_v314 import PrintSpoolV314
            factory = PrintSpoolV314
        self.settings = dict(settings)
        self._commands = queue.Queue(maxsize=2)
        self._results = queue.Queue()
        self._cancel = threading.Event()
        self._pending = False
        self._deferred = []
        self._done = threading.Event()
        self.error = ''
        self._thread = threading.Thread(
            target=self._run, args=(printer, dict(settings), factory),
            name='PDFModder-print-spool', daemon=True)
        self._thread.start()

    @property
    def busy(self):
        return self._pending

    @property
    def alive(self):
        return not self._done.is_set()

    def push(self, page, *, sheet_page=None):
        if self.busy or not self.alive or self._cancel.is_set():
            return False
        self._pending = True
        self._commands.put_nowait(('push', dict(page), dict(sheet_page) if sheet_page else None))
        return True

    def finish(self):
        if self.busy or not self.alive or self._cancel.is_set():
            return False
        self._pending = True
        self._commands.put_nowait(('finish', None, None))
        return True

    def cancel(self):
        self._cancel.set()
        if self.alive:
            self._pending = True
            try:
                self._commands.put_nowait(('cancel', None, None))
            except queue.Full:
                pass
        return True  # request accepted; poll supplies the cancellation outcome

    def poll(self):
        records = []
        deferred, self._deferred = self._deferred, []
        for record in deferred:
            self._results.put(record)
        while True:
            try:
                record = self._results.get_nowait()
            except queue.Empty:
                break
            terminal = record['kind'] != 'push' or not record.get('ok')
            if terminal and not self._done.is_set():
                self._deferred.append(record)
                continue
            self._pending = False
            if record.get('error'):
                self.error = record['error']
            records.append(record)
        return records

    def _run(self, printer, settings, factory):
        spool = None
        try:
            spool = factory(printer, settings)
            while True:
                kind, page, anchor = self._commands.get()
                try:
                    if self._cancel.is_set() or kind == 'cancel':
                        ok = spool.cancel()
                        self._results.put({'kind': 'cancel', 'ok': ok,
                                           'error': getattr(spool, 'cancel_error', '')})
                        return
                    if kind == 'push':
                        if anchor is not None:
                            spool.settings['sheet_page_v314'] = anchor
                        ok = spool.push(page)
                        if self._cancel.is_set():
                            cancelled = spool.cancel()
                            self._results.put({'kind': 'cancel', 'ok': cancelled,
                                               'error': getattr(spool, 'cancel_error', '')})
                            return
                        self._results.put({'kind': 'push', 'ok': ok, 'page': page['page'],
                                           'dpi': page.get('dpi'), 'error': spool.error})
                        if not ok:
                            return
                    elif kind == 'finish':
                        ok = spool.finish()
                        self._results.put({'kind': 'finish', 'ok': ok, 'error': spool.error})
                        return
                finally:
                    if page is not None:
                        release_print_pages_v318([page])
        except Exception as exc:
            self._results.put({'kind': 'error', 'ok': False, 'error': str(exc)})
        finally:
            try:
                if spool is not None and not getattr(spool, 'finished', False):
                    spool.cancel()
                while not self._commands.empty():
                    _, page, _ = self._commands.get_nowait()
                    if page is not None:
                        release_print_pages_v318([page])
            except Exception as exc:
                self._results.put({'kind': 'error', 'ok': False, 'error': str(exc)})
            finally:
                # Terminal records become observable only after the painter
                # has ended and cleanup no longer touches the printer.
                self._done.set()
