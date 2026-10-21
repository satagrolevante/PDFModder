"""Daily startup notifications use the existing updater without blocking PDF work."""
from datetime import date, timedelta
import sys
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from pdfmodder import __version__
from pdfmodder.updates_v170 import version_tuple
from test_tools_ui_v150 import NoPdfPool


def next_version():
    major, minor, patch = version_tuple(__version__)
    return f'{major}.{minor}.{patch + 1}'


class ControlledUpdater:
    def __init__(self):
        self._cancel = threading.Event()
        self.calls = []
        self.value = {'state': 'idle', 'busy': False, 'installedVersion': __version__,
                      'latestVersion': '', 'message': 'cuando quieras', 'progress': 0,
                      'retryAt': 0}

    def status(self):
        return dict(self.value)

    def check(self):
        self.calls.append('check')
        self._cancel.clear()
        self.value.update(state='checking', busy=True)
        return True

    def cancel(self):
        self.calls.append('cancel')
        self._cancel.set()
        self.value.update(state='cancelled', busy=False)

    def finish(self, state='available', version=None):
        self.value.update(state=state, busy=False,
                          latestVersion=version if version is not None else next_version())


def pump(window, count=4):
    """Advance only the daily controller, with no network or wall-clock delay."""
    for _ in range(count):
        window._daily_timer_v307.stop()
        window._daily_update_tick_v307()
        QApplication.processEvents()
    window._daily_timer_v307.stop()


def begin(window):
    window.start_daily_update_check_v307()
    pump(window, 1)


@pytest.fixture
def daily_windows(qtbot, monkeypatch, tmp_path):
    import pdfmodder.app as application
    from pdfmodder import daily_updates_ui_v307 as daily

    monkeypatch.setattr(application, 'ProcessPoolExecutor', NoPdfPool)
    monkeypatch.setattr(application.MainWindow, '_offer_recovery_v200', lambda *_: None)
    today = [date(2026, 11, 4)]
    monkeypatch.setattr(daily, 'local_today', lambda: today[0])
    windows = []

    def close(widget):
        widget.future = None
        widget.state = {}
        widget._allow_close = True

    def create(folder='preferences'):
        directory = tmp_path / folder
        directory.mkdir(exist_ok=True)
        window = application.MainWindow(config_path=directory / 'fonts.json')
        qtbot.addWidget(window, before_close_func=close)
        window.poller.stop()
        window.thumbnail_timer.stop()
        window.reader_timer_v180.stop()
        window._updater_v170 = ControlledUpdater()
        monkeypatch.setattr(window, 'isActiveWindow', lambda: True)
        window.show()
        QApplication.processEvents()
        windows.append(window)
        return window

    yield create, today
    for window in reversed(windows):
        close(window)
        window.close()


def test_default_configuration_and_daily_check_leave_event_loop_responsive(daily_windows, qtbot):
    create, _ = daily_windows
    window = create()
    action = window.daily_updates_action_v307
    assert action.isCheckable() and action.isChecked()
    menu = window.configuration_menu_v307
    assert menu.menuAction() in window.menuBar().actions()
    assert menu.title().replace('&', '') == 'Configuración'
    assert action in menu.actions()
    assert window._updater_v170.calls == []
    window.start_daily_update_check_v307()
    assert window._daily_timer_v307.isActive()
    assert window._updater_v170.calls == []
    pump(window, 1)
    assert window._updater_v170.calls == ['check']
    events = []
    QTimer.singleShot(0, lambda: events.append('responsive'))
    qtbot.waitUntil(lambda: bool(events))
    assert window._updater_v170.status()['busy']
    assert window._daily_prompt_v307 is None


def test_disabled_preference_persists_and_reenable_schedules_current_startup(daily_windows):
    create, _ = daily_windows
    first = create()
    first.daily_updates_action_v307.trigger()
    assert not first._daily_preferences_v307.read()['enabled']
    first._allow_close = True
    first.close()
    second = create()
    assert not second.daily_updates_action_v307.isChecked()
    begin(second)
    assert second._updater_v170.calls == []
    second.daily_updates_action_v307.trigger()
    assert second._daily_preferences_v307.read()['enabled']
    pump(second)
    assert second._updater_v170.calls == ['check']


def test_restarts_check_once_per_local_day_even_after_connection_failure(daily_windows):
    create, today = daily_windows
    first = create()
    begin(first)
    first._updater_v170.finish('error')
    pump(first)
    same_day = create()
    begin(same_day)
    assert same_day._updater_v170.calls == []
    today[0] += timedelta(days=1)
    next_day = create()
    begin(next_day)
    assert next_day._updater_v170.calls == ['check']


@pytest.mark.parametrize('state', ['current', 'error', 'unavailable', 'rate_limited', 'cancelled'])
def test_no_update_or_network_problem_is_silent(daily_windows, monkeypatch, state):
    create, _ = daily_windows
    window = create()
    notices = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: notices.append(args))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: notices.append(args))
    begin(window)
    window._updater_v170.finish(state, __version__)
    pump(window)
    assert window._daily_prompt_v307 is None
    assert not notices
    assert window._updater_v170.calls == ['check']


@pytest.mark.parametrize('choice', ['later', 'escape', 'close'])
def test_new_release_can_be_postponed_until_tomorrow_across_restarts(daily_windows, qtbot, choice):
    create, today = daily_windows
    window = create()
    begin(window)
    window._updater_v170.finish()
    pump(window)
    prompt = window._daily_prompt_v307
    assert isinstance(prompt, QMessageBox) and prompt.isVisible()
    assert next_version() in prompt.text()
    assert any(button.text() == 'Actualizar ahora' for button in prompt.buttons())
    if choice == 'later':
        next(button for button in prompt.buttons() if button.text() == 'Más tarde (mañana)').click()
    elif choice == 'escape':
        qtbot.keyClick(prompt, Qt.Key_Escape)
    else:
        prompt.close()
    QApplication.processEvents()
    assert window._daily_preferences_v307.read()['deferred_until'] == (today[0] + timedelta(days=1)).isoformat()
    assert window._updater_v170.calls == ['check']
    same_day = create()
    begin(same_day)
    assert same_day._updater_v170.calls == []
    today[0] += timedelta(days=1)
    tomorrow = create()
    begin(tomorrow)
    assert tomorrow._updater_v170.calls == ['check']


