"""Conventional menus backed by the same guarded actions as the tool panels."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QDialog, QInputDialog, QMenu
from .action_state_v310 import set_ui_enabled_v310, ui_enabled_v310


class MenusUiV308Mixin:
    def _create_ui(self):
        super()._create_ui()
        bar = self.menuBar()
        # Configuration is created by the update preferences layer. Place the
        # document menus ahead of it without replacing its persistent action.
        configuration = self.configuration_menu_v307.menuAction()

        def menu(title, name):
            result = QMenu(title, self)
            result.setObjectName(name)
            bar.insertMenu(configuration, result)
            return result

        def entries(target, *names):
            for name in names:
                if name is None:
                    target.addSeparator()
                else:
                    target.addAction(getattr(self, name))

        self.file_menu_v308 = menu('&Archivo', 'fileMenuV308')
        self.close_document_action_v308 = self._menu_action_v308(
            'Cerrar documento', lambda: self._close_tab_v200(self.document_tabs_v200.currentIndex()), 'Ctrl+W')
        self.exit_action_v308 = self._menu_action_v308('Salir', self.close, 'Alt+F4')
        self.share_action_v308 = self._menu_action_v308('Compartir…', self.choose_share_v308)
        entries(self.file_menu_v308, 'open_action', 'recovery_action_v200', None,
                'save_action', 'save_as_action_v300', 'save_all_action_v300',
                'export_document_action', None, 'print_action_v200', 'share_action_v308', None,
                'document_properties_action', 'sign_action', 'document_security_action', None,
                'close_document_action_v308', 'exit_action_v308')

        self.edit_menu_v308 = menu('&Edición', 'editMenuV308')
        entries(self.edit_menu_v308, 'undo_action', 'redo_action', None,
                'cut_action_v170', 'copy_action_v170', 'paste_action_v170', 'delete_action_v170', None,
                'search_action', 'search_previous_action_v306', 'search_next_action_v306', 'replace_action', None,
                'tools_action', 'edit_content_action', 'image_mode_action',
                'add_text_action', 'add_image_action', 'add_text_properties_action',
                'cell_action_v200', 'native_objects_action')

        self.format_menu_v308 = menu('F&ormato', 'formatMenuV308')
        entries(self.format_menu_v308, 'format_action')
        self.format_menu_v308.addSeparator()
        self.font_menu_v308 = self.format_menu_v308.addMenu('Fuente')
        self.font_menu_v308.setObjectName('fontMenuV308')
        self._font_group_v308 = QActionGroup(self.font_menu_v308)
        self.font_menu_v308.aboutToShow.connect(self._populate_fonts_v308)
        self.font_size_action_v308 = self._menu_action_v308('Tamaño de fuente…', self._choose_font_size_v308)
        self.format_menu_v308.addAction(self.font_size_action_v308)
        style_menu = self.format_menu_v308.addMenu('Estilo')
        self.style_actions_v308 = {}
        for key, label in (('bold', 'Negrita'), ('italic', 'Cursiva'), ('underline', 'Subrayado')):
            action = self._menu_action_v308(label, lambda _=False, style=key: self._apply_style_v308(style))
            action.setCheckable(True)
            style_menu.addAction(action)
            self.style_actions_v308[key] = action
        self.text_color_action_v308 = self._menu_action_v308('Color del texto…', self._choose_text_color_v308)
        self.format_menu_v308.addAction(self.text_color_action_v308)
        alignment_menu = self.format_menu_v308.addMenu('Alineación')
        self.alignment_actions_v308 = {}
        alignment_group = QActionGroup(self)
        for key, label in (('left', 'Izquierda'), ('center', 'Centrada'), ('right', 'Derecha'), ('justify', 'Justificada')):
            action = self._menu_action_v308(label, lambda _=False, alignment=key: self._apply_alignment_v308(alignment))
            action.setCheckable(True)
            alignment_group.addAction(action)
            alignment_menu.addAction(action)
            self.alignment_actions_v308[key] = action
        self.paragraph_action_v308 = self._menu_action_v308(
            'Espaciado, sangrías y tabulaciones…', lambda: self._show_inline_panel_v308('paragraph_panel'))
        self.typography_action_v308 = self._menu_action_v308(
            'Opciones tipográficas…', lambda: self._show_inline_panel_v308('typography_panel'))
        entries(self.format_menu_v308, 'paragraph_action_v308', 'typography_action_v308', None,
                'copy_format_action', 'paste_format_action')
        self.image_format_menu_v308 = self.format_menu_v308.addMenu('Imagen')
        self.image_format_actions_v308 = []
        for key, label in (('flip_horizontal', 'Voltear horizontalmente'), ('flip_vertical', 'Voltear verticalmente'),
                           ('left', 'Girar a la izquierda'), ('right', 'Girar a la derecha'),
                           ('crop', 'Recortar…'), ('replace', 'Sustituir…')):
            action = self._menu_action_v308(label, lambda _=False, operation=key: self._apply_image_format_v308(operation))
            self.image_format_menu_v308.addAction(action)
            self.image_format_actions_v308.append(action)

        self.pages_menu_v308 = menu('&Páginas', 'pagesMenuV308')
        entries(self.pages_menu_v308, 'organize_action', 'rotate_pages_action', None,
                'insert_pages_action', 'replace_pages_action', 'delete_pages_action', None,
                'extract_pages_action', 'crop_pages_action', 'split_document_action', 'merge_action')
        self.advanced_menu_v308 = menu('&Herramientas avanzadas', 'advancedMenuV308')
        self.font_inspector_action_v308 = self._menu_action_v308('Inspector de fuentes…', self._inspect_fonts_v308)
        entries(self.advanced_menu_v308, 'document_properties_action', 'document_security_action',
                'sign_action', None, 'objects_action', 'native_objects_action',
                'font_inspector_action_v308', 'forms_action_v200', 'redaction_action_v200',
                'remove_tags_action', None, 'split_action_v200')
        self.view_menu_v308 = menu('&Vista', 'viewMenuV308')
        entries(self.view_menu_v308, 'reading_action', 'tools_action', 'thumbnail_action', None,
                'zoom_in_action', 'zoom_out_action', 'fit_width_action', 'fit_page_action', None,
                'compare_action', 'highlight_action')
        self.configuration_menu_v307.addSeparator()
        self.configuration_menu_v307.addAction(self.update_action_v170)
        for target in (self.file_menu_v308, self.edit_menu_v308, self.format_menu_v308,
                       self.pages_menu_v308, self.advanced_menu_v308, self.view_menu_v308):
            target.aboutToShow.connect(self._refresh_menu_actions_v308)
        self._refresh_menu_actions_v308()

    def _menu_action_v308(self, title, callback, shortcut=None):
        action = QAction(title, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        self.addAction(action)
        return action

    def _refresh_actions(self):
        super()._refresh_actions()
        self._refresh_menu_actions_v308()

    def _sync_format_v150(self):
        super()._sync_format_v150()
        self._refresh_menu_actions_v308()

    def _rich_format_ready_v308(self):
        return bool(getattr(self, '_rich_active', False) and self.canvas.editor.rich_mode
                    and not getattr(self, '_rich_accept_pending', False)
                    and not getattr(self, '_save_transaction_v300', None)
                    and not getattr(self, '_close_waiting_v300', False) and not self._closed)

    def _refresh_menu_actions_v308(self):
        if not hasattr(self, 'style_actions_v308'):
            return
        locked = bool(getattr(self, '_save_transaction_v300', None) or getattr(self, '_close_waiting_v300', False))
        set_ui_enabled_v310(self, self.close_document_action_v308, bool(self.state) and not self.busy and not locked)
        set_ui_enabled_v310(self, self.exit_action_v308, not locked)
        set_ui_enabled_v310(self, self.share_action_v308, ui_enabled_v310(self, self.save_action) and not locked)
        set_ui_enabled_v310(self, self.font_inspector_action_v308, ui_enabled_v310(self, self.font_button) and not locked)
        active = self._rich_format_ready_v308()
        set_ui_enabled_v310(self, self.font_menu_v308, active)
        for action in (self.font_size_action_v308, self.text_color_action_v308,
                       self.paragraph_action_v308, self.typography_action_v308,
                       *self.style_actions_v308.values(), *self.alignment_actions_v308.values()):
            set_ui_enabled_v310(self, action, active)
        if active:
            toolbar = self.canvas.editor.toolbar
            toolbar.sync_cursor()
            for key, action in self.style_actions_v308.items():
                with QSignalBlocker(action):
                    action.setChecked(getattr(toolbar, key).isChecked())
            alignment = toolbar.align.currentData()
            for key, action in self.alignment_actions_v308.items():
                with QSignalBlocker(action):
                    action.setChecked(key == alignment)
        image_ready = ui_enabled_v310(self, self.image_quick_controls) and not locked
        set_ui_enabled_v310(self, self.image_format_menu_v308, image_ready)
        for action in self.image_format_actions_v308:
            set_ui_enabled_v310(self, action, image_ready)

    def _populate_fonts_v308(self):
        self.font_menu_v308.clear()
        if not self._rich_format_ready_v308():
            return
        editor = self.canvas.editor
        style = editor.current_style()
        for entry in editor._catalog:
            action = self.font_menu_v308.addAction(entry.get('name') or entry.get('family') or 'Fuente')
            action.setCheckable(True)
            action.setChecked(entry.get('name') == style.get('font_name')
                              and (not style.get('font_file') or (entry.get('path') or entry.get('font_file')) == style['font_file']))
            action.setEnabled(entry.get('editable') is not False)
            self._font_group_v308.addAction(action)
            action.triggered.connect(lambda _=False, face=entry: self._choose_face_v308(face))

    def _choose_face_v308(self, face):
        if self._rich_format_ready_v308():
            self.canvas.editor.change_face(face)

    def _choose_font_size_v308(self):
        if not self._rich_format_ready_v308():
            return
        dialog = QInputDialog(self)
        dialog.setWindowTitle('Tamaño de fuente')
        dialog.setLabelText('Tamaño en puntos:')
        dialog.setInputMode(QInputDialog.DoubleInput)
        dialog.setDoubleRange(.5, 500.)
        dialog.setDoubleDecimals(2)
        dialog.setDoubleValue(float(self.canvas.editor.current_style().get('size', 12)))
        if self._exec_edit_dialog(dialog) == QDialog.Accepted and self._rich_format_ready_v308():
            self.canvas.editor.merge_style(size=dialog.doubleValue())

    def _apply_style_v308(self, key):
        if not self._rich_format_ready_v308():
            return
        editor = self.canvas.editor
        if key == 'underline':
            editor.merge_style(underline=not editor.current_style().get('underline', False))
        else:
            editor.toolbar.toggle_variant(key)
        self._refresh_menu_actions_v308()

    def _apply_alignment_v308(self, alignment):
        if self._rich_format_ready_v308():
            self.canvas.editor.merge_paragraph(alignment=alignment)
            self._refresh_menu_actions_v308()

    def _choose_text_color_v308(self):
        if self._rich_format_ready_v308():
            self.canvas.editor.toolbar._color()

    def _show_inline_panel_v308(self, name):
        if self._rich_format_ready_v308():
            toolbar = self.canvas.editor.toolbar
            getattr(toolbar, name).show()
            toolbar.adjustSize()

    def _apply_image_format_v308(self, operation):
        if self.image_quick_controls.isEnabled() and not getattr(self, '_save_transaction_v300', None):
            self._quick_image_v150(operation)

    def _inspect_fonts_v308(self):
        if self.font_button.isEnabled() and not getattr(self, '_save_transaction_v300', None):
            self.font_inspector()
