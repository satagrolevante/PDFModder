"""Collect action availability before applying a single coherent Qt state.

Refresh contributors use the explicit setter/getter below. Ordinary calls made
outside a refresh keep Qt's usual immediate behavior; no Qt methods or signals
are patched or blocked.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def _local_enabled_v310(control):
    if isinstance(control, QWidget):
        return not control.testAttribute(Qt.WA_ForceDisabled)
    return control.isEnabled()


def set_ui_enabled_v310(owner, control, enabled):
    enabled = bool(enabled)
    batch = getattr(owner, '_action_state_v310', None)
    if batch is not None and batch['phase'] == 'collect':
        batch['enabled'][control] = enabled
    elif _local_enabled_v310(control) != enabled:
        control.setEnabled(enabled)


def ui_enabled_v310(owner, control):
    batch = getattr(owner, '_action_state_v310', None)
    pending = batch['enabled'] if batch is not None else {}
    if not isinstance(control, QWidget):
        return pending.get(control, control.isEnabled())
    # QWidget.isEnabled() includes ancestors. Evaluate pending parent changes
    # as well, so a child does not inherit the previous refresh's disabled state.
    current = control
    while current is not None:
        if not pending.get(current, _local_enabled_v310(current)):
            return False
        if current.isWindow():
            break
        current = current.parentWidget()
    return True


class ActionStateV310Mixin:
    def _refresh_actions(self):
        if getattr(self, '_action_state_v310', None) is not None:
            # Nested UI notifications cannot start a second state calculation
            # halfway through collecting or publishing the current one.
            return

        def contribute():
            result = super(ActionStateV310Mixin, self)._refresh_actions()
            # Availability signals no longer fire during collection. Calculate
            # their dependent tool controls explicitly from the pending state.
            tools = getattr(super(ActionStateV310Mixin, self), '_refresh_tools_v150', None)
            if tools is not None:
                tools()
            menus = getattr(super(ActionStateV310Mixin, self), '_refresh_menu_actions_v308', None)
            if menus is not None:
                menus()
            return result

        return self._collect_action_states_v310(contribute)

    def _collect_action_states_v310(self, contribute):
        batch = {'phase': 'collect', 'enabled': {}}
        self._action_state_v310 = batch
        try:
            result = contribute()
            finalize = getattr(self, '_finalize_action_states_v310', None)
            if finalize is not None:
                finalize()
            batch['phase'] = 'commit'
            # Disable children before re-enabling a parent: inherited QWidget
            # state must not briefly expose a child whose final state is off.
            changes = list(batch['enabled'].items())
            def depth(control):
                value = 0
                while isinstance(control, QWidget) and not control.isWindow():
                    value += 1
                    control = control.parentWidget()
                return value
            changes.sort(key=lambda item: (item[1], depth(item[0]) if item[1] else -depth(item[0])))
            for control, enabled in changes:
                if _local_enabled_v310(control) != enabled:
                    control.setEnabled(enabled)
            return result
        finally:
            self._action_state_v310 = None

    def _refresh_tools_v150(self):
        batch = getattr(self, '_action_state_v310', None)
        if batch is not None:
            if batch['phase'] == 'collect':
                return super()._refresh_tools_v150()
            # QAction.changed from the final commit has already been accounted
            # for by the explicit dependent-control calculation above.
            return
        return self._collect_action_states_v310(super()._refresh_tools_v150)

    def _refresh_menu_actions_v308(self):
        batch = getattr(self, '_action_state_v310', None)
        if batch is not None and batch['phase'] == 'commit':
            return
        if batch is not None:
            return super()._refresh_menu_actions_v308()
        return self._collect_action_states_v310(super()._refresh_menu_actions_v308)
