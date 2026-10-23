"""Persistent printer/theme options and navigation without real print jobs."""
import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPalette
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import QApplication, QLabel

from pdfmodder.appearance_ui_v311 import AppearancePreferencesV311
from pdfmodder.printer_preferences_v311 import PrinterPreferencesV311
from pdfmodder.printing_v309 import PrintDialogV309
from test_tools_ui_v150 import NoPdfPool


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    import pdfmodder.app as application
    app = QApplication.instance()
    palette, style = app.palette(), app.style().objectName()
    previous_theme = app.property('_interfaceThemeV311')
    monkeypatch.setattr(application, 'ProcessPoolExecutor', NoPdfPool)
    monkeypatch.setattr(application.MainWindow, '_offer_recovery_v200', lambda _: None)
    result = application.MainWindow(config_path=tmp_path / 'fonts.json')
    def close(widget):
        widget.state = {}
        widget._allow_close = True
    qtbot.addWidget(result, before_close_func=close)
    for timer in ('poller', 'thumbnail_timer', 'reader_timer_v180'):
        getattr(result, timer).stop()
    result.show()
    yield result
    close(result)
    result.close()
    app.removeEventFilter(result._theme_filter_v311)
    app.setProperty('_interfaceThemeV311', previous_theme)
    app.setStyle(style)
    app.setPalette(palette)


def test_printer_store_separates_profiles_and_ignores_document_ranges(tmp_path):
    store = PrinterPreferencesV311(tmp_path / 'printers.json')
    assert store.read()['enabled']
    store.remember('Oficina', {'paper': 2, 'fit': False, 'dpi': 600, 'copies': 9,
                              'pages': '110-123', 'duplex': QPrinter.DuplexLongSide})
    store.remember('Casa', {'paper': 1, 'dpi': 150})
    again = PrinterPreferencesV311(store.path)
    assert again.settings_for('Oficina') == {'paper': 2, 'fit': False, 'dpi': 600, 'duplex': 2}
    assert again.settings_for('Casa') == {'paper': 1, 'dpi': 150}
    again.set_enabled(False)
    again.remember('Oficina', {'paper': 3})
    assert again.settings_for('Oficina') == {}
    again.set_enabled(True)
    assert again.settings_for('Oficina')['paper'] == 2
    store.path.write_text('{broken')
    assert store.settings_for('Oficina') == {}
    store.remember('Casa', {'dpi': 9999999, 'paper': 999})
    assert json.loads(store.path.read_text())['printers']['Casa'] == {}


def test_printer_switch_restores_profiles_and_driver_limits(qtbot, tmp_path, monkeypatch):
    import pdfmodder.printing_v201 as legacy
    monkeypatch.setattr(QPrinterInfo, 'availablePrinterNames', lambda: ['Color', 'Mono'])
    monkeypatch.setattr(QPrinterInfo, 'defaultPrinterName', lambda: 'Color')
    def caps(name):
        return {'duplex_modes': [QPrinter.DuplexNone] if name == 'Mono' else None,
                'color_modes': [QPrinter.GrayScale] if name == 'Mono' else None}
    monkeypatch.setattr(legacy, 'printer_capabilities_v201', caps)
    store = PrinterPreferencesV311(tmp_path / 'printers.json')
    store.remember('Color', {'paper': 2, 'dpi': 600, 'duplex': QPrinter.DuplexLongSide})
    store.remember('Mono', {'paper': 3, 'color': QPrinter.Color, 'duplex': QPrinter.DuplexLongSide})
    dialog = PrintDialogV309(123, 0, preferences=store)
    dialog.preview_printer.setOutputFormat(QPrinter.PdfFormat)
    qtbot.addWidget(dialog)
    dialog.preview_timer.stop()
    assert dialog.paper.currentIndex() == 2
    assert dialog.duplex.currentData() == QPrinter.DuplexLongSide
    dialog.printer.setCurrentIndex(1)
    assert dialog.paper.currentIndex() == 3
    assert dialog.color.currentData() == QPrinter.GrayScale
    assert dialog.duplex.currentData() == QPrinter.DuplexNone
    dialog.printer.setCurrentIndex(0)
    assert dialog.duplex.currentData() == QPrinter.DuplexLongSide
    assert dialog.dpi.value() == 600
    assert dialog.copies.value() == 1 and dialog.scope.currentData() == 'all'
    dialog.reject()
    assert store.settings_for('Mono')['color'] == 1  # Cancel saves nothing.


