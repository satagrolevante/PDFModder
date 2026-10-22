"""Opening width is selected before the first render, without extra PDF work."""
import pytest
from PySide6.QtWidgets import QApplication

from pdfmodder.continuous_reader_v180 import ContinuousReader
from pdfmodder.view_zoom_ui_v308 import ViewZoomUiV308Mixin


class _SubmissionBase:
    def _submit(self, command, payload=None, callback=None):
        self.requests.append((command, payload, callback))
        return True

    def set_zoom(self, value):
        self.zoom = value


class _OpeningWindow(ViewZoomUiV308Mixin, _SubmissionBase):
    def __init__(self, reader):
        self.reader = reader
        self.state = {'session_id': 'first', 'path': 'first.pdf'}
        self.page_number = 0
        self.zoom = 1.25
        self.requests = []
        self.synced = []

    def _sync_zoom_control(self):
        self.synced.append(self.zoom)


@pytest.mark.parametrize('width,height,count', [(500., 720., 123), (900., 400., 1)])
def test_first_reader_layout_and_render_use_fitted_width(qtbot, width, height, count):
    reader = ContinuousReader()
    qtbot.addWidget(reader)
    reader.resize(800, 600)
    reader.show()
    QApplication.processEvents()
    window = _OpeningWindow(reader)
    geometry = {'page_count': count, 'default_geometry': {'width': width, 'height': height},
                'geometries': {0: {'width': width, 'height': height}}}
    rendered_zooms = []

    def opened(_):
        def metadata_ready(result):
            reader.reset_document(result, zoom=window.zoom)
            rendered_zooms.append(window.zoom)
        window._submit('reading_info', {'progressive': True, 'pages': [0]}, metadata_ready)

    window._submit('open', {'path': 'first.pdf'}, opened)
    window.requests[0][2]({'state': window.state})
    window.requests[1][2](geometry)
    QApplication.processEvents()
    assert [request[0] for request in window.requests] == ['open', 'reading_info']
    assert rendered_zooms == window.synced == [window.zoom]
    assert reader._rects[0].width() <= reader.viewport().width() - 2 * reader.MARGIN + 1
    assert reader.viewport().width() - 2 * reader.MARGIN - reader._rects[0].width() <= 2
    assert reader.horizontalScrollBar().maximum() == 0


def test_manual_zoom_and_tab_metadata_keep_the_chosen_zoom(qtbot):
    reader = ContinuousReader()
    qtbot.addWidget(reader)
    reader.resize(800, 600)
    reader.show()
    QApplication.processEvents()
    window = _OpeningWindow(reader)
    geometry = {'page_count': 123, 'default_geometry': {'width': 500., 'height': 720.}}
    window._submit('open')
    window.requests[-1][2]({'state': window.state})
    window._submit('reading_info')
    metadata_ready = window.requests[-1][2]
    window.set_zoom(.75)
    metadata_ready(geometry)
    assert window.zoom == .75 and window.synced == []
    # Reader metadata after switching/restoring a tab must not refit it.
    window._submit('reading_info')
    assert window.requests[-1][2] is None
    # A second successful open gets its own default, regardless of old zoom.
    window.state = {'session_id': 'second', 'path': 'second.pdf'}
    window._submit('open')
    window.requests[-1][2]({'state': window.state})
    window._submit('reading_info')
    window.requests[-1][2](geometry)
    assert window.zoom > .75 and window.synced == [window.zoom]
