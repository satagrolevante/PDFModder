"""Prominent page navigation and a pan tool which never moves PDF objects."""
from PySide6.QtCore import QEvent, QObject, Qt, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractSpinBox, QSpinBox, QToolButton

from .action_state_v310 import set_ui_enabled_v310
from .ui_icons_v170 import icon_v170


class _HandPanV311(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.drag = None

    def cancel(self):
        self.drag = None
        self.update_cursors()

    def update_cursors(self):
        for view in (self.owner.canvas, self.owner.reader):
            if self.owner.hand_action_v311.isChecked():
                view.viewport().setCursor(Qt.ClosedHandCursor if self.drag else Qt.OpenHandCursor)
            else:
                view.viewport().unsetCursor()
            view.verticalScrollBar().setCursor(Qt.ArrowCursor)
            view.horizontalScrollBar().setCursor(Qt.ArrowCursor)

    def eventFilter(self, watched, event):
        if not self.owner.hand_action_v311.isChecked():
            return False
        view = next((view for view in (self.owner.canvas, self.owner.reader)
                     if watched is view.viewport()), None)
        if view is None:
            return False
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if not self.owner._pan_allowed_v311():
                self.owner._set_hand_v311(False)
                return True
            view.setFocus(Qt.MouseFocusReason)
            self.drag = (view, event.position().toPoint(),
                         view.horizontalScrollBar().value(), view.verticalScrollBar().value())
            self.update_cursors()
            event.accept()
            return True
        if kind == QEvent.MouseMove:
            if self.drag and self.drag[0] is view:
                _, origin, x, y = self.drag
                delta = event.position().toPoint() - origin
                view.horizontalScrollBar().setValue(x - delta.x())
                view.verticalScrollBar().setValue(y - delta.y())
            event.accept()
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.cancel()
            event.accept()
            return True
        if kind in (QEvent.MouseButtonDblClick, QEvent.ContextMenu):
            event.accept()
            return True
        if kind in (QEvent.Hide, QEvent.WindowDeactivate):
            self.cancel()
        return False


class ToolbarUiV311Mixin:
    def _create_ui(self):
        super()._create_ui()
        toolbar = self.toolbar
        for action in (self.save_as_action_v300, self.save_all_action_v300,
                       self.document_properties_action, self.document_security_action,
                       self.reading_action):
            toolbar.removeAction(action)
        for action in list(toolbar.actions()):
            if toolbar.widgetForAction(action) is self.mode_label_v171:
                toolbar.removeAction(action)
        self.previous_page_action_v311 = QAction('Página anterior', self)
        self.previous_page_action_v311.setIcon(icon_v170('previous_page'))
        self.next_page_action_v311 = QAction('Página siguiente', self)
        self.next_page_action_v311.setIcon(icon_v170('next_page'))
        self.previous_page_action_v311.triggered.connect(lambda: self.go_page(self.page_number-1))
        self.next_page_action_v311.triggered.connect(lambda: self.go_page(self.page_number+1))
        self.page_number_box_v311 = QSpinBox()
        self.page_number_box_v311.setObjectName('pageNumberV311')
        self.page_number_box_v311.setAccessibleName('Página actual y total de páginas')
        self.page_number_box_v311.setToolTip('Escribe una página y pulsa Intro para ir a ella')
        self.page_number_box_v311.setKeyboardTracking(False)
        self.page_number_box_v311.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.page_number_box_v311.setMinimumWidth(100)
        self.page_number_box_v311.setMaximumWidth(150)
        self.page_number_box_v311.editingFinished.connect(self._jump_from_toolbar_v311)
        self._page_document_v311 = None
        number_action = toolbar.addWidget(self.page_number_box_v311)
        self.hand_action_v311 = QAction(icon_v170('hand'), 'Mano', self)
        self.hand_action_v311.setObjectName('handPanV311')
        self.hand_action_v311.setToolTip('Desplazar la vista arrastrando, sin seleccionar ni mover contenido')
        self.hand_action_v311.setCheckable(True)
        self.hand_action_v311.toggled.connect(self._set_hand_v311)
        self._hand_filter_v311 = _HandPanV311(self)
        for view in (self.canvas, self.reader):
            view.viewport().installEventFilter(self._hand_filter_v311)
        self.view_menu_v308.addSeparator()
        for action in (self.previous_page_action_v311, self.next_page_action_v311, self.hand_action_v311):
            self.view_menu_v308.addAction(action)
        tools_widget_action = next(action for action in toolbar.actions()
                                   if toolbar.widgetForAction(action) is self.tools_toggle_button)
        selection = self.mode_actions_v170['select']
        selection.setToolTip('Seleccionar texto para copiar o editar; arrastra para ampliar la selección')
        priority = (self.open_action, self.save_action, self.previous_page_action_v311,
                    number_action, self.next_page_action_v311, tools_widget_action,
                    self.hand_action_v311, selection, self.highlight_action)
        for action in priority:
            toolbar.removeAction(action)
        anchor = toolbar.actions()[0] if toolbar.actions() else None
        for action in priority:
            toolbar.insertAction(anchor, action)
        for action in (self.hand_action_v311, selection, self.highlight_action):
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # Keep the exact visible label the user requested.
        self.highlight_action.setText('Resaltar cambios')
        self.reader.current_page_changed.connect(lambda *_: self._refresh_toolbar_v311())
        self.operation_finished.connect(lambda *_: self._refresh_toolbar_v311())
        self._refresh_toolbar_v311()

    def _pan_allowed_v311(self):
        return bool(self.state and not self._ui_mutation_locked_v310()
                    and not self.canvas.placement_mode and not self.canvas.zone_mode
                    and not self.canvas.signature_rectangle_mode)

    def _set_hand_v311(self, checked):
        if not hasattr(self, '_hand_filter_v311'):
            return
        checked = bool(checked and self._pan_allowed_v311())
        with QSignalBlocker(self.hand_action_v311):
            self.hand_action_v311.setChecked(checked)
        if checked:
            self.mode_group_v170.setExclusive(False)
            for action in self.mode_actions_v170.values():
                with QSignalBlocker(action):
                    action.setChecked(False)
            self.mode_group_v170.setExclusive(True)
        else:
            self._sync_modes_v170()
        self._hand_filter_v311.cancel()

    def _set_mode_v170(self, mode):
        if hasattr(self, 'hand_action_v311'):
            self._set_hand_v311(False)
        return super()._set_mode_v170(mode)

    def _set_mode_v171(self, mode):
        if hasattr(self, 'hand_action_v311'):
            self._set_hand_v311(False)
        result = super()._set_mode_v171(mode)
        self._refresh_toolbar_v311()
        return result

    def _refresh_actions(self):
        super()._refresh_actions()
        self._refresh_toolbar_v311()

    def _refresh_toolbar_v311(self):
        if not hasattr(self, 'hand_action_v311'):
            return
        count = int(self.state.get('page_count', 0))
        unlocked = bool(count and not self._ui_mutation_locked_v310())
        set_ui_enabled_v310(self, self.previous_page_action_v311, unlocked and self.page_number > 0)
        set_ui_enabled_v310(self, self.next_page_action_v311, unlocked and self.page_number < count-1)
        set_ui_enabled_v310(self, self.page_number_box_v311, unlocked)
        set_ui_enabled_v310(self, self.hand_action_v311, self._pan_allowed_v311())
        selection = self.mode_actions_v170['select']
        selection.setVisible(True)
        if self.application_mode == 'reading':
            set_ui_enabled_v310(self, selection, unlocked)
            if not self.hand_action_v311.isChecked():
                with QSignalBlocker(selection):
                    selection.setChecked(True)
        if self.hand_action_v311.isChecked() and not self._pan_allowed_v311():
            self._set_hand_v311(False)
        key = (self._active_session_v200, self.state.get('path'), count)
        box = self.page_number_box_v311
        if key != self._page_document_v311 or not (box.hasFocus() and box.lineEdit().isModified()):
            with QSignalBlocker(box):
                box.setRange(1 if count else 0, max(0, count))
                box.setSuffix(f' de {count}')
                box.setValue(self.page_number+1 if count else 0)
                box.lineEdit().setModified(False)
            self._page_document_v311 = key

    def _jump_from_toolbar_v311(self):
        if not self.state or self._ui_mutation_locked_v310():
            self._refresh_toolbar_v311()
            return
        number = self.page_number_box_v311.value()-1
        if number != self.page_number:
            self.go_page(number)
        self.page_number_box_v311.lineEdit().setModified(False)
        self._refresh_toolbar_v311()