def test_update_now_enters_existing_verified_update_workflow_only_after_click(daily_windows, monkeypatch):
    create, _ = daily_windows
    window = create()
    launches = []
    monkeypatch.setattr(window, 'show_updates_v170', lambda **options: launches.append(options))
    begin(window)
    window._updater_v170.finish()
    pump(window)
    assert launches == []
    prompt = window._daily_prompt_v307
    next(button for button in prompt.buttons() if button.text() == 'Actualizar ahora').click()
    QApplication.processEvents()
    assert launches == [{'start_update': True}]
    assert window._updater_v170.calls == ['check']


@pytest.mark.parametrize('work', ['busy', 'rich', 'editor', 'modal', 'inactive'])
def test_offer_waits_until_editing_and_other_dialogs_finish(daily_windows, monkeypatch, qtbot, work):
    create, _ = daily_windows
    window = create()
    begin(window)
    window._updater_v170.finish()
    modal = None
    if work == 'busy':
        window.future = object()
    elif work == 'rich':
        window._rich_active = True
    elif work == 'editor':
        monkeypatch.setattr(window.canvas.editor, 'isVisible', lambda: True)
    elif work == 'inactive':
        monkeypatch.setattr(window, 'isActiveWindow', lambda: False)
    else:
        modal = QDialog(window)
        qtbot.addWidget(modal)
        modal.setModal(True)
        modal.show()
        QApplication.processEvents()
        assert QApplication.activeModalWidget() is modal
    pump(window)
    assert window._daily_prompt_v307 is None
    window.future = None
    window._rich_active = False
    monkeypatch.setattr(window.canvas.editor, 'isVisible', lambda: False)
    monkeypatch.setattr(window, 'isActiveWindow', lambda: True)
    if modal:
        modal.reject()
    pump(window)
    assert window._daily_prompt_v307 is not None


def test_disable_during_own_check_cancels_and_never_shows_late_response(daily_windows):
    create, _ = daily_windows
    window = create()
    begin(window)
    window.daily_updates_action_v307.trigger()
    assert window._updater_v170._cancel.is_set()
    window._updater_v170.finish()
    pump(window)
    assert window._daily_prompt_v307 is None


def test_closing_window_stops_pending_checks_and_ignores_late_response(daily_windows):
    create, _ = daily_windows
    window = create()
    begin(window)
    window._allow_close = True
    window.close()
    assert window._updater_v170._cancel.is_set()
    assert not window._daily_timer_v307.isActive()
    window._updater_v170.finish()
    pump(window)
    assert window._daily_prompt_v307 is None


def test_manual_update_takes_ownership_and_disabling_daily_check_leaves_download_running(daily_windows):
    create, _ = daily_windows
    window = create()
    begin(window)
    window._before_manual_updates_v307()
    window._updater_v170.value.update(state='downloading', busy=True)
    window.daily_updates_action_v307.trigger()
    pump(window)
    assert window._updater_v170.calls == ['check']
    assert not window._updater_v170._cancel.is_set()
    assert window._updater_v170.status()['state'] == 'downloading'
    assert window._daily_prompt_v307 is None


@pytest.mark.parametrize('automatic', [False, True])
def test_update_action_and_update_now_use_the_real_dialog_entrypoint(daily_windows, monkeypatch, automatic):
    from pdfmodder import workspace_ui_v170 as workspace
    create, _ = daily_windows
    window = create()
    calls = []

    class UpdateDialog:
        def __init__(self, owner, updater):
            assert owner is window and updater is window._updater_v170
            calls.append('dialog')

        def _check(self):
            calls.append('check')

        def exec(self):
            calls.append('exec')
            QApplication.processEvents()

    monkeypatch.setattr(workspace, 'UpdatesDialog', UpdateDialog)
    if automatic:
        window.show_updates_v170(start_update=True)
    else:
        window.update_action_v170.trigger()
    assert calls == ['dialog', 'exec'] + (['check'] if automatic else [])


@pytest.mark.parametrize('smoke', [False, True])
def test_real_entrypoint_schedules_daily_check_only_for_normal_startup(qtbot, monkeypatch, tmp_path, smoke):
    from pdfmodder import app as application
    calls = []

    class StartupWindow(QWidget):
        def __init__(self, *args, **kwargs):
            super().__init__()
            qtbot.addWidget(self)

        def start_daily_update_check_v307(self):
            calls.append('daily')

    monkeypatch.setattr(application, 'MainWindow', StartupWindow)
    monkeypatch.setattr(application.QApplication, 'exec', lambda *_: 0)
    # This test checks entry-point scheduling, not global Qt configuration.
    # Changing names or style would alter subsequent windows in this process.
    for setter in ('setStyle', 'setApplicationName', 'setOrganizationName'):
        monkeypatch.setattr(application.QApplication, setter, lambda *_: None)
    monkeypatch.setitem(sys.modules, 'pdfmodder.smoke_v300', SimpleNamespace(SmokeV300=lambda *args: object()))
    arguments = ['--smoke-v300', str(tmp_path / 'smoke.json')] if smoke else []
    assert application.main(arguments) == 0
    assert calls == ([] if smoke else ['daily'])
