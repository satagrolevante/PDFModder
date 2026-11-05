"""Explorer printing sends the selected PDF without an options dialog."""
from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QMainWindow, QInputDialog

from pdfmodder.printing_dialog_v314 import PrintDialogV314
from pdfmodder.shell_ui_v305 import ShellActionsUiMixin
from test_saving_v300 import saving_window, finished


def source_pdf(path, encrypted=False):
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 60), 'Documento para imprimir')
        options = ({'encryption': fitz.PDF_ENCRYPT_AES_256,
                    'owner_pw': 'owner-secret', 'user_pw': 'secret'} if encrypted else {})
        doc.save(path, **options)
    return path


@pytest.mark.parametrize('encrypted', [False, True])
def test_print_sends_the_selected_file_without_a_dialog_or_saved_profile(
        qtbot, saving_window, tmp_path, monkeypatch, encrypted):
    window = saving_window
    source = source_pdf(tmp_path/'Factura con espacios y ñ.PDF', encrypted)
    original = source.read_bytes()
    import pdfmodder.printing_direct_v320 as direct
    settings, output = pdf_device(tmp_path, copies=1 if encrypted else 2)
    started = []
    def defaults(document):
        assert Path(document) == source
        started.append(document)
        return settings
    monkeypatch.setattr(direct, 'system_default_printer_v320', defaults)
    monkeypatch.setattr(window, '_exec_edit_dialog', lambda *_: pytest.fail('No print dialog is allowed'))
    monkeypatch.setattr(PrintDialogV314, '__init__', lambda *_a, **_k: pytest.fail('No hidden print options'))
    monkeypatch.setattr(window._printer_preferences_v311, 'remember', lambda *_: pytest.fail('Do not change saved preferences'))
    monkeypatch.setattr(window._printer_preferences_v311, 'settings_for', lambda *_: pytest.fail('Do not read saved preferences'))
    monkeypatch.setattr(QInputDialog, 'getText', lambda *_: ('secret', True))
    assert window.open_pdf_for_print_v320(source)
    qtbot.waitUntil(lambda: bool(started) and window._print_context_v314 is None, timeout=20000)
    finished(qtbot, window)
    assert len(started) == 1 and window._shell_print_v320 is None
    assert window._print_context_v314 is None
    assert source.read_bytes() == original
    with fitz.open(output) as printed:
        assert len(printed) == settings['copies']
        expected = settings['page_layout_v314'].fullRect(QPageLayout.Point)
        assert all(abs(page.rect.width-expected.width()) < .1 and
                   abs(page.rect.height-expected.height()) < .1 for page in printed)


