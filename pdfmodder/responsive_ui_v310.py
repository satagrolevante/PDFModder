"""Keep read-only background work separate from exclusive document operations."""
from collections import deque

from PySide6.QtCore import QSignalBlocker, QTimer

from .action_state_v310 import set_ui_enabled_v310


class ResponsiveUiV310Mixin:
    def _create_ui(self):
        self._read_intents_v310 = deque()
        self._read_history_revision_v310 = None
        self._read_intent_timer_v310 = QTimer(self)
        self._read_intent_timer_v310.setSingleShot(True)
        self._read_intent_timer_v310.setInterval(40)
        self._read_intent_timer_v310.timeout.connect(self._drain_read_intents_v310)
        super()._create_ui()
        self.operation_finished.connect(self._read_operation_finished_v310)
        self.error_raised.connect(self._read_operation_failed_v310)

    def _render_busy_v310(self):
        # The worker remains serial and busy. Only the presentation of safe
        # commands changes; no mutation is submitted concurrently with a read.
        return bool(self.busy and self._command in
                    ('page', 'reading_info', 'search', 'reading_copy_range'))

    def _ui_mutation_locked_v310(self):
        return bool(self._closed or (self.busy and not self._render_busy_v310())
                    or self.state.get('preview')
                    or self.canvas.editor.isVisible()
                    or getattr(self, '_rich_active', False)
                    or getattr(self, '_rich_loading', False)
                    or getattr(self, '_rich_accept_pending', False)
                    or getattr(self, '_save_transaction_v300', None)
                    or getattr(self, '_close_waiting_v300', False)
                    or getattr(self, '_mode_preparing_v171', False)
                    or getattr(self, '_cell_draw_v200', False)
                    or getattr(self, '_signature_placement_dialog', None)
                    or getattr(self, '_placement', None)
                    or getattr(self, '_office_conversion_v305', None)
                    or getattr(self, '_modal_depth_v200', 0))

    def _finalize_action_states_v310(self):
        if (not self.state or not hasattr(self, 'save_all_action_v300')
                or self._ui_mutation_locked_v310()):
            return

        def enabled(name, value=True):
            target = getattr(self, name, None)
            if target is not None:
                set_ui_enabled_v310(self, target, bool(value))

        for name in ('open_action', 'pages', 'document_tabs_v200', 'zoom_box',
                     'fit_page_action', 'fit_width_action', 'print_action_v200',
                     'tools_action', 'reading_action', 'update_action_v170',
                     'document_properties_action', 'recovery_action_v200',
                     'recent_files_v170', 'close_document_action_v308'):
            enabled(name)
        enabled('zoom_out_action', self.zoom > .100001)
        enabled('zoom_in_action', self.zoom < 3.999999)
        search = self._search_permitted_v306() if hasattr(self, 'search_panel_v306') else False
        for name in ('search_action', 'search_box', 'search_panel_v306'):
            enabled(name, search)
        for name in ('search_next_action_v306', 'search_previous_action_v306'):
            enabled(name, search and bool(self.search_box.text().strip()))
        self.canvas.page_navigation_enabled = True
        prepared = self.state.get('editing_prepared', self.application_mode == 'editing')
        permitted = (not self.state.get('issues') or self.state.get('metadata_only_save')
                     or self.state.get('special_only_save'))
        save = bool((prepared and permitted) or self._clean_reading_copy_v300())
        for name in ('save_action', 'save_as_action_v300', 'share_action_v308'):
            enabled(name, save)
        enabled('save_all_action_v300', bool(self._session_paths_v200))
        original = self.compare_action.isChecked()
        origins = self.state.get('original_pages', [])
        enabled('compare_action', not origins or origins[self.page_number] is not None)
        editing = self.application_mode == 'editing'
        enabled('undo_action', editing and self.state.get('undo'))
        enabled('redo_action', editing and self.state.get('redo'))
        enabled('sign_action', editing and not self.state.get('issues') and not original)
        enabled('document_security_action', editing and not original)

        # Global document commands can wait for a read. A page-specific editor
        # must still wait for the correct model, page and zoom to be displayed.
        pending = getattr(self, '_navigation_pending_v310', lambda: False)()
        model = getattr(self.canvas, 'model', None)
        current = bool(model and model.number == self.page_number
                       and abs(self.canvas.zoom-self.zoom) < 1e-8)
        if editing and (pending or not current):
            self.canvas.read_only = True
            self.canvas.allow_background_edit = False
            for name in ('edit_content_action', 'format_action', 'add_text_action',
                         'add_image_action', 'image_mode_action', 'objects_action',
                         'native_objects_action', 'copy_format_action', 'paste_format_action',
                         'property_box', 'interaction_box', 'font_button',
                         'font_inspector_action_v308', 'cell_action_v200'):
                enabled(name, False)

    def _run_after_read_v310(self, name, callback, *args, **kwargs):
        if self._render_busy_v310() and not self._ui_mutation_locked_v310():
            entry = (name, self._active_session_v200,
                     self.state.get('document_revision'), callback, args, kwargs)
            # Repeated clicks on the same dialog or save action need one
            # response. Undo/redo retain every requested history step.
            if name not in ('undo', 'redo'):
                self._read_intents_v310 = deque(item for item in self._read_intents_v310
                                                if item[:3] != entry[:3])
            self._read_intents_v310.append(entry)
            self._schedule_read_intents_v310()
            return True
        return callback(*args, **kwargs)

    def _schedule_read_intents_v310(self):
        if getattr(self, '_read_intents_v310', None) and not self._closed:
            self._read_intent_timer_v310.start()

    def _read_operation_finished_v310(self, command, result):
        previous = self._read_history_revision_v310
        if previous is not None and command in ('undo', 'redo'):
            self._read_history_revision_v310 = None
            session, revision = previous
            state = result.get('state', {})
            if state.get('session_id') == session:
                current = state.get('document_revision')
                # Commands explicitly ordered after this undo/redo follow its
                # new revision. An unrelated document change still invalidates
                # a pending command rather than applying it to different data.
                self._read_intents_v310 = deque(
                    (name, sid, current if (sid, old) == previous else old, callback, args, kwargs)
                    for name, sid, old, callback, args, kwargs in self._read_intents_v310)
        self._schedule_read_intents_v310()

    def _read_operation_failed_v310(self, _message):
        self._read_history_revision_v310 = None
        self._schedule_read_intents_v310()

    def _drain_read_intents_v310(self):
        if self._closed:
            self._read_intents_v310.clear()
            return
        if not self._read_intents_v310:
            return
        if self.busy or self._ui_mutation_locked_v310():
            self._schedule_read_intents_v310()
            return
        if self._navigation_pending_v310():
            self._schedule_navigation_v310()
            self._schedule_read_intents_v310()
            return
        name, session, revision, callback, args, kwargs = self._read_intents_v310.popleft()
        if session == self._active_session_v200 and revision == self.state.get('document_revision'):
            if name in ('undo', 'redo'):
                self._read_history_revision_v310 = (session, revision)
            callback(*args, **kwargs)
        else:
            self._notice('El documento cambió. Vuelve a solicitar la operación pendiente.')
        self._schedule_read_intents_v310()

    def _hold_prefetch_for_intents_v310(self):
        if getattr(self, '_read_intents_v310', None):
            if self._navigation_pending_v310():
                self._schedule_navigation_v310()
            self._schedule_read_intents_v310()
            return True
        return False

    def _pump_reader_v180(self):
        if not self._hold_prefetch_for_intents_v310():
            return super()._pump_reader_v180()

    def _load_visible_thumbnail(self):
        if not self._hold_prefetch_for_intents_v310():
            return super()._load_visible_thumbnail()

    def choose_open(self):
        return self._run_after_read_v310('open', super().choose_open)

    def open_document(self, *args, **kwargs):
        return self._run_after_read_v310('open_path', super().open_document, *args, **kwargs)

    def _open_recent_v170(self, *args):
        return self._run_after_read_v310('recent', super()._open_recent_v170, *args)

    def save_document_v300(self):
        return self._run_after_read_v310('save', super().save_document_v300)

    def choose_save(self):
        return self._run_after_read_v310('save_as_dialog', super().choose_save)

    def save_as(self, *args, **kwargs):
        return self._run_after_read_v310('save_as', super().save_as, *args, **kwargs)

    def save_all_v300(self, *args, **kwargs):
        return self._run_after_read_v310('save_all', super().save_all_v300, *args, **kwargs)

    def history(self, command):
        return self._run_after_read_v310(command, super().history, command)

    def choose_print_v200(self):
        return self._run_after_read_v310('print', super().choose_print_v200)

    def choose_sign_document(self):
        return self._run_after_read_v310('sign', super().choose_sign_document)

    def choose_document_properties_v170(self):
        return self._run_after_read_v310('properties', super().choose_document_properties_v170)

    def choose_document_security_v170(self):
        return self._run_after_read_v310('security', super().choose_document_security_v170)

    def choose_share_v308(self):
        return self._run_after_read_v310('share', super().choose_share_v308)

    def show_updates_v170(self, **kwargs):
        return self._run_after_read_v310('updates', super().show_updates_v170, **kwargs)

    def show_recovery_v200(self):
        return self._run_after_read_v310('recovery', super().show_recovery_v200)

    def _close_tab_v200(self, index):
        if not 0 <= index < self.document_tabs_v200.count():
            return False
        session = self.document_tabs_v200.tabData(index)
        close = super()._close_tab_v200
        def close_same_tab():
            for current in range(self.document_tabs_v200.count()):
                if self.document_tabs_v200.tabData(current) == session:
                    return close(current)
            return False
        return self._run_after_read_v310('close_'+str(session), close_same_tab)

    def toggle_original(self, checked):
        if self._render_busy_v310() and not self._ui_mutation_locked_v310():
            self._reader_generation_v180 += 1
            self._reader_key_v180 = None
        return self._run_after_read_v310('original', super().toggle_original, checked)

    def _tools_mode_v171(self, editing):
        if self._render_busy_v310() and not self._ui_mutation_locked_v310():
            with QSignalBlocker(self.tools_action):
                self.tools_action.setChecked(self.application_mode == 'editing')
        return self._run_after_read_v310('mode', super()._tools_mode_v171, editing)
