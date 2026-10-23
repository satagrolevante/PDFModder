"""The left panel collapses without losing content, width or its restore button."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from test_tools_ui_v150 import NoPdfPool


@pytest.fixture
def sidebar_window(qtbot, monkeypatch):
    import pdfmodder.app as application
    monkeypatch.setattr(application, 'ProcessPoolExecutor', NoPdfPool)
    monkeypatch.setattr(application.MainWindow, '_offer_recovery_v200', lambda _self: None)
    window = application.MainWindow()
    def allow_close(widget):
        widget.state = {}
        widget._allow_close = True
    qtbot.addWidget(window, before_close_func=allow_close)
    for name in ('poller', 'thumbnail_timer', 'reader_timer_v180'):
        getattr(window, name).stop()
    window.tools_action.setChecked(True)
    window.show()
    QApplication.processEvents()
    yield window
    allow_close(window)
    window.close()


def test_corner_button_collapses_and_visible_rail_restores_same_tab(sidebar_window, qtbot):
    window = sidebar_window
    window.workspace_tabs_v170.setCurrentIndex(1)
    before = window.document_splitter.sizes()
    zoom = window.zoom
    qtbot.mouseClick(window.sidebar_collapse_button_v311, Qt.LeftButton)
    QApplication.processEvents()
    after = window.document_splitter.sizes()
    assert not window.workspace_tabs_v170.isVisible()
    assert window.sidebar_host_v311.width() == 26
    assert not window.document_splitter.isCollapsible(0)
    assert window.sidebar_restore_button_v311.isVisible()
    assert not window.thumbnail_action.isChecked()
    assert after[1] > before[1]+150
    assert abs(after[2]-before[2]) <= 1
    qtbot.mouseClick(window.sidebar_restore_button_v311, Qt.LeftButton)
    QApplication.processEvents()
    restored = window.document_splitter.sizes()
    assert window.workspace_tabs_v170.isVisible()
    assert window.workspace_tabs_v170.currentIndex() == 1
    assert window.thumbnail_action.isChecked()
    assert not window.sidebar_restore_button_v311.isVisible()
    assert abs(restored[0]-before[0]) <= 1
    assert abs(restored[2]-before[2]) <= 1
    assert window.zoom == zoom


def test_menu_toggle_and_corner_share_one_state_and_keep_pages_visible(sidebar_window, qtbot):
    window = sidebar_window
    window.pages.set_page_count_v300(123)
    window.pages.setCurrentRow(50)
    QApplication.processEvents()
    current = window.pages.currentRow()
    scroll = window.pages.verticalScrollBar().value()
    window.thumbnail_action.trigger()
    QApplication.processEvents()
    assert window.sidebar_restore_button_v311.isVisible()
    window.thumbnail_action.trigger()
    QApplication.processEvents()
    assert window.pages.isVisible()
    assert window.pages.currentRow() == current
    assert window.pages.verticalScrollBar().value() == scroll
    assert window.pages.count() == 123
    assert window.sidebar_collapse_button_v311.isVisible()


def test_disabled_shared_action_prevents_collapsing_or_restoring(sidebar_window, qtbot):
    window = sidebar_window
    window.thumbnail_action.setEnabled(False)
    assert not window.sidebar_collapse_button_v311.isEnabled()
    qtbot.mouseClick(window.sidebar_collapse_button_v311, Qt.LeftButton)
    assert window.workspace_tabs_v170.isVisible()
    window.thumbnail_action.setEnabled(True)
    window.thumbnail_action.trigger()
    window.thumbnail_action.setEnabled(False)
    assert not window.sidebar_restore_button_v311.isEnabled()
    qtbot.mouseClick(window.sidebar_restore_button_v311, Qt.LeftButton)
    assert not window.workspace_tabs_v170.isVisible()
