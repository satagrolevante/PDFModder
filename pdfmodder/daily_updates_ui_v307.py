"""Opt-out daily startup check, with a quiet background request and an explicit offer."""
from datetime import date

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox

from .daily_updates_v307 import DailyUpdatePreferences
from .updates_v170 import version_tuple


def local_today():
    return date.today()


class DailyUpdatesUiV307Mixin:
    def _create_ui(self):
        super()._create_ui()
        self._daily_preferences_v307 = DailyUpdatePreferences(
            self._local_data_v170 / 'update_preferences.json')
        self._daily_startup_v307 = False
        self._daily_phase_v307 = None
        self._daily_updater_v307 = None
        self._daily_version_v307 = None
        self._daily_prompt_v307 = None
        self._daily_timer_v307 = QTimer(self)
        self._daily_timer_v307.setSingleShot(True)
        self._daily_timer_v307.timeout.connect(self._daily_update_tick_v307)
        self.configuration_menu_v307 = self.menuBar().addMenu('Configuración')
        self.configuration_menu_v307.setObjectName('configurationMenuV307')
        self.daily_updates_action_v307 = QAction(
            'Comprobar actualizaciones automáticamente cada día', self)
        self.daily_updates_action_v307.setObjectName('dailyUpdatesActionV307')
        self.daily_updates_action_v307.setCheckable(True)
        self.daily_updates_action_v307.setChecked(self._daily_preferences_v307.read()['enabled'])
        self.daily_updates_action_v307.setToolTip(
            'Al primer inicio de cada día, consultar GitHub en segundo plano. '
            'Solo avisa si hay una versión nueva.')
        self.daily_updates_action_v307.toggled.connect(self._toggle_daily_updates_v307)
        self.configuration_menu_v307.addAction(self.daily_updates_action_v307)

    def start_daily_update_check_v307(self):
        """The interactive entry point calls this after showing the window."""
        if self._closed or self._daily_startup_v307:
            return
        self._daily_startup_v307 = True
        self._schedule_daily_update_v307()

    def _schedule_daily_update_v307(self):
        if self._closed or not self._daily_preferences_v307.read()['enabled']:
            return
        self._daily_phase_v307 = 'waiting'
        self._daily_timer_v307.start(2000)

    def _toggle_daily_updates_v307(self, enabled):
        try:
            self._daily_preferences_v307.set_enabled(enabled)
        except OSError:
            with QSignalBlocker(self.daily_updates_action_v307):
                self.daily_updates_action_v307.setChecked(self._daily_preferences_v307.read()['enabled'])
            QMessageBox.warning(self, 'Configuración',
                                'No se ha podido guardar la opción de actualizaciones automáticas.')
            return
        if not enabled:
            self._stop_daily_update_v307(cancel=True)
        elif self._daily_startup_v307:
            self._schedule_daily_update_v307()

    def _stop_daily_update_v307(self, *, cancel=False):
        self._daily_timer_v307.stop()
        if cancel and self._daily_phase_v307 == 'checking' and self._daily_updater_v307 is not None:
            self._daily_updater_v307.cancel()
        self._daily_phase_v307 = None
        self._daily_updater_v307 = None
        self._daily_version_v307 = None
        prompt, self._daily_prompt_v307 = self._daily_prompt_v307, None
        if prompt is not None:
            prompt.reject()

    def _before_manual_updates_v307(self):
        # The manual dialog takes over the same updater and its verified data.
        # It remains available even if startup checks are disabled or deferred.
        self._stop_daily_update_v307()

    def _daily_offer_safe_v307(self):
        return (self.isVisible() and self.isActiveWindow() and not self.busy
                and QApplication.activeModalWidget() is None
                and not self.canvas.editor.isVisible()
                and not getattr(self, '_rich_active', False)
                and not getattr(self, '_rich_loading', False)
                and not getattr(self, '_rich_accept_pending', False)
                and not getattr(self, '_save_transaction_v300', None)
                and not getattr(self, '_close_waiting_v300', False)
                and not getattr(self, '_cell_draw_v200', False)
                and not getattr(self, '_signature_placement_dialog', None)
                and not getattr(self, '_office_conversion_v305', None)
                and not getattr(self, '_mode_preparing_v171', False))

    def _daily_update_tick_v307(self):
        if self._closed or not self._daily_startup_v307 or self._daily_phase_v307 is None:
            self._stop_daily_update_v307()
            return
        if self._daily_phase_v307 == 'waiting':
            if not self.isVisible():
                self._daily_timer_v307.start(500)
                return
            updater = self._updater_v170
            if updater.status()['busy']:
                self._daily_timer_v307.start(250)
                return
            if not self._daily_preferences_v307.claim_check(local_today()):
                self._stop_daily_update_v307()
                return
            self._daily_updater_v307 = updater
            self._daily_phase_v307 = 'checking'
            if not updater.check():
                self._stop_daily_update_v307()
                return
        if self._daily_phase_v307 == 'checking':
            status = self._daily_updater_v307.status()
            if status['busy']:
                self._daily_timer_v307.start(150)
                return
            try:
                newer = version_tuple(status['latestVersion']) > version_tuple(status['installedVersion'])
            except (KeyError, ValueError):
                newer = False
            if status['state'] != 'available' or not newer:
                self._stop_daily_update_v307()
                return
            self._daily_version_v307 = status['latestVersion']
            self._daily_phase_v307 = 'offer'
        if self._daily_phase_v307 == 'offer':
            if not self._daily_offer_safe_v307():
                self._daily_timer_v307.start(500)
                return
            preferences = self._daily_preferences_v307.read()
            if (not preferences['enabled'] or (preferences['deferred_until'] is not None
                    and preferences['deferred_until'] > local_today().isoformat())):
                self._stop_daily_update_v307()
                return
            self._show_daily_offer_v307()

    def _show_daily_offer_v307(self):
        self._daily_timer_v307.stop()
        self._daily_phase_v307 = 'prompt'
        prompt = QMessageBox(QMessageBox.Information, 'Actualización disponible',
            f'Hay una nueva versión de PDF Modder: {self._daily_version_v307}.\n'
            '¿Quieres actualizar ahora o posponer hasta mañana?', QMessageBox.NoButton, self)
        prompt.setObjectName('dailyUpdatePromptV307')
        prompt.setTextFormat(Qt.PlainText)
        now = prompt.addButton('Actualizar ahora', QMessageBox.AcceptRole)
        later = prompt.addButton('Más tarde (mañana)', QMessageBox.RejectRole)
        prompt.setDefaultButton(now)
        prompt.setEscapeButton(later)
        self._daily_prompt_v307 = prompt

        def chosen(_result):
            if self._daily_prompt_v307 is not prompt:
                prompt.deleteLater()
                return
            self._daily_prompt_v307 = None
            self._daily_phase_v307 = None
            self._daily_updater_v307 = None
            self._daily_version_v307 = None
            update_now = prompt.clickedButton() is now
            prompt.deleteLater()
            if self._closed:
                return
            if update_now:
                self.show_updates_v170(start_update=True)
            else:
                try:
                    self._daily_preferences_v307.postpone(local_today())
                except OSError:
                    # The daily claim is already persistent. A failed extra
                    # postponement cannot produce another automatic check today.
                    pass

        prompt.finished.connect(chosen)
        prompt.open()

    def closeEvent(self, event):
        super().closeEvent(event)
        if self._closed:
            self._stop_daily_update_v307(cancel=True)
