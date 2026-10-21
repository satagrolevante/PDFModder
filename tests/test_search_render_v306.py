"""Search decoration follows result fragments, page rotation and the active result."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication
import pytest

from pdfmodder.canvas import PdfCanvas
from pdfmodder.continuous_reader_v180 import ContinuousReader
from pdfmodder.model import PageModel
from test_continuous_reader_v180 import png


def page_model(number=0, rotated=False):
    matrix = (0., 1., -1., 0., 200., 0.) if rotated else (1., 0., 0., 1., 0., 0.)
    inverse = (0., -1., 1., 0., 0., 200.) if rotated else matrix
    return PageModel(number, 200. if rotated else 320., 320. if rotated else 200.,
                     90 if rotated else 0, matrix, inverse, (0., 0., 320., 200.), [])


def view(qtbot, count=3):
    widget = ContinuousReader()
    qtbot.addWidget(widget)
    widget.resize(500, 570)
    widget.show()
    widget.reset_document([{'width': 320., 'height': 200.} for _ in range(count)], zoom=1.)
    for number in range(min(2, count)):
        widget.set_page(number, png(320, 200), page_model(number), 1.)
    QApplication.processEvents()
    return widget


def active_items(items):
    return [item for item in items if item.pen().color().name() == '#b94b00']


def test_current_multiline_result_is_distinct_from_other_results(qtbot):
    widget = view(qtbot)
    first = (35., 90., 75., 104.)
    second = (35., 160., 95., 174.)
    widget.set_search_matches([
        {'page': 0, 'rect': first},
        {'page': 1, 'rect': (35., 90., 95., 174.), 'rects': [first, second]},
        {'page': 2, 'rect': first},  # Not loaded: no decoration for this page.
    ])
    widget.set_active_search_match(1)
    assert len(widget._search_overlays) == 3
    active = active_items(widget._search_overlays)
    assert len(active) == 2
    assert all(item.pen().widthF() == 2. and item.pen().isCosmetic() for item in active)
    assert all(item.zValue() > 1 and item.acceptedMouseButtons() == Qt.NoButton for item in active)
    assert len({item.brush().color().rgba() for item in widget._search_overlays}) == 2
    page = widget._rects[1]
    expected = [QRectF(page.left() + rect[0], page.top() + rect[1], rect[2] - rect[0], rect[3] - rect[1])
                for rect in (first, second)]
    assert [item.rect() for item in active] == expected
    # Navigate back using the global index, not the fragment count.
    widget.set_active_search_match(0)
    assert len(active_items(widget._search_overlays)) == 1
    assert active_items(widget._search_overlays)[0].rect().top() == pytest.approx(widget._rects[0].top() + 90.)
    widget.set_active_search_match(-1)
    assert not active_items(widget._search_overlays)


def test_search_results_are_virtual_and_reset_drops_the_active_result(qtbot):
    widget = view(qtbot, count=10000)
    widget.set_search_matches([{'page': number, 'rect': (35., 90., 75., 104.)}
                               for number in range(10000)])
    assert len(widget._search_overlays) == 2
    widget.set_active_search_match(9999)
    assert len(widget._search_overlays) == 2
    assert not active_items(widget._search_overlays)
    widget.reset_document([{'width': 320., 'height': 200.}], zoom=1.)
    assert not widget._search_matches and not widget._search_by_page
    assert widget._active_search_index == -1 and not widget._search_overlays


def test_active_result_uses_rotated_page_coordinates_and_preserves_page_items(qtbot):
    widget = view(qtbot, count=1)
    widget.set_page(0, png(200, 320), page_model(rotated=True), 1.)
    existing_image = widget._images[0][1]
    widget.set_search_matches([{'page': 0, 'rect': (35., 90., 75., 104.)}])
    widget.set_active_search_match(0)
    active = active_items(widget._search_overlays)
    assert len(active) == 1
    page = widget._rects[0]
    assert active[0].rect() == QRectF(page.left() + 96., page.top() + 35., 14., 40.)
    assert widget._images[0][1] is existing_image
    widget.set_search_matches([])
    assert not widget._search_overlays and widget._active_search_index == -1
    assert widget._images[0][1] is existing_image


def test_editing_canvas_active_fragments_remain_distinct_after_selection_redraw(qtbot):
    widget = PdfCanvas()
    qtbot.addWidget(widget)
    widget.set_page(png(200, 320), page_model(rotated=True), 1.)
    widget.search_rects = [(35., 90., 75., 104.), (35., 160., 95., 174.)]
    widget.active_search_rects = list(widget.search_rects)
    widget.set_selection([])
    assert len(widget.overlays) == 4
    active = active_items(widget.overlays)
    assert len(active) == 2
    assert active[0].rect() == QRectF(96., 35., 14., 40.)
    assert all(item.pen().widthF() == 2. and item.zValue() == 3 for item in active)
    assert all(item.acceptedMouseButtons() == Qt.NoButton for item in active)
    widget.active_search_rects = []
    widget._draw_overlays()
    assert len(widget.overlays) == 2 and not active_items(widget.overlays)