def test_configuration_theme_persists_and_keeps_pdf_artwork(window, qtbot):
    win = window
    image = QImage(40, 40, QImage.Format_RGB32)
    image.fill(Qt.white)
    from PySide6.QtGui import QPixmap
    item = win.canvas.scene().addPixmap(QPixmap.fromImage(image))
    original_image = item.pixmap().toImage()
    win.theme_actions_v311['dark'].trigger()
    assert QApplication.palette().color(QPalette.Window).lightness() < 80
    assert win.theme_actions_v311['dark'].isChecked()
    assert AppearancePreferencesV311(win._appearance_preferences_v311.path).read() == 'dark'
    assert win.canvas.editor.palette().color(QPalette.Base) == Qt.white
    assert item.pixmap().toImage() == original_image
    label = QLabel('Nuevo diálogo', win)
    label.setStyleSheet('color: #22384a; background: #e6eff5;')
    label.ensurePolished()
    assert '#e6eaf0' in label.styleSheet()
    win._notice('Comprobación de aviso')
    assert '#283f51' in win.message.styleSheet()
    win.theme_actions_v311['light'].trigger()
    assert QApplication.palette().color(QPalette.Window).lightness() > 200
    assert '#22384a' in label.styleSheet()
    win.remember_printers_action_v311.trigger()
    assert not PrinterPreferencesV311(win._printer_preferences_v311.path).read()['enabled']


def test_toolbar_priorities_keep_menu_commands_and_typed_page(window, qtbot, monkeypatch):
    win = window
    actions = win.toolbar.actions()
    for action in (win.save_as_action_v300, win.save_all_action_v300,
                   win.document_properties_action, win.document_security_action, win.reading_action):
        assert action not in actions
    for action in (win.save_as_action_v300, win.save_all_action_v300,
                   win.document_properties_action, win.document_security_action):
        assert action in win.file_menu_v308.actions()
    assert win.highlight_action in actions
    assert actions.index(win.next_page_action_v311) < actions.index(win.print_action_v200)
    calls = []
    monkeypatch.setattr(win, 'go_page', lambda page: calls.append(page))
    win.state = {'page_count': 123, 'path': 'synthetic.pdf'}
    win._refresh_toolbar_v311()
    box = win.page_number_box_v311
    box.setFocus()
    box.lineEdit().selectAll()
    qtbot.keyClicks(box, '37')
    win._refresh_toolbar_v311()
    assert '37' in box.text()
    qtbot.keyClick(box, Qt.Key_Return)
    assert calls == [36]
    win._command, win.future = 'page', object()
    win._refresh_toolbar_v311()
    assert win.next_page_action_v311.isEnabled() and box.isEnabled()
    win._command = 'apply'
    win._refresh_toolbar_v311()
    assert not win.next_page_action_v311.isEnabled() and not box.isEnabled()
    win.future = None


def test_hand_scrolls_without_selecting_and_select_tool_restores_cursor(window, qtbot):
    win = window
    win.state = {'page_count': 2}
    win.reader.reset_document([{'width': 500., 'height': 1200.}]*2, zoom=1.)
    win._refresh_toolbar_v311()
    view = win.reader
    bar = view.verticalScrollBar()
    bar.setValue(100)
    selections = []
    view.selection_changed.connect(selections.append)
    before = bar.value()
    win.hand_action_v311.trigger()
    assert view.viewport().cursor().shape() == Qt.OpenHandCursor
    qtbot.mousePress(view.viewport(), Qt.LeftButton, pos=QPoint(100, 160))
    assert view.viewport().cursor().shape() == Qt.ClosedHandCursor
    qtbot.mouseMove(view.viewport(), QPoint(100, 90))
    qtbot.mouseRelease(view.viewport(), Qt.LeftButton, pos=QPoint(100, 90))
    assert bar.value() > before and selections == []
    assert bar.cursor().shape() == Qt.ArrowCursor
    win.mode_actions_v170['select'].trigger()
    assert not win.hand_action_v311.isChecked()
    assert view.viewport().cursor().shape() == Qt.IBeamCursor
