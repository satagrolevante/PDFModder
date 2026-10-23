"""Retain the latest view intent while the serial PDF worker renders pages."""
from math import isclose

from PySide6.QtCore import QSignalBlocker, QTimer


class NavigationUiV310Mixin:
    def _create_ui(self):
        super()._create_ui()
        self._ensure_navigation_v310()
        self.operation_finished.connect(lambda *_: self._schedule_navigation_v310())
        self.error_raised.connect(lambda *_: self._schedule_navigation_v310())
        self.document_tabs_v200.tabBarClicked.connect(self._navigation_tab_clicked_v310)

    def _ensure_navigation_v310(self):
        if hasattr(self, '_navigation_timer_v310'):
            return
        self._navigation_intent_v310 = None
        self._navigation_fit_v310 = None
        self._navigation_timer_v310 = QTimer(self)
        self._navigation_timer_v310.setSingleShot(True)
        self._navigation_timer_v310.setInterval(40)
        self._navigation_timer_v310.timeout.connect(self._drain_navigation_v310)

    def _navigation_key_v310(self):
        return (self._active_session_v200, self.state.get('document_revision'), self.application_mode)

    def _navigation_pending_v310(self):
        return bool(getattr(self, '_navigation_intent_v310', None)
                    or getattr(self, '_navigation_fit_v310', None))

    def _schedule_navigation_v310(self):
        self._ensure_navigation_v310()
        if not self.busy and self._navigation_intent_v310 is None:
            # A failed page render has no callback to complete a deferred fit.
            # Do not leave unrelated commands waiting for an image that failed.
            self._navigation_fit_v310 = None
        if self._navigation_intent_v310 and not self._closed:
            self._navigation_timer_v310.start(0)

    def _view_intent_v310(self):
        self._ensure_navigation_v310()
        intent = self._navigation_intent_v310
        if intent is None or intent['key'] != self._navigation_key_v310():
            intent = {'key': self._navigation_key_v310(), 'tab': None, 'fit': None}
            self._navigation_intent_v310 = intent
        return intent

    def _queue_view_v310(self):
        return bool(not self._ui_mutation_locked_v310()
                    and ((self.busy and self._render_busy_v310())
                         or getattr(self, '_navigation_intent_v310', None) is not None))

    def _select_navigation_row_v310(self):
        with QSignalBlocker(self.pages):
            self.pages.setCurrentRow(self.page_number)

    def go_page(self, index):
        if not self.state or not 0 <= index < self.state.get('page_count', 0):
            return
        if self._ui_mutation_locked_v310():
            return
        # The continuous reader already replaces its viewport queue with the
        # newest position, even while an older page is rendering.
        if self.application_mode == 'reading':
            return super().go_page(index)
        if self._queue_view_v310():
            intent = self._view_intent_v310()
            intent['tab'] = None
            self.page_number = index
            self._restore_ids = self._restore_regions = None
            self._navigation_fit_v310 = None
            if hasattr(self, '_search_navigation_v306'):
                self._search_navigation_v306 = None
            self._select_navigation_row_v310()
            self._schedule_navigation_v310()
            self._refresh_actions()
            return True
        return super().go_page(index)

    def set_zoom(self, value):
        if not value or self._ui_mutation_locked_v310():
            return
        if self.application_mode == 'reading':
            return super().set_zoom(value)
        if self._queue_view_v310():
            intent = self._view_intent_v310()
            intent.update(tab=None, fit=None)
            self._navigation_fit_v310 = None
            self._fit_width_session_v308 = None
            # Repeated +/- presses must compound from the requested zoom,
            # rather than repeatedly starting from the last displayed image.
            self.zoom = max(.1, min(float(value), 4.))
            self._sync_zoom_control()
            self._schedule_navigation_v310()
            self._refresh_actions()
            return True
        return super().set_zoom(value)

    def fit_page(self, width_only=False):
        if self._ui_mutation_locked_v310():
            return
        if self.application_mode != 'reading' and self._queue_view_v310():
            intent = self._view_intent_v310()
            intent.update(tab=None, fit=bool(width_only))
            self._schedule_navigation_v310()
            return True
        return super().fit_page(width_only)

    def _switch_tab_v200(self, index):
        if index < 0 or index >= self.document_tabs_v200.count():
            return
        if self._queue_view_v310():
            sid = self.document_tabs_v200.tabData(index)
            if sid == self._active_session_v200:
                self._navigation_tab_clicked_v310(index)
                return
            intent = self._view_intent_v310()
            intent.update(tab=sid, fit=None)
            self._navigation_fit_v310 = None
            # Keep the tab header consistent with the still displayed PDF.
            with QSignalBlocker(self.document_tabs_v200):
                for active in range(self.document_tabs_v200.count()):
                    if self.document_tabs_v200.tabData(active) == self._active_session_v200:
                        self.document_tabs_v200.setCurrentIndex(active)
                        break
            self._schedule_navigation_v310()
            return True
        return super()._switch_tab_v200(index)

    def _navigation_tab_clicked_v310(self, index):
        intent = getattr(self, '_navigation_intent_v310', None)
        if (intent is not None and intent.get('tab') is not None
                and self.document_tabs_v200.tabData(index) == self._active_session_v200):
            # Clicking the already highlighted active tab emits tabBarClicked,
            # but no currentChanged; it still cancels an earlier queued switch.
            intent['tab'] = None
            self._schedule_navigation_v310()

    def load_page(self):
        if self.application_mode != 'reading' and self._queue_view_v310():
            self._view_intent_v310()
            self._schedule_navigation_v310()
            return True
        return super().load_page()

    def _drain_navigation_v310(self):
        self._ensure_navigation_v310()
        intent = self._navigation_intent_v310
        if intent is None:
            return False
        if self._closed or intent['key'] != self._navigation_key_v310():
            self._navigation_intent_v310 = None
            self._navigation_fit_v310 = None
            return False
        if self.busy or self._ui_mutation_locked_v310():
            self._navigation_timer_v310.start()
            return True
        self._navigation_intent_v310 = None
        if intent['tab'] is not None:
            for index in range(self.document_tabs_v200.count()):
                if self.document_tabs_v200.tabData(index) == intent['tab']:
                    with QSignalBlocker(self.document_tabs_v200):
                        self.document_tabs_v200.setCurrentIndex(index)
                    super()._switch_tab_v200(index)
                    return True
            return False
        self._select_navigation_row_v310()
        self.canvas.search_rects = [rect for match in self._search_matches
                                    if match['page'] == self.page_number
                                    for rect in (match.get('rects') or [match['rect']])]
        fit = intent['fit']
        if fit is not None:
            self._navigation_fit_v310 = (self._navigation_key_v310(), self.page_number, fit)
        super().load_page()
        return True

    def _loaded_page(self, result):
        self._ensure_navigation_v310()
        state = result.get('state', {})
        intent = self._navigation_intent_v310
        stale = (result.get('number', result['model'].number) != self.page_number
                 or not isclose(float(result['zoom']), self.zoom, abs_tol=1e-8)
                 or state.get('session_id', self._active_session_v200) != self._active_session_v200
                 or (intent is not None and intent.get('tab') is not None))
        if stale:
            self._schedule_navigation_v310()
            return
        # A render can already satisfy the final requested page and zoom.
        # Apply it once instead of scheduling that identical work again.
        if intent is not None and intent['key'] == self._navigation_key_v310():
            if intent['fit'] is not None:
                self._navigation_fit_v310 = (intent['key'], self.page_number, intent['fit'])
            self._navigation_intent_v310 = None
            self._navigation_timer_v310.stop()
        super()._loaded_page(result)
        fit, self._navigation_fit_v310 = self._navigation_fit_v310, None
        if fit is not None and fit[:2] == (self._navigation_key_v310(), self.page_number):
            self.fit_page(fit[2])

    def _pump_reader_v180(self):
        if self._navigation_intent_v310 is not None and self._drain_navigation_v310():
            return
        return super()._pump_reader_v180()

    def _load_visible_thumbnail(self):
        if self._navigation_intent_v310 is not None and self._drain_navigation_v310():
            return
        return super()._load_visible_thumbnail()

    def _reset_view_v200(self):
        self._ensure_navigation_v310()
        self._navigation_intent_v310 = None
        self._navigation_fit_v310 = None
        self._navigation_timer_v310.stop()
        return super()._reset_view_v200()