def test_failed_open_does_not_print_a_subsequently_opened_document(
        qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    broken = tmp_path/'roto.pdf'; broken.write_bytes(b'not a PDF')
    shown = []
    monkeypatch.setattr(window, 'print_to_default_v320', lambda: shown.append(True))
    assert window.open_pdf_for_print_v320(broken)
    finished(qtbot, window, error=True)
    assert window._shell_print_v320 is None and not shown
    window.last_error = ''
    assert window.open_document(source_pdf(tmp_path/'otro.pdf'))
    finished(qtbot, window)
    assert not shown


def test_cancelling_password_also_cancels_the_print_request(
        qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    source = source_pdf(tmp_path/'cifrado.pdf', True)
    shown = []
    monkeypatch.setattr(QInputDialog, 'getText', lambda *_: ('', False))
    monkeypatch.setattr(window, 'print_to_default_v320', lambda: shown.append(True))
    assert window.open_pdf_for_print_v320(source)
    finished(qtbot, window)
    assert window._shell_print_v320 is None and not shown


def test_a_tab_change_before_sending_cannot_print_the_wrong_document(qtbot, tmp_path):
    class Window(ShellActionsUiMixin, QMainWindow):
        operation_finished = Signal(str, object)
        error_raised = Signal(str)
        def __init__(self):
            super().__init__()
            self._closed = self.busy = False
            self._active_session_v200 = None
            self.state = {}
            self.printed = []
        def open_document(self, path): return True
        def print_to_default_v320(self): self.printed.append(self._active_session_v200)
    window = Window(); qtbot.addWidget(window)
    source = source_pdf(tmp_path/'elegido.pdf')
    assert window.open_pdf_for_print_v320(source)
    window.state = {'path': str(source), 'session_id': 'selected', 'document_revision': 'first'}
    window._active_session_v200 = 'selected'
    window.operation_finished.emit('open', {'state': dict(window.state)})
    window._active_session_v200 = 'another-tab'
    qtbot.wait(10)
    assert not window.printed


def test_cli_print_routes_only_after_the_window_is_shown(monkeypatch):
    from pdfmodder import app
    events = []
    class Application:
        @staticmethod
        def instance(): return Application()
        def setApplicationName(self, *args): pass
        def setOrganizationName(self, *args): pass
        def setStyle(self, *args): pass
        def exec(self): return 0
    class Window:
        def __init__(self, initial): assert initial is None
        def show(self): events.append('show')
        def start_daily_update_check_v307(self): pass
        def open_pdf_for_print_v320(self, path): events.append(('print', path))
    monkeypatch.setattr(app, 'QApplication', Application)
    monkeypatch.setattr(app, 'MainWindow', Window)
    monkeypatch.setattr(app, '_application_icon', lambda: QIcon())
    monkeypatch.setattr(app, 'QTimer', SimpleNamespace(singleShot=lambda delay, callback: callback()))
    path = r'C:\Facturas con espacios\Documento ñ.pdf'
    assert app.main(['--print', path]) == 0
    assert events == ['show', ('print', path)]
    with pytest.raises(SystemExit):
        app.main(['--print', path, 'otro.pdf'])


def pdf_device(tmp_path, copies=1):
    """Substitute a PDF device only in tests; production requires native output."""
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    output = tmp_path/'sent.pdf'
    printer.setOutputFileName(str(output))
    printer.setResolution(72)
    printer.setCopyCount(copies)
    printer.setPageSize(QPageSize(QPageSize.A5))
    printer.setPageOrientation(QPageLayout.Landscape)
    return {'printer': 'Windows default', 'printer_device_v314': printer,
            'preserve_driver_defaults_v320': True, 'driver_layout': True,
            'page_layout_v314': QPageLayout(printer.pageLayout()),
            'dpi': 72, 'copies': copies, 'collate': printer.collateCopies(),
            'duplex': printer.duplex(), 'color': printer.colorMode(),
            'paper': 0, 'orientation': 2, 'fit': True}, output


def test_system_defaults_use_a_fresh_native_device_without_setting_overrides(qapp, monkeypatch):
    import pdfmodder.printing_direct_v320 as direct
    from pdfmodder.printing_ui_v314 import PrintingUiV314Mixin
    info = SimpleNamespace(isNull=lambda: False, printerName=lambda: 'Windows default')
    layout = QPageLayout(QPageSize(QPageSize.A5), QPageLayout.Landscape, QPageLayout().margins())
    devices = []
    class NativeDevice:
        HighResolution, NativeFormat = QPrinter.HighResolution, QPrinter.NativeFormat
        def __init__(self, selected, mode):
            assert selected is info and mode == QPrinter.HighResolution
            self.private_driver_settings = object()
            devices.append(self)
        def isValid(self): return True
        def printerName(self): return 'Windows default'
        def outputFormat(self): return QPrinter.NativeFormat
        def pageLayout(self): return layout
        def resolution(self): return 1200
        def colorMode(self): return QPrinter.GrayScale
        def duplex(self): return QPrinter.DuplexShortSide
        def copyCount(self): return 3
        def collateCopies(self): return False
        def setDocName(self, value): self.document_name = value
        def __getattr__(self, name):
            if name.startswith('set'):
                pytest.fail('Unexpected driver override: '+name)
            raise AttributeError(name)
    monkeypatch.setattr(direct.QPrinterInfo, 'defaultPrinter', lambda: info)
    monkeypatch.setattr(direct, 'QPrinter', NativeDevice)
    settings = direct.system_default_printer_v320('Factura ñ.pdf')
    owner = SimpleNamespace(state={'path': 'Factura ñ.pdf'})
    device = PrintingUiV314Mixin._make_print_printer_v314(owner, settings)
    assert len(devices) == 1 and device is devices[0]
    assert device.document_name == 'Factura ñ.pdf' and device.resolution() == 1200
    assert settings['copies'] == 3 and not settings['collate']
    assert settings['color'] == QPrinter.GrayScale and settings['duplex'] == QPrinter.DuplexShortSide
    assert settings['page_layout_v314'].isEquivalentTo(layout)


def test_missing_default_printer_reports_error_without_a_dialog(
        qtbot, saving_window, tmp_path, monkeypatch):
    import pdfmodder.printing_direct_v320 as direct
    window = saving_window
    monkeypatch.setattr(direct.QPrinterInfo, 'defaultPrinter', lambda: SimpleNamespace(isNull=lambda: True))
    monkeypatch.setattr(window, '_exec_edit_dialog', lambda *_: pytest.fail('No print dialog'))
    assert window.open_pdf_for_print_v320(source_pdf(tmp_path/'source.pdf'))
    qtbot.waitUntil(lambda: bool(window.last_error), timeout=20000)
    assert 'predeterminada' in window.last_error
    assert getattr(window, '_print_context_v314', None) is None


def test_driver_failure_finishes_without_retrying_or_changing_the_document(
        qtbot, saving_window, tmp_path, monkeypatch):
    import pdfmodder.printing_direct_v320 as direct
    import pdfmodder.printing_device_v314 as device
    window = saving_window
    source = source_pdf(tmp_path/'source.pdf'); original = source.read_bytes()
    settings, _output = pdf_device(tmp_path)
    attempts = []
    def unavailable(*_):
        attempts.append(True)
        raise OSError('Impresora desconectada')
    monkeypatch.setattr(direct, 'system_default_printer_v320', lambda _: settings)
    monkeypatch.setattr(device, 'PrintSpoolV314', unavailable)
    monkeypatch.setattr(window, '_exec_edit_dialog', lambda *_: pytest.fail('No print dialog'))
    assert window.open_pdf_for_print_v320(source)
    qtbot.waitUntil(lambda: bool(window.last_error), timeout=20000)
    assert 'desconectada' in window.last_error and len(attempts) == 1
    assert window._print_context_v314 is None and source.read_bytes() == original


def test_closing_waits_for_the_printer_owner_before_exiting(
        qtbot, saving_window, tmp_path, monkeypatch):
    import threading
    import pdfmodder.printing_direct_v320 as direct
    import pdfmodder.printing_device_v314 as device
    entered, release = threading.Event(), threading.Event()
    window = saving_window
    settings, _output = pdf_device(tmp_path)
    class SlowSpool:
        def __init__(self, printer, settings):
            self.settings = settings; self.error = ''; self.finished = False
        def push(self, page):
            entered.set()
            assert release.wait(5)
            return True
        def cancel(self):
            self.finished = True
            return True
    monkeypatch.setattr(direct, 'system_default_printer_v320', lambda _: settings)
    monkeypatch.setattr(device, 'PrintSpoolV314', SlowSpool)
    try:
        assert window.open_pdf_for_print_v320(source_pdf(tmp_path/'source.pdf'))
        qtbot.waitUntil(entered.is_set, timeout=20000)
        assert not window.close() and not window._closed
        release.set()
        qtbot.waitUntil(lambda: window._closed, timeout=10000)
        assert window._print_context_v314 is None
    finally:
        release.set()
