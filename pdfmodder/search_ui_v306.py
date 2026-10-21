"""Read-only search navigation, bound to the current tab, PDF revision and view."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget, QApplication

from .draft_control_v305 import DraftControl
from .model import union
from .search_panel_v306 import SearchPanel


class SearchUiV306Mixin:
    def _create_ui(self):
        super()._create_ui()
        self._search_generation_v306 = 0
        self._search_result_key_v306 = None
        self._search_document_v306 = None
        self._search_pending_v306 = None
        self._search_running_v306 = None
        self._search_navigation_v306 = None
        self._search_canvas_page_v306 = None
        self._search_syncing_v306 = False
        self._search_control_v306 = DraftControl()
        self._search_timer_v306 = QTimer(self)
        self._search_timer_v306.setInterval(35)
        self._search_timer_v306.timeout.connect(self._pump_search_v306)
        self.search_panel_v306 = SearchPanel(self)
        self.search_dock_v306 = QDockWidget('Buscar en el documento', self)
        self.search_dock_v306.setObjectName('searchResultsDock')
        self.search_dock_v306.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.search_dock_v306.setWidget(self.search_panel_v306)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.search_dock_v306)
        self.search_dock_v306.hide()
        self.search_panel_v306.find_requested.connect(self._request_search_v306)
        self.search_panel_v306.criteria_changed.connect(self._panel_search_changed_v306)
        self.search_panel_v306.match_requested.connect(self._select_search_match_v306)
        self.search_panel_v306.next_requested.connect(self._next_match)
        self.search_panel_v306.previous_requested.connect(self._previous_match_v306)
        self.search_panel_v306.close_requested.connect(self.search_dock_v306.hide)
        self.search_dock_v306.visibilityChanged.connect(self._search_visibility_v306)
        self.search_box.textChanged.connect(self._toolbar_search_changed_v306)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMaxLength(4096)
        self.search_action.setText('Buscar')
        self.search_action.setShortcut(QKeySequence())
        self.search_action.setToolTip('Abrir resultados de búsqueda · Ctrl+F')
        self.search_next_action_v306 = QAction('Siguiente resultado', self)
        self.search_next_action_v306.setShortcut(QKeySequence('F3'))
        self.search_next_action_v306.triggered.connect(self._next_match)
        self.addAction(self.search_next_action_v306)
        self.search_previous_action_v306 = QAction('Resultado anterior', self)
        self.search_previous_action_v306.setShortcut(QKeySequence('Shift+F3'))
        self.search_previous_action_v306.triggered.connect(self._previous_match_v306)
        self.addAction(self.search_previous_action_v306)
        self.error_raised.connect(self._search_failed_v306)
        self.page_ready.connect(self._sync_search_visuals_v306)

    def _search_view_key_v306(self):
        if not self.state:
            return None
        return (self.state.get('session_id', self._active_session_v200),
                self.state.get('document_revision'), self.compare_action.isChecked())

    def _search_permitted_v306(self):
        writing = (self.canvas.editor.isVisible() or getattr(self, '_rich_active', False)
                   or getattr(self, '_rich_loading', False))
        return bool(self.state and not self._closed and not writing and not self.state.get('preview')
                    and not getattr(self, '_save_transaction_v300', None)
                    and not getattr(self, '_cell_draw_v200', False)
                    and not getattr(self, '_signature_placement_dialog', None)
                    and not getattr(self, '_mode_preparing_v171', False))

    def focus_search_v306(self):
        self.search_dock_v306.show()
        self.search_dock_v306.raise_()
        self.search_panel_v306.query.setFocus()
        self.search_panel_v306.query.selectAll()

    def _toolbar_search_changed_v306(self, text):
        if self._search_syncing_v306:
            return
        self._search_syncing_v306 = True
        try:
            self.search_panel_v306.set_query(text)
        finally:
            self._search_syncing_v306 = False
        self._clear_search_v306()

    def _panel_search_changed_v306(self):
        if self._search_syncing_v306:
            return
        self._search_syncing_v306 = True
        try:
            self.search_box.setText(self.search_panel_v306.query_text())
        finally:
            self._search_syncing_v306 = False
        self._clear_search_v306()

    def _clear_search_v306(self, message='Escribe un texto y pulsa Enter o Buscar.'):
        if not hasattr(self, '_search_control_v306'):
            return
        self._search_generation_v306 += 1
        self._search_control_v306.invalidate()
        self._search_pending_v306 = self._search_navigation_v306 = None
        self._search_result_key_v306 = self._last_search = None
        self._search_matches = []
        self._search_index = -1
        self._search_timer_v306.stop()
        self.search_panel_v306.set_busy(False)
        self.search_panel_v306.clear_results(message)
        self.reader.set_search_matches([])
        self.canvas.search_rects = self.canvas.active_search_rects = []
        self.canvas._draw_overlays()

    def _search_visibility_v306(self, visible):
        if not visible:
            self._clear_search_v306()

    def search(self):
        self.search_dock_v306.show()
        return self._request_search_v306(self.search_box.text(), **self.search_panel_v306.options())

    def _request_search_v306(self, text, case_sensitive=False, whole_word=False):
        if not self._search_permitted_v306():
            return False
        self._search_syncing_v306 = True
        try:
            self.search_box.setText(text)
            self.search_panel_v306.set_query(text)
            self.search_panel_v306.case_box.setChecked(bool(case_sensitive))
            self.search_panel_v306.whole_box.setChecked(bool(whole_word))
        finally:
            self._search_syncing_v306 = False
        self.search_dock_v306.show()
        if not text.strip():
            self._clear_search_v306()
            self.search_panel_v306.query.setFocus()
            return False
        document = self._search_view_key_v306()
        key = (document, text, bool(case_sensitive), bool(whole_word))
        if key == self._search_result_key_v306:
            if self._search_matches:
                self._next_match()
            return True
        self._clear_search_v306()
        self._search_document_v306 = document
        self._search_pending_v306 = (key, self._search_generation_v306)
        self.search_panel_v306.set_busy(True)
        self._search_timer_v306.start()
        self._pump_search_v306()
        return True

    def _discard_search_reply_v306(self):
        job = self._search_running_v306
        obsolete = not job or (job[1] != self._search_generation_v306
                              or job[0][0] != self._search_view_key_v306() or self._closed)
        if obsolete:
            self._search_running_v306 = None
            if self._search_pending_v306:
                self._search_timer_v306.start()
        return obsolete

    def _pump_search_v306(self):
        if self._closed:
            self._search_timer_v306.stop()
            return False
        if self._search_pending_v306:
            if not self._search_permitted_v306():
                self._clear_search_v306()
                return False
            if self.busy or QApplication.activeModalWidget() is not None:
                return True
            key, generation = self._search_pending_v306
            if key[0] != self._search_view_key_v306():
                self._clear_search_v306()
                return False
            job = (key, generation)
            self._search_running_v306 = job
            payload = {'text': key[1], 'case_sensitive': key[2], 'whole_word': key[3],
                       'original': key[0][2], '_search_control_v306': self._search_control_v306.ticket()}

            def found(result):
                self._search_running_v306 = None
                if generation != self._search_generation_v306 or key[0] != self._search_view_key_v306():
                    return
                self.search_panel_v306.set_busy(False)
                if result.get('search_cancelled_v306'):
                    self.search_panel_v306.clear_results('Búsqueda cancelada.')
                    return
                self._search_result_key_v306 = key
                self._last_search = key[1]
                self._search_matches = result['matches']
                self._search_index = -1
                self.search_panel_v306.set_matches(self._search_matches)
                self.reader.set_search_matches(self._search_matches)
                if self._search_matches:
                    self._select_search_match_v306(0)
                else:
                    self._notice('No hay coincidencias en el documento para este texto y estas opciones.')
                    self._sync_search_visuals_v306()

            if self._submit('search', payload, found):
                self._search_pending_v306 = None
            else:
                self._search_running_v306 = None
            return True
        if self._search_navigation_v306 is not None:
            if not self._search_permitted_v306():
                self._search_navigation_v306 = None
                self._search_timer_v306.stop()
                return False
            if self.busy:
                return True
            # The continuous reader must finish its geometry before seeking.
            if self.application_mode == 'reading' and self._reader_key_v180 != self._search_view_key_v306()[1:]:
                return False
            index, self._search_navigation_v306 = self._search_navigation_v306, None
            self._select_search_match_v306(index)
            return True
        self._search_timer_v306.stop()
        return False

    def _next_match(self):
        if not self._search_matches:
            return self.search()
        return self._select_search_match_v306((self._search_index + 1) % len(self._search_matches))

    def _previous_match_v306(self):
        if not self._search_matches:
            return self.search()
        return self._select_search_match_v306((self._search_index - 1) % len(self._search_matches))

    def _select_search_match_v306(self, index):
        if (not 0 <= index < len(self._search_matches) or not self._search_permitted_v306()
                or self._search_result_key_v306 is None):
            return False
        self._search_index = index
        self.search_panel_v306.set_current_index(index)
        match = self._search_matches[index]
        self._notice(f"Coincidencia {index + 1} de {len(self._search_matches)} · Página {match['page'] + 1}")
        if self.application_mode == 'reading':
            if self._reader_key_v180 != self._search_view_key_v306()[1:]:
                self._search_navigation_v306 = index
                self._search_timer_v306.start()
                return True
            self.page_number = match['page']
            self._sync_search_visuals_v306()
            self.reader.go_page(self.page_number)
            self.reader.reveal_rect(self.page_number, match.get('rects', [match['rect']])[0])
            return True
        if self.busy:
            self._search_navigation_v306 = index
            self._search_timer_v306.start()
            return True
        self.page_number = match['page']
        blocked = self.pages.blockSignals(True)
        self.pages.setCurrentRow(self.page_number)
        self.pages.blockSignals(blocked)
        self._sync_search_visuals_v306()
        key = (self._search_view_key_v306(), self.page_number, self.zoom)
        if key == self._search_canvas_page_v306:
            self.canvas.ensureVisible(self.canvas.scene_rect(union(match.get('rects') or [match['rect']])), 35, 55)
        else:
            self._search_navigation_v306 = index
            self._search_timer_v306.start()
            self.load_page()
        return True

    def _sync_search_visuals_v306(self):
        if not hasattr(self, 'search_panel_v306'):
            return
        if self._search_matches and not self.reader._search_matches:
            self.reader.set_search_matches(self._search_matches)
        self.reader.set_active_search_match(self._search_index)
        self.canvas.search_rects = [rect for match in self._search_matches
                                    if match['page'] == self.page_number
                                    for rect in (match.get('rects') or [match['rect']])]
        match = (self._search_matches[self._search_index]
                 if 0 <= self._search_index < len(self._search_matches) else None)
        self.canvas.active_search_rects = (match.get('rects') or [match['rect']]) if match and match['page'] == self.page_number else []
        self.canvas._draw_overlays()

    def _search_failed_v306(self, message):
        if self._command == 'search':
            self._search_running_v306 = None
            self.search_panel_v306.set_busy(False)
            self.search_panel_v306.clear_results(str(message))

    def _refresh_actions(self):
        super()._refresh_actions()
        if not hasattr(self, 'search_panel_v306'):
            return
        view = self._search_view_key_v306()
        if view != self._search_document_v306:
            self._clear_search_v306('El documento cambió. Pulsa Buscar para actualizar los resultados.' if view else 'Abre un PDF para buscar.')
            self._search_document_v306 = view
        allowed = self._search_permitted_v306()
        background = self._command in ('page', 'reading_info', 'search')
        interactive = allowed and (not self.busy or background)
        self.search_box.setEnabled(interactive)
        self.search_action.setEnabled(interactive)
        self.search_panel_v306.setEnabled(interactive)
        self.search_next_action_v306.setEnabled(interactive and bool(self.search_box.text().strip()))
        self.search_previous_action_v306.setEnabled(interactive and bool(self.search_box.text().strip()))
        self.search_panel_v306.set_busy(bool(self._search_running_v306 or self._search_pending_v306))

    def _loaded_page(self, result):
        super()._loaded_page(result)
        self._search_canvas_page_v306 = (self._search_view_key_v306(), self.page_number, self.zoom)

    def _reset_view_v200(self):
        self._clear_search_v306()
        self._search_canvas_page_v306 = None
        return super()._reset_view_v200()

    def _pump_reader_v180(self):
        if not hasattr(self, '_search_timer_v306') or not self._pump_search_v306():
            return super()._pump_reader_v180()

    def _load_visible_thumbnail(self):
        if self._search_pending_v306 or self._search_navigation_v306 is not None:
            return
        return super()._load_visible_thumbnail()

    def cancel(self):
        if (hasattr(self, 'search_dock_v306') and self.search_dock_v306.isVisible()
                and (self.search_panel_v306.isAncestorOf(QApplication.focusWidget())
                     or self.search_box.hasFocus()) and self._search_permitted_v306()):
            self.search_dock_v306.hide()
            (self.reader if self.application_mode == 'reading' else self.canvas).setFocus()
            return True
        return super().cancel()

    def closeEvent(self, event):
        if (hasattr(self, '_search_control_v306')
                and (self._search_running_v306 or self._search_pending_v306)):
            self._clear_search_v306()
        super().closeEvent(event)
        if self._closed:
            self._search_timer_v306.stop()
            self._search_control_v306.close()
