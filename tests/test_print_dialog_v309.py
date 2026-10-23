"""One print window and bounded inline preview, without physical print jobs."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewWidget
from pdfmodder.model import EditError


@pytest.fixture
def print_dialog(qtbot, monkeypatch):
    from pdfmodder import printing_v201 as legacy
    from pdfmodder import printing_v309 as printing

    capabilities = {'duplex_modes': [QPrinter.DuplexNone, QPrinter.DuplexLongSide],
                    'color_modes': [QPrinter.Color, QPrinter.GrayScale]}
    monkeypatch.setattr(legacy, 'printer_capabilities_v201', lambda name: capabilities)
    monkeypatch.setattr(printing, 'printer_capabilities_v201', lambda name: capabilities)

    def create(names=()):
        monkeypatch.setattr(legacy.QPrinterInfo, 'availablePrinterNames', lambda: list(names))
        monkeypatch.setattr(legacy.QPrinterInfo, 'defaultPrinterName', lambda: names[0] if names else '')
        dialog = printing.PrintDialogV309(123, 42)
        dialog.preview_printer.setOutputFormat(QPrinter.PdfFormat)
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.preview_timer.stop()
        return dialog

    return create


def test_no_printer_keeps_inline_preview_and_disables_print(print_dialog, qtbot):
    dialog = print_dialog()
    assert dialog.isVisible()
    assert dialog.findChildren(QPrintPreviewWidget) == [dialog.preview]
    assert not dialog.preview.isWindow()
    assert dialog.preview_printer.outputFormat() == QPrinter.PdfFormat
    assert not dialog.print_button.isEnabled()
    assert dialog.selected_pages() == list(range(123))
    requests = []
    dialog.print_requested.connect(lambda: requests.append('print'))
    qtbot.mouseClick(dialog.print_button, Qt.LeftButton)
    assert requests == []
    qtbot.mouseClick(dialog.cancel_button, Qt.LeftButton)
    assert not dialog.isVisible()


def test_direct_print_does_not_require_preview_or_close_options(print_dialog, qtbot):
    dialog = print_dialog(('Impresora de pruebas',))
    requests = []
    dialog.print_requested.connect(lambda: requests.append(dialog.selected_pages()))
    assert dialog._preview_image is None and dialog.preview.pageCount() == 0
    assert dialog.print_button.isEnabled()
    dialog.scope.setCurrentIndex(dialog.scope.findData('current'))
    dialog.preview_timer.stop()
    qtbot.mouseClick(dialog.print_button, Qt.LeftButton)
    assert requests == [[42]]
    assert dialog.isVisible()
    assert dialog.preview.pageCount() == 0


def test_selected_original_pages_navigation_and_invalid_ranges(print_dialog, qtbot):
    dialog = print_dialog(('Impresora de pruebas',))
    dialog.scope.setCurrentIndex(dialog.scope.findData('current'))
    assert dialog.selected_pages() == [42]
    assert dialog.page.maximum() == 1
    dialog.scope.setCurrentIndex(dialog.scope.findData('range'))
    dialog.pages.setText('7,3-4,7')
    assert dialog.selected_pages() == [6, 2, 3]
    assert dialog.page.maximum() == 3
    dialog.page.setValue(2)
    assert 'original 3' in dialog.summary.text()
    assert dialog.previous.isEnabled() and dialog.following.isEnabled()
    requests = []
    dialog.print_requested.connect(lambda: requests.append('print'))
    dialog.pages.setText('124')
    assert dialog.error.text()
    assert not dialog.print_button.isEnabled()
    qtbot.mouseClick(dialog.print_button, Qt.LeftButton)
    assert requests == []
    with pytest.raises(EditError, match=r'(?i)(página|intervalo|123)'):
        dialog.selected_pages()
    dialog.pages.setText('1,123')
    assert dialog.print_button.isEnabled()
    assert dialog.selected_pages() == [0, 122]
    dialog.preview_timer.stop()


def test_preview_owns_page_image_after_worker_file_is_removed(print_dialog, tmp_path):
    dialog = print_dialog()
    path = tmp_path / 'preview.png'
    image = QImage(400, 300, QImage.Format_RGB32)
    image.fill(QColor('red'))
    assert image.save(str(path))
    settings = dialog.settings()
    dialog.show_preview({'page': 0, 'path': str(path), 'width': 400., 'height': 300., 'dpi': 120.}, settings)
    assert dialog.preview.pageCount() == 1
    assert dialog._preview_image.pixelColor(0, 0) == QColor('red')
    assert not dialog.error.text()
    path.unlink()
    settings.update(color=QPrinter.GrayScale, orientation=2)
    dialog.redraw_preview(settings)
    assert dialog.preview.pageCount() == 1
    assert not dialog.error.text()
    assert dialog._preview_image.pixelColor(0, 0) == QColor('red')
    assert dialog.preview_stack.currentWidget() is dialog.preview
    assert not path.exists()


def test_preparing_prevents_duplicate_print_and_restores_editable_settings(print_dialog, qtbot):
    dialog = print_dialog(('Impresora de pruebas',))
    requests = []
    dialog.print_requested.connect(lambda: requests.append('print'))
    dialog.set_preparing(True)
    assert not dialog.options_scroll.isEnabled()
    assert not dialog.page.isEnabled()
    assert not dialog.print_button.isEnabled()
    assert dialog.cancel_button.isEnabled()
    qtbot.mouseClick(dialog.print_button, Qt.LeftButton)
    assert requests == []
    dialog.set_preparing(False)
    assert dialog.options_scroll.isEnabled()
    assert dialog.page.isEnabled()
    assert dialog.print_button.isEnabled()
    dialog.set_spooling(True)
    assert not dialog.cancel_button.isEnabled()
    dialog.reject()
    assert dialog.isVisible()
    dialog.set_spooling(False)
    qtbot.mouseClick(dialog.cancel_button, Qt.LeftButton)
    assert not dialog.isVisible()
