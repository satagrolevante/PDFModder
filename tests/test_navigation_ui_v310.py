"""View intents are retained without dispatching work into an occupied worker."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMainWindow, QListWidget, QTabBar

from pdfmodder.navigation_ui_v310 import NavigationUiV310Mixin
from test_saving_v300 import saving_window  # noqa: F401 — shared real-worker fixture


class ViewBase:
    def go_page(self, index):
        self.page_number = index
        self.calls.append(('reading-page' if self.application_mode == 'reading' else 'page', index))
        if self.application_mode != 'reading':
            self.load_page()

    def set_zoom(self, value):
        self.zoom = float(value)
        self.calls.append(('reading-zoom' if self.application_mode == 'reading' else 'zoom', self.zoom))
        if self.application_mode != 'reading':
            self.load_page()

    def step_zoom_v160(self, direction):
        self.set_zoom(self.zoom * (1.25 if direction > 0 else .8))

    def fit_page(self, width_only=False):
        self.calls.append(('fit', self.model.number, width_only))
        self.set_zoom(2. if width_only else 1.5)

    def load_page(self):
        assert not self.busy, 'A view command must not be lost in the worker busy gate'
        self.submissions.append((self.page_number, self.zoom))
        self.busy = True

    def _loaded_page(self, result):
        self.model = result['model']
        self.canvas.model = self.model
        self.canvas.zoom = result['zoom']
        self.zoom = result['zoom']
        self.applied.append((self.model.number, self.zoom))

    def _switch_tab_v200(self, index):
        assert not self.busy
        self.calls.append(('tab', self.document_tabs_v200.tabData(index)))

    def _pump_reader_v180(self):
        self.calls.append(('prefetch',))

    def _load_visible_thumbnail(self):
        self.calls.append(('thumbnail',))

    def _reset_view_v200(self):
        pass


class Window(NavigationUiV310Mixin, ViewBase, QMainWindow):
    def __init__(self):
        super().__init__()
        self._closed = False
        self._active_session_v200 = 'first'
        self.state = {'page_count': 123, 'document_revision': 'revision'}
        self.application_mode = 'editing'
        self.page_number = 0
        self.zoom = 1.
        self.model = SimpleNamespace(number=0)
        self.canvas = SimpleNamespace(model=self.model, zoom=self.zoom, search_rects=[])
        self.pages = QListWidget(self)
        self.pages.addItems([str(number) for number in range(123)])
        self.document_tabs_v200 = QTabBar(self)
        for name in ('first', 'second', 'third'):
            index = self.document_tabs_v200.addTab(name)
            self.document_tabs_v200.setTabData(index, name)
        self.busy = True
        self.locked = False
        self._command = 'page'
        self.calls, self.submissions, self.applied = [], [], []
        self._search_matches = []
        self._search_navigation_v306 = None
        self._ensure_navigation_v310()

    def _render_busy_v310(self):
        return self.busy and self._command in ('page', 'reading_info', 'search', 'reading_copy_range')

    def _ui_mutation_locked_v310(self):
        return self.locked or (self.busy and not self._render_busy_v310())

    def _sync_zoom_control(self):
        self.shown_zoom = self.zoom

    def _refresh_actions(self):
        pass


@pytest.fixture
def window(qtbot):
    result = Window()
    qtbot.addWidget(result)
    yield result
    result._closed = True
    result._navigation_timer_v310.stop()


def loaded(window, number, zoom):
    window.busy = False
    window._loaded_page({'number': number, 'zoom': zoom,
                         'model': SimpleNamespace(number=number),
                         'state': {'session_id': 'first'}})


def test_failed_fit_render_does_not_leave_other_commands_waiting(window):
    window._navigation_fit_v310 = (window._navigation_key_v310(), 0, True)
    window.busy = False
    window._schedule_navigation_v310()
    assert not window._navigation_pending_v310()


def test_rapid_page_and_zoom_retain_only_final_view_and_ignore_old_render(window):
    window.go_page(15)
    window.go_page(35)
    window.step_zoom_v160(1)
    window.step_zoom_v160(1)
    assert window.page_number == 35 and window.zoom == 1.5625
    assert window.shown_zoom == 1.5625
    assert window.submissions == []
    loaded(window, 0, 1.)
    assert window.applied == [], 'An old page must not overwrite the requested view'
    assert window._drain_navigation_v310()
    assert window.submissions == [(35, 1.5625)]
    loaded(window, 35, 1.5625)
    assert window.applied == [(35, 1.5625)]
    assert not window._navigation_pending_v310()


def test_render_already_matching_final_request_is_not_submitted_twice(window):
    window.go_page(5)
    window.go_page(0)
    loaded(window, 0, 1.)
    assert window.applied == [(0, 1.)]
    assert not window._navigation_pending_v310()
    assert not window._drain_navigation_v310()
    assert window.submissions == []


def test_latest_tab_intent_precedes_prefetch_and_thumbnail_work(window):
    window._switch_tab_v200(1)
    window._switch_tab_v200(2)
    assert window.document_tabs_v200.currentIndex() == 0
    window.busy = False
    window._load_visible_thumbnail()
    assert window.calls == [('tab', 'third')]
    assert window.submissions == []


def test_returning_to_active_tab_cancels_a_pending_tab_without_losing_view_request(window):
    window.go_page(35)
    window._switch_tab_v200(1)
    window._navigation_tab_clicked_v310(0)
    loaded(window, 0, 1.)
    window._drain_navigation_v310()
    assert window.submissions == [(35, 1.)]
    assert not any(call[0] == 'tab' for call in window.calls)


def test_last_view_request_wins_in_idle_gap_before_pending_timer_drains(window):
    window._switch_tab_v200(1)
    window.busy = False
    window.go_page(12)
    assert not window.submissions
    window._drain_navigation_v310()
    assert window.submissions == [(12, 1.)]
    assert not any(call[0] == 'tab' for call in window.calls)


def test_fit_waits_for_the_actual_destination_page_geometry(window):
    window.go_page(12)
    window.fit_page(True)
    loaded(window, 0, 1.)
    window._drain_navigation_v310()
    assert window.submissions == [(12, 1.)]
    loaded(window, 12, 1.)
    assert ('fit', 12, True) in window.calls
    assert window.submissions[-1] == (12, 2.)


@pytest.mark.parametrize('change', ['revision', 'session'])
def test_pending_view_cannot_leak_to_another_revision_or_session(window, change):
    window.go_page(42)
    if change == 'revision':
        window.state['document_revision'] = 'changed'
    else:
        window._active_session_v200 = 'second'
    window.busy = False
    assert not window._drain_navigation_v310()
    assert not window._navigation_pending_v310()
    assert not window.submissions


def test_exclusive_document_work_and_drafts_do_not_accept_navigation(window):
    window._command = 'save'
    window.go_page(10)
    window.set_zoom(2.)
    window.fit_page(True)
    assert window.page_number == 0 and window.zoom == 1.
    assert not window._navigation_pending_v310()
    window._command = 'page'
    window.locked = True
    window.go_page(10)
    assert window.page_number == 0


def test_reading_preserves_its_existing_replacement_queue_during_rendering(window):
    window.application_mode = 'reading'
    window.go_page(40)
    window.set_zoom(1.5)
    assert window.calls == [('reading-page', 40), ('reading-zoom', 1.5)]
    assert not window._navigation_pending_v310()


def test_queued_zoom_preserves_selection_restoration(window):
    window._restore_ids = [2, 5]
    window._restore_regions = None
    window.set_zoom(1.5)
    loaded(window, 0, 1.)
    window._drain_navigation_v310()
    assert window._restore_ids == [2, 5]


def test_real_editing_navigation_and_zoom_apply_final_view_only(qtbot, saving_window, tmp_path):
    import pymupdf as fitz
    from test_saving_v300 import open_editing
    window = saving_window
    source = tmp_path / 'long.pdf'
    with fitz.open() as document:
        for number in range(123):
            page = document.new_page(width=400 + number % 2 * 100, height=600)
            page.insert_text((30, 50), f'Page {number+1}')
        document.save(source)
    original = source.read_bytes()
    open_editing(qtbot, window, source)
    applied = []
    window.page_ready.connect(lambda: applied.append((window.canvas.model.number, window.canvas.zoom)))
    window.go_page(50)
    assert window.busy
    window.go_page(75)
    window.set_zoom(1.5)
    window.step_zoom_v160(1)
    assert window.page_number == 75 and window.zoom == 1.875
    assert window.canvas.read_only
    qtbot.waitUntil(lambda: not window.busy and not window._navigation_pending_v310(), timeout=30000)
    assert window.canvas.model.number == 75
    assert window.canvas.zoom == window.zoom == 1.875
    assert applied == [(75, 1.875)]
    window.go_page(80)
    window.fit_page(True)
    qtbot.waitUntil(lambda: not window.busy and not window._navigation_pending_v310(), timeout=30000)
    assert window.canvas.model.number == 80
    expected = (window.canvas.viewport().width()-35)/window.canvas.model.width
    assert window.zoom == pytest.approx(expected)
    assert source.read_bytes() == original
