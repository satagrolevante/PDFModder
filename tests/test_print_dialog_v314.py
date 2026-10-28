"""One print window, valid driver defaults and truthful/cancellable progress."""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import QDialog

from pdfmodder.printing_dialog_v314 import PrintDialogV314
from pdfmodder.printer_preferences_v311 import PrinterPreferencesV311


@pytest.fixture
def dialog_factory(qtbot, monkeypatch):
    import pdfmodder.printing_dialog_v314 as ui
    import pdfmodder.printing_v201 as legacy
    monkeypatch.setattr(QPrinterInfo, 'availablePrinterNames', lambda: ['Oficina', 'Mono'])
    monkeypatch.setattr(QPrinterInfo, 'defaultPrinterName', lambda: 'Oficina')
    state = {'unavailable': False}
    def caps(name):
        if state['unavailable']:
            raise ValueError('La impresora seleccionada ya no está disponible.')
        return {'duplex_modes': [QPrinter.DuplexNone] if name == 'Mono' else
                [QPrinter.DuplexNone, QPrinter.DuplexLongSide, QPrinter.DuplexShortSide, QPrinter.DuplexAuto],
                'color_modes': [QPrinter.GrayScale] if name == 'Mono' else None}
    monkeypatch.setattr(legacy, 'printer_capabilities_v201', caps)
    def device(name):
        result = QPrinter(QPrinter.HighResolution)
        result.setOutputFormat(QPrinter.PdfFormat)
        # All output in these tests remains PDF; no OS printer is used.
        result.printerName = lambda: name
        return result
    monkeypatch.setattr(ui, '_new_device_v314', device)
    def defaults(name, printer):
        return {'color': QPrinter.Color, 'duplex': QPrinter.DuplexLongSide,
                'dpi': 300, 'paper': 1, 'orientation': 1, 'collate': True,
                'fit': True, 'driver_layout': True, 'copies': 1}
    monkeypatch.setattr(ui, '_defaults_v314', defaults)
    def create(preferences=None):
        result = PrintDialogV314(123, 0, preferences=preferences)
        result.preview_printer.setOutputFormat(QPrinter.PdfFormat)
        qtbot.addWidget(result)
        result.show()
        result.preview_timer.stop()
        return result
    return create, state


def test_driver_defaults_and_saved_profile_capability_warning(dialog_factory, tmp_path):
    create, _ = dialog_factory
    initial = create()
    assert initial.duplex.currentData() == QPrinter.DuplexLongSide
    assert initial.settings()['driver_layout']
    store = PrinterPreferencesV311(tmp_path / 'printers.json')
    store.remember('Oficina', {'duplex': QPrinter.DuplexShortSide, 'paper': 2})
    store.remember('Mono', {'duplex': QPrinter.DuplexLongSide, 'color': QPrinter.Color})
    dialog = create(store)
    assert dialog.duplex.currentData() == QPrinter.DuplexShortSide
    assert dialog.paper.currentIndex() == 2
    assert not dialog.settings()['driver_layout']
    dialog.printer.setCurrentIndex(1)
    assert dialog.duplex.currentData() == QPrinter.DuplexNone
    assert dialog.color.currentData() == QPrinter.GrayScale
    assert 'Una cara' in dialog.profile_notice_v314.text()
    assert 'Escala de grises' in dialog.profile_notice_v314.text()


def test_unavailable_printer_error_survives_range_changes_and_can_refresh(dialog_factory):
    create, state = dialog_factory
    state['unavailable'] = True
    dialog = create()
    assert 'no está disponible' in dialog.error.text()
    assert not dialog.print_button.isEnabled()
    dialog.scope.setCurrentIndex(dialog.scope.findData('range'))
    dialog.pages.setText('1-4')
    assert 'no está disponible' in dialog.error.text()
    assert not dialog.print_button.isEnabled()
    state['unavailable'] = False
    dialog._refresh_printer_v314()
    assert dialog.print_button.isEnabled()
    assert not dialog.error.text()


