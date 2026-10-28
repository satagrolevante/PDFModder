"""Exercise direct printing, stale preview replies and cancellation safely."""
from pathlib import Path

import pymupdf as fitz
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import QMainWindow

from pdfmodder.printing_v309 import PrintingV309Mixin, PrintDialogV309
from test_saving_v300 import saving_window, open_editing


@pytest.fixture
def printer_names(monkeypatch):
    from PySide6.QtPrintSupport import QPrinterInfo
    import pdfmodder.printing_v201 as legacy
    import pdfmodder.printing_v309 as printing
    monkeypatch.setattr(QPrinterInfo, 'availablePrinterNames', lambda: ['Impresora de prueba'])
    monkeypatch.setattr(QPrinterInfo, 'defaultPrinterName', lambda: 'Impresora de prueba')
    caps = lambda _name: {'duplex_modes': None, 'color_modes': None}
    monkeypatch.setattr(legacy, 'printer_capabilities_v201', caps)
    monkeypatch.setattr(printing, 'printer_capabilities_v201', caps)
    # A regression must never open the native confirmation or send a real job.
    monkeypatch.setattr(QPrintDialog, '__init__', lambda *_: pytest.fail('Native print dialog opened'))


class Harness(PrintingV309Mixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = {'document_revision': 'revision', 'path': 'source.pdf'}
        self._active_session_v200 = 'session'
        self._closed = False
        self.busy = False
        self.requests = []
        self.painted = []
        self.last_error = ''

    def _submit(self, command, payload, callback):
        assert not self.busy
        self.busy = True
        self.requests.append((command, payload, callback))
        return True

    def _make_print_printer_v309(self, settings):
        return object()

    def _paint_print_v200(self, printer, pages, settings):
        self.painted.append(([page['page'] for page in pages], settings))
        return True

    def _notice(self, text):
        pass


def context_for(qtbot, window):
    dialog = PrintDialogV309(123, 0)
    dialog.preview_printer.setOutputFormat(QPrinter.PdfFormat)
    qtbot.addWidget(dialog)
    dialog.preview_timer.stop()
    timer = QTimer(dialog)
    timer.setSingleShot(True)
    context = {'dialog': dialog, 'session': 'session', 'revision': 'revision',
               'closed': False, 'serial': 0, 'pending': None, 'inflight': None,
               'job': None, 'timer': timer}
    return context


def finish_request(window, index, tmp_path):
    _, payload, callback = window.requests[index]
    image = QImage(100, 150, QImage.Format_RGB32)
    image.fill(0xffffffff)
    path = tmp_path / f'preview-{index}.png'
    assert image.save(str(path))
    pages = [{'page': number, 'path': str(path), 'width': 300., 'height': 450.,
              'dpi': payload['dpi']} for number in payload['pages']]
    window.busy = False
    callback({'pages': pages, 'revision': 'revision'})


def test_print_queues_behind_preview_and_prevents_further_preview_work(qtbot, printer_names, tmp_path):
    window = Harness()
    qtbot.addWidget(window)
    context = context_for(qtbot, window)
    dialog = context['dialog']
    window._request_preview_v309(context)
    window._pump_print_v309(context)
    assert window.requests[0][1] == {'pages': [0], 'dpi': 120}
    dialog.scope.setCurrentIndex(dialog.scope.findData('range'))
    dialog.pages.setText('5,2-3')
    window._request_print_v309(context)
    assert context['job'][0] == [4, 1, 2]
    assert not dialog.print_button.isEnabled()
    window._request_preview_v309(context)
    assert context['pending'] is None
    finish_request(window, 0, tmp_path)
    assert dialog._preview_image is None, 'Obsolete preview must not become current'
    window._pump_print_v309(context)
    assert window.requests[1][1] == {'pages': [4, 1, 2], 'dpi': 300}
    finish_request(window, 1, tmp_path)
    assert window.painted[0][0] == [4, 1, 2]
    assert len(window.requests) == 2
    dialog.preview_timer.stop()
    context['timer'].stop()


@pytest.mark.parametrize('cancel_kind', ['closed', 'revision'])
def test_cancel_or_changed_revision_cannot_print_late_result(qtbot, printer_names, tmp_path, cancel_kind):
    window = Harness()
    qtbot.addWidget(window)
    context = context_for(qtbot, window)
    window._request_print_v309(context)
    window._pump_print_v309(context)
    if cancel_kind == 'closed':
        context['closed'] = True
    else:
        window.state['document_revision'] = 'changed'
    finish_request(window, 0, tmp_path)
    assert not window.painted
    context['timer'].stop()


def test_style_changes_reuse_decoded_preview_without_another_pdf_request(qtbot, printer_names, tmp_path):
    window = Harness()
    qtbot.addWidget(window)
    context = context_for(qtbot, window)
    dialog = context['dialog']
    window._request_preview_v309(context)
    window._pump_print_v309(context)
    finish_request(window, 0, tmp_path)
    (tmp_path / 'preview-0.png').unlink()
    dialog.color.setCurrentIndex(dialog.color.findData(QPrinter.GrayScale))
    window._request_preview_v309(context)
    assert context['pending'] is None and len(window.requests) == 1
    assert dialog._preview_settings['color'] == QPrinter.GrayScale
    assert not dialog.error.text()
    dialog.preview_timer.stop()
    context['timer'].stop()


def test_failed_preparation_unlocks_controls_and_cannot_send_a_job(qtbot, printer_names):
    window = Harness()
    qtbot.addWidget(window)
    context = context_for(qtbot, window)
    dialog = context['dialog']
    window._request_print_v309(context)
    window._pump_print_v309(context)
    window.busy = False
    window._print_failed_v309(context, 'El documento no permite imprimir.')
    assert context['job'] is None and not window.painted
    assert dialog.print_button.isEnabled() and dialog.options_scroll.isEnabled()
    assert 'no permite' in dialog.error.text()
    dialog.preview_timer.stop()
    context['timer'].stop()


def test_events_during_spooling_cannot_prepare_a_second_job(qtbot, printer_names):
    window = Harness()
    qtbot.addWidget(window)
    context = context_for(qtbot, window)
    window._request_print_v309(context)
    context['dialog'].set_spooling(True)
    window._pump_print_v309(context)
    assert not window.requests
    context['dialog'].set_spooling(False)
    context['timer'].stop()


def test_direct_print_opens_one_dialog_and_produces_exact_pdf_pages(qtbot, saving_window, printer_names, tmp_path, monkeypatch):
    window = saving_window
    source = tmp_path / 'original.pdf'
    with fitz.open() as document:
        document.new_page(width=300, height=400).insert_text((30, 50), 'Primera')
        document.new_page(width=500, height=300).insert_text((30, 50), 'Segunda')
        document.save(source)
    original = source.read_bytes()
    open_editing(qtbot, window, source)
    target = tmp_path / 'impresion.pdf'
    calls, requested = [], []
    original_submit = window._submit
    def submit(command, payload=None, callback=None):
        if command == 'print_pages_v200':
            requested.append(dict(payload))
        return original_submit(command, payload, callback)
    monkeypatch.setattr(window, '_submit', submit)
    def printer(settings):
        from pdfmodder.printing_v201 import configure_printer_v201
        device = QPrinter(QPrinter.HighResolution)
        device.setOutputFormat(QPrinter.PdfFormat)
        device.setOutputFileName(str(target))
        configure_printer_v201(device, dict(settings, printer=''))
        return device
    monkeypatch.setattr(window, '_make_print_printer_v309', printer)
    monkeypatch.setattr(window, '_make_print_printer_v314', printer)
    execute = window._exec_edit_dialog
    def single_dialog(dialog):
        calls.append(dialog)
        def print_now():
            dialog.scope.setCurrentIndex(dialog.scope.findData('range'))
            dialog.pages.setText('2,1')
            dialog.paper.setCurrentIndex(0)
            dialog.dpi.setValue(72)
            dialog.color.setCurrentIndex(dialog.color.findData(QPrinter.GrayScale))
            dialog.print_button.click()
        QTimer.singleShot(0, print_now)
        # Fail promptly rather than hanging a modal loop on a regression.
        watchdog = QTimer(dialog)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(dialog.reject)
        watchdog.start(30000)
        try:
            return execute(dialog)
        finally:
            watchdog.stop()
    monkeypatch.setattr(window, '_exec_edit_dialog', single_dialog)
    window.print_action_v200.trigger()
    assert len(calls) == 1 and isinstance(calls[0], PrintDialogV309)
    assert [item['pages'] for item in requested] == [[1], [0]]
    assert all(item['dpi'] == 72 and item['revision'] and item['control'] for item in requested)
    assert not window.last_error, window.last_error
    with fitz.open(target) as printed:
        assert len(printed) == 2
        assert [(page.rect.width, page.rect.height) for page in printed] == [(500., 300.), (300., 400.)]
    assert source.read_bytes() == original
    from pdfmodder.printer_preferences_v311 import PrinterPreferencesV311
    remembered = PrinterPreferencesV311(window._printer_preferences_v311.path).settings_for('Impresora de prueba')
    assert remembered['paper'] == 0 and remembered['dpi'] == 72
    assert remembered['color'] == QPrinter.GrayScale.value
    assert 'copies' not in remembered and 'pages' not in remembered
