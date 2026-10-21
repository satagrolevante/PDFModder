"""Scrollbars keep a navigation cursor when the PDF surface uses a tool cursor."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QApplication
import pytest

from pdfmodder.canvas import PdfCanvas
from pdfmodder.continuous_reader_v180 import ContinuousReader
from test_continuous_reader_v180 import model, png


def move_to_bars_and_back(qtbot, widget, text_point, expected):
    qtbot.mouseMove(widget.viewport(), text_point)
    assert widget.viewport().cursor().shape() == expected
    for bar in (widget.verticalScrollBar(), widget.horizontalScrollBar()):
        assert bar.isVisible()
        before = bar.value()
        qtbot.mouseMove(bar, bar.rect().center())
        assert bar.cursor().shape() == Qt.ArrowCursor
        assert bar.value() == before
        qtbot.mouseMove(widget.viewport(), text_point)
        assert widget.viewport().cursor().shape() == expected


def test_continuous_reader_cursor_changes_from_text_to_each_scrollbar_and_back(qtbot):
    widget = ContinuousReader()
    qtbot.addWidget(widget)
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    widget.resize(230, 270)
    widget.show()
    widget.reset_document([{'width': 320., 'height': 600.}], zoom=1.)
    current, rows = model(0)
    widget.set_page(0, png(), current, 1.)
    widget.reveal_rect(0, rows[0][0].bbox)
    QApplication.processEvents()
    page = widget._rects[0]
    point = widget.mapFromScene(QPointF(page.left() + 39., page.top() + 96.))
    assert widget.viewport().rect().contains(point)
    assert widget._endpoint_at(point) is not None
    move_to_bars_and_back(qtbot, widget, point, Qt.IBeamCursor)


@pytest.mark.parametrize(('mode', 'expected'), [
    ('reading', Qt.IBeamCursor), ('write', Qt.IBeamCursor),
    ('move', Qt.SizeAllCursor), ('signature', Qt.CrossCursor),
])
def test_canvas_bars_override_the_view_cursor_without_changing_tools(qtbot, mode, expected):
    widget = PdfCanvas()
    qtbot.addWidget(widget)
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    widget.resize(230, 270)
    current, _rows = model(0)
    widget.set_page(png(), current, 1.)
    widget.show()
    widget.ensureVisible(QRectF(35., 90., 80., 14.), 2, 2)
    if mode == 'reading':
        widget.reading_mode = True
    elif mode == 'signature':
        widget.begin_signature_rectangle()
    else:
        widget.set_interaction_mode(mode)
    QApplication.processEvents()
    point = widget.mapFromScene(QPointF(39., 96.))
    assert widget.viewport().rect().contains(point)
    move_to_bars_and_back(qtbot, widget, point, expected)
