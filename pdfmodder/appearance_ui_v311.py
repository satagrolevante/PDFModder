"""Persistent light/dark interface palettes without changing PDF page artwork."""
import re

from PySide6.QtCore import QEvent, QObject, QSettings, QSignalBlocker
from PySide6.QtGui import QAction, QActionGroup, QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget


class AppearancePreferencesV311:
    def __init__(self, path):
        self.path = str(path)

    def read(self):
        value = QSettings(self.path, QSettings.IniFormat).value('theme', 'light')
        return value if value in ('light', 'dark') else 'light'

    def write(self, theme):
        if theme not in ('light', 'dark'):
            raise ValueError('Tema no válido.')
        settings = QSettings(self.path, QSettings.IniFormat)
        settings.setValue('theme', theme)
        settings.sync()
        if settings.status() != QSettings.NoError:
            raise OSError('No se pudo guardar el tema elegido.')


def interface_palette_v311(theme):
    dark = theme == 'dark'
    palette = QPalette(QColor('#303844' if dark else '#e7ebef'))
    colors = {
        QPalette.Window: '#252b33' if dark else '#f1f3f5',
        QPalette.WindowText: '#e6eaf0' if dark else '#202830',
        QPalette.Base: '#1d232b' if dark else '#ffffff',
        QPalette.AlternateBase: '#303844' if dark else '#eaf0f5',
        QPalette.Text: '#e6eaf0' if dark else '#202830',
        QPalette.Button: '#303844' if dark else '#e7ebef',
        QPalette.ButtonText: '#e6eaf0' if dark else '#202830',
        QPalette.ToolTipBase: '#303844' if dark else '#fffde4',
        QPalette.ToolTipText: '#e6eaf0' if dark else '#202830',
        QPalette.Highlight: '#355d86' if dark else '#b5d5f4',
        QPalette.HighlightedText: '#ffffff' if dark else '#142b40',
        QPalette.PlaceholderText: '#a4aebc' if dark else '#65717f',
        QPalette.Link: '#8fc6ff' if dark else '#165e9d',
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor('#808b99' if dark else '#88939e'))
    return palette


def _dark_stylesheet_v311(style):
    def replace(match):
        key, value = match.group(1), match.group(2)
        color = QColor(value)
        if not color.isValid():
            return match.group(0)
        if key == 'color':
            if color.red() > color.green()*1.4:
                value = '#ffb4a8'
            elif color.green() > color.red()*1.2 and color.green() > color.blue():
                value = '#a2dfb3'
            else:
                value = '#e6eaf0'
        elif key.startswith('background'):
            value = {
                '#ffffff': '#1d232b', 'white': '#1d232b',
                '#d9e8f5': '#355474', '#e3edf8': '#344452',
                '#fff4c7': '#544826', '#e3f1e7': '#244739',
                '#ffebe7': '#512f30', '#e6eff5': '#283f51',
            }.get(value.lower(), '#303844')
        else:
            value = '#607186'
        return key + ': ' + value
    return re.sub(r'(?<![\w-])(color|background(?:-color)?|border-color)\s*:\s*(#[0-9a-fA-F]{3,8}|white|black)\b', replace, style)


class _ThemeFilterV311(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.applying = False

    def eventFilter(self, watched, event):
        if (not self.applying and isinstance(watched, QWidget)
                and event.type() in (QEvent.Polish, QEvent.StyleChange)):
            self.owner._retint_local_style_v311(watched)
        return False


class AppearanceUiV311Mixin:
    def _create_ui(self):
        super()._create_ui()
        self._appearance_preferences_v311 = AppearancePreferencesV311(
            self._local_data_v170 / 'appearance.ini')
        self.appearance_menu_v311 = self.configuration_menu_v307.addMenu('Aspecto')
        self.appearance_menu_v311.setObjectName('appearanceMenuV311')
        self.theme_actions_v311 = {}
        self._theme_group_v311 = QActionGroup(self)
        for theme, label in (('light', 'Tema claro'), ('dark', 'Tema oscuro')):
            action = QAction(label, self)
            action.setObjectName('theme' + theme.title() + 'V311')
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, value=theme: self._choose_theme_v311(value))
            self._theme_group_v311.addAction(action)
            self.appearance_menu_v311.addAction(action)
            self.theme_actions_v311[theme] = action
        self._theme_filter_v311 = _ThemeFilterV311(self)
        QApplication.instance().installEventFilter(self._theme_filter_v311)
        self._apply_theme_v311(self._appearance_preferences_v311.read())

    def _choose_theme_v311(self, theme):
        try:
            self._appearance_preferences_v311.write(theme)
        except OSError as exc:
            with QSignalBlocker(self._theme_group_v311):
                self.theme_actions_v311[self._theme_v311].setChecked(True)
            self._notice(str(exc))
            return
        self._apply_theme_v311(theme)

    def _retint_local_style_v311(self, widget):
        guard = getattr(self, '_theme_filter_v311', None)
        if guard is None or guard.applying:
            return
        style = widget.styleSheet()
        previous = widget.property('_themeOutputV311')
        original = widget.property('_themeOriginalV311')
        if previous is None or style != previous:
            original = style
            widget.setProperty('_themeOriginalV311', style)
        # The on-page editor displays the document's actual colors.
        is_page_editor = widget.objectName() == 'onPageEditor'
        theme = QApplication.instance().property('_interfaceThemeV311') or self._theme_v311
        output = _dark_stylesheet_v311(original) if theme == 'dark' and not is_page_editor else original
        widget.setProperty('_themeOutputV311', output)
        if output != style:
            guard.applying = True
            try:
                widget.setStyleSheet(output)
            finally:
                guard.applying = False

    def _apply_theme_v311(self, theme):
        self._theme_v311 = theme
        app = QApplication.instance()
        app.setProperty('_interfaceThemeV311', theme)
        if app.style().objectName().lower() != 'fusion':
            app.setStyle('Fusion')
        palette = interface_palette_v311(theme)
        changed = app.palette() != palette
        if changed:
            app.setPalette(palette)
        for key, action in self.theme_actions_v311.items():
            with QSignalBlocker(action):
                action.setChecked(key == theme)
        # Rich text on the page remains black on white unless the PDF itself
        # specifies a different text color; no document formats are changed.
        page_palette = interface_palette_v311('light')
        self.canvas.editor.setPalette(page_palette)
        widgets = app.allWidgets() if changed else [self, *self.findChildren(QWidget)]
        for widget in widgets:
            self._retint_local_style_v311(widget)
            if changed:
                widget.update()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            QApplication.instance().removeEventFilter(self._theme_filter_v311)