def test_new_page_hides_previous_image_but_color_keeps_valid_image(dialog_factory, tmp_path):
    create, _ = dialog_factory
    dialog = create()
    image = QImage(60, 80, QImage.Format_RGB32)
    image.fill(QColor('red'))
    path = tmp_path / 'page.png'
    assert image.save(str(path))
    dialog.show_preview({'page': 0, 'path': str(path), 'width': 60., 'height': 80., 'dpi': 120.}, dialog.settings())
    assert dialog.preview_stack.currentWidget() is dialog.preview
    dialog.color.setCurrentIndex(dialog.color.findData(QPrinter.GrayScale))
    assert dialog.preview_stack.currentWidget() is dialog.preview
    assert dialog._preview_image.pixelColor(0, 0) == QColor('red')
    dialog.page.setValue(2)
    assert 'Página original 2' in dialog.summary.text()
    assert dialog.preview_stack.currentWidget() is dialog.placeholder
    assert 'página 2' in dialog.placeholder.text()
    assert dialog._preview_page['page'] == 0  # Cached, but no longer presented as page 2.


def test_cancel_during_incremental_spooling_waits_for_controller_cleanup(dialog_factory, qtbot):
    create, _ = dialog_factory
    dialog = create()
    cancellations = []
    dialog.cancel_requested.connect(lambda: cancellations.append(True))
    dialog.set_preparing(True)
    dialog.set_spooling(True)
    dialog.set_progress(2, 123, 'Enviando')
    assert dialog.cancel_button.isEnabled()
    assert dialog.progress_v314.maximum() == 123
    assert 'Enviando: 2 de 123' in dialog.status.text()
    qtbot.mouseClick(dialog.cancel_button, Qt.LeftButton)
    assert cancellations == [True]
    assert dialog.isVisible()
    assert not dialog.cancel_button.isEnabled()
    dialog.reject()
    assert cancellations == [True]
    dialog.finish_cancel()
    assert not dialog.isVisible()


def test_properties_is_optional_and_retains_configured_device(dialog_factory, monkeypatch):
    import pdfmodder.printing_dialog_v314 as ui
    create, _ = dialog_factory
    dialog = create()
    calls = []
    class Properties:
        def exec(self):
            calls.append(True)
            device = dialog._native_printer_v314
            device.setCopyCount(3)
            device.setPageOrientation(QPageLayout.Landscape)
            return QDialog.Accepted
    monkeypatch.setattr(dialog, '_properties_dialog_v314', lambda device: Properties())
    monkeypatch.setattr(ui, '_defaults_v314', lambda name, device: {
        'color': QPrinter.Color, 'duplex': QPrinter.DuplexLongSide, 'dpi': 300,
        'paper': 1, 'orientation': 2, 'collate': True, 'fit': True, 'driver_layout': True})
    assert calls == []
    dialog._choose_properties_v314()
    assert calls == [True]
    assert dialog.copies.value() == 3
    assert dialog.settings()['printer_device_v314'] is dialog._native_printer_v314
    assert dialog.settings()['driver_layout']
    assert dialog.orientation.currentIndex() == 2
    dialog.paper.setCurrentIndex(2)
    assert not dialog.settings()['driver_layout']


def test_preview_preserves_real_device_printable_margins(dialog_factory,tmp_path):
    from PySide6.QtCore import QMarginsF
    create,_=dialog_factory
    dialog=create()
    device=dialog._native_printer_v314
    layout=device.pageLayout()
    assert layout.setMargins(QMarginsF(20,30,20,30))
    assert device.setPageLayout(layout)
    image=QImage(60,80,QImage.Format_RGB32);image.fill(0xffffffff)
    path=tmp_path/'margins.png';image.save(str(path))
    page={'page':0,'path':str(path),'width':300.,'height':450.,'dpi':120}
    dialog.show_preview(page,dialog.settings())
    assert dialog.preview_printer.pageLayout().margins()==device.pageLayout().margins()
