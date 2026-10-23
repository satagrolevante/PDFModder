"""Publish action availability once, retaining legitimate Qt notifications."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QPushButton, QWidget

from pdfmodder.action_state_v310 import (
    ActionStateV310Mixin, set_ui_enabled_v310, ui_enabled_v310,
)


class EarlierRules:
    def _refresh_actions(self):
        set_ui_enabled_v310(self, self.save, False)
        set_ui_enabled_v310(self, self.search, True)


class LaterRules(EarlierRules):
    def _refresh_actions(self):
        super()._refresh_actions()
        set_ui_enabled_v310(self, self.save, True)
        set_ui_enabled_v310(self, self.search, False)

    def _refresh_tools_v150(self):
        self.tool_refreshes += 1
        set_ui_enabled_v310(self, self.dependent, ui_enabled_v310(self, self.save))


class Window(ActionStateV310Mixin, LaterRules, QMainWindow):
    def __init__(self):
        super().__init__()
        self.save = QAction('Save', self)
        self.search = QAction('Search', self)
        self.dependent = QAction('Dependent', self)
        self.tool_refreshes = 0
        self.finalize_calls = 0
        self.search.changed.connect(self._refresh_tools_v150)

    def _finalize_action_states_v310(self):
        self.finalize_calls += 1


def test_final_state_emits_only_real_action_changes(qtbot):
    window = Window()
    qtbot.addWidget(window)
    save_changes, search_changes = [], []
    window.save.changed.connect(lambda: save_changes.append(window.save.isEnabled()))
    window.search.changed.connect(lambda: search_changes.append(window.search.isEnabled()))
    window._refresh_actions()
    assert save_changes == []
    assert search_changes == [False]
    assert window.save.isEnabled() and window.dependent.isEnabled()
    assert window.tool_refreshes == 1, 'Commit signals must not recompute dependent tools'
    assert window.finalize_calls == 1
    window._refresh_actions()
    assert save_changes == [] and search_changes == [False]


def test_pending_dependency_reads_final_intended_state(qtbot):
    window = Window()
    qtbot.addWidget(window)
    window.save.setEnabled(False)
    window.dependent.setEnabled(False)
    changed = []
    window.save.changed.connect(lambda: changed.append(window.save.isEnabled()))
    window._refresh_actions()
    assert changed == [True]
    assert window.dependent.isEnabled()


def test_helpers_keep_immediate_behavior_without_mixin(qtbot):
    owner = SimpleNamespace()
    widget = QWidget()
    qtbot.addWidget(widget)
    action = QAction('Legacy harness')
    set_ui_enabled_v310(owner, action, False)
    set_ui_enabled_v310(owner, widget, False)
    assert not ui_enabled_v310(owner, action)
    assert not ui_enabled_v310(owner, widget)
    set_ui_enabled_v310(owner, widget, True)
    assert widget.isEnabled()


def test_widget_dependencies_respect_pending_parent_and_local_state(qtbot):
    window = Window()
    qtbot.addWidget(window)
    parent = QWidget(window)
    child = QPushButton(parent)
    parent.setEnabled(False)
    seen = []
    def contribute():
        set_ui_enabled_v310(window, parent, True)
        seen.append(ui_enabled_v310(window, child))
        set_ui_enabled_v310(window, child, False)
        seen.append(ui_enabled_v310(window, child))
    window._collect_action_states_v310(contribute)
    assert seen == [True, False]
    assert parent.isEnabled() and not child.isEnabled()


def test_reenabling_parent_never_temporarily_enables_disabled_child(qtbot):
    window = Window()
    qtbot.addWidget(window)
    parent = QWidget(window)
    child = QPushButton(parent)
    parent.setEnabled(False)
    transitions = []
    class Watch(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.EnabledChange:
                transitions.append(obj.isEnabled())
            return False
    watch = Watch(child)
    child.installEventFilter(watch)
    def contribute():
        set_ui_enabled_v310(window, parent, True)
        set_ui_enabled_v310(window, child, False)
    window._collect_action_states_v310(contribute)
    assert transitions == []


def test_failed_calculation_does_not_publish_partial_availability(qtbot):
    window = Window()
    qtbot.addWidget(window)
    changes = []
    window.save.changed.connect(lambda: changes.append(window.save.isEnabled()))
    def fail():
        set_ui_enabled_v310(window, window.save, False)
        raise ValueError('Calculation failed')
    with pytest.raises(ValueError, match='Calculation failed'):
        window._collect_action_states_v310(fail)
    assert window.save.isEnabled() and changes == []
    assert window._action_state_v310 is None


def test_standalone_tool_refresh_also_applies_final_policy(qtbot):
    window = Window()
    qtbot.addWidget(window)
    window._refresh_tools_v150()
    assert window.finalize_calls == 1
    assert window._action_state_v310 is None
