"""Collapse the pages/recent sidebar while keeping a visible restore control."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget


class SidebarUiV311Mixin:
    def _create_ui(self):
        super()._create_ui()
        tabs = self.workspace_tabs_v170
        splitter = self.document_splitter
        index = splitter.indexOf(tabs)
        self._sidebar_index_v311 = index
        self._sidebar_expanded_width_v311 = 220
        self._sidebar_expanded_v311 = True
        self.sidebar_host_v311 = QWidget()
        self.sidebar_host_v311.setObjectName('sidebarHostV311')
        self.sidebar_host_v311.setMinimumWidth(220)
        self.sidebar_host_v311.setMaximumWidth(235)
        layout = QHBoxLayout(self.sidebar_host_v311)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sizes = splitter.sizes()
        splitter.replaceWidget(index, self.sidebar_host_v311)
        splitter.setCollapsible(index, False)
        layout.addWidget(tabs)
        self.sidebar_collapse_button_v311 = QToolButton(tabs)
        self.sidebar_collapse_button_v311.setObjectName('collapseSidebarV311')
        self.sidebar_collapse_button_v311.setArrowType(Qt.LeftArrow)
        self.sidebar_collapse_button_v311.setAutoRaise(True)
        self.sidebar_collapse_button_v311.setFixedSize(22, 22)
        self.sidebar_collapse_button_v311.setToolTip('Contraer páginas y recientes')
        self.sidebar_collapse_button_v311.setAccessibleName('Contraer panel de páginas y recientes')
        tabs.setCornerWidget(self.sidebar_collapse_button_v311, Qt.TopRightCorner)
        self.sidebar_restore_button_v311 = QToolButton(self.sidebar_host_v311)
        self.sidebar_restore_button_v311.setObjectName('restoreSidebarV311')
        self.sidebar_restore_button_v311.setArrowType(Qt.RightArrow)
        self.sidebar_restore_button_v311.setAutoRaise(True)
        self.sidebar_restore_button_v311.setFixedSize(22, 22)
        self.sidebar_restore_button_v311.setToolTip('Mostrar páginas y recientes')
        self.sidebar_restore_button_v311.setAccessibleName('Mostrar panel de páginas y recientes')
        layout.addWidget(self.sidebar_restore_button_v311, 0, Qt.AlignTop)
        self.sidebar_restore_button_v311.hide()
        tabs.show()
        splitter.setSizes(sizes)
        # The old action separately hid pages and then the complete tab widget.
        # Keep one shared visibility state and leave a reachable restore rail.
        self.thumbnail_action.triggered.disconnect()
        self.thumbnail_action.setText('Panel de páginas y recientes')
        self.thumbnail_action.setToolTip('Mostrar o contraer el panel izquierdo')
        self.thumbnail_action.toggled.connect(self._set_sidebar_expanded_v311)
        self.sidebar_collapse_button_v311.clicked.connect(self.thumbnail_action.trigger)
        self.sidebar_restore_button_v311.clicked.connect(self.thumbnail_action.trigger)
        self.thumbnail_action.changed.connect(self._sync_sidebar_controls_v311)
        self._sync_sidebar_controls_v311()
        if not self.thumbnail_action.isChecked():
            self._set_sidebar_expanded_v311(False)

    def _sync_sidebar_controls_v311(self):
        enabled = self.thumbnail_action.isEnabled()
        self.sidebar_collapse_button_v311.setEnabled(enabled)
        self.sidebar_restore_button_v311.setEnabled(enabled)

    def _set_sidebar_expanded_v311(self, expanded):
        expanded = bool(expanded)
        if expanded == self._sidebar_expanded_v311:
            return
        splitter = self.document_splitter
        sizes = splitter.sizes()
        index = self._sidebar_index_v311
        previous = sizes[index]
        if not expanded:
            self._sidebar_expanded_width_v311 = max(220, min(235, previous))
        width = self._sidebar_expanded_width_v311 if expanded else 26
        self._sidebar_expanded_v311 = expanded
        self.workspace_tabs_v170.setVisible(expanded)
        self.sidebar_restore_button_v311.setVisible(not expanded)
        self.sidebar_host_v311.setMinimumWidth(220 if expanded else 26)
        self.sidebar_host_v311.setMaximumWidth(235 if expanded else 26)
        sizes[index] = width
        # Give the released width to the PDF view, retaining the right-hand
        # editing panel's size instead of redistributing it across all panes.
        if index+1 < len(sizes):
            sizes[index+1] = max(1, sizes[index+1] + previous-width)
        splitter.setSizes(sizes)
