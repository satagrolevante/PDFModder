"""Menus reuse guarded document actions and preserve rich text selection."""
from pathlib import Path

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog

from test_tools_ui_v150 import tools_window  # noqa: F401 — shared no-worker fixture


def test_standard_menus_reuse_actions_and_configuration(tools_window):
    window = tools_window
    assert [action.text().replace('&', '') for action in window.menuBar().actions()] == [
        'Archivo', 'Edición', 'Formato', 'Páginas', 'Herramientas avanzadas', 'Vista', 'Configuración']
    for menu, actions in (
        (window.file_menu_v308, [window.open_action, window.save_action, window.save_as_action_v300,
                                window.save_all_action_v300, window.print_action_v200, window.sign_action,
                                window.document_security_action, window.document_properties_action]),
        (window.edit_menu_v308, [window.undo_action, window.copy_action_v170, window.add_text_action,
                                window.add_image_action, window.edit_content_action, window.search_action]),
        (window.pages_menu_v308, [window.delete_pages_action, window.insert_pages_action,
                                 window.merge_action, window.organize_action]),
        (window.configuration_menu_v307, [window.daily_updates_action_v307, window.update_action_v170]),
    ):
        assert all(action in menu.actions() for action in actions)
    assert not window.close_document_action_v308.isEnabled()
    assert not window.share_action_v308.isEnabled()
    assert not window.font_size_action_v308.isEnabled()
    # Existing capability checks apply identically to panel and menu entries.
    window.state = {'page_count': 1, 'page_capabilities': {'delete': False, 'rotate': True}}
    window._refresh_actions()
    assert window.rotate_pages_action.isEnabled()
    assert not window.delete_pages_action.isEnabled()
    assert window.file_menu_v308.actions()[0] is window.open_action
    window.future = object()
    window._refresh_actions()
    assert not window.open_action.isEnabled()
    assert not window.close_document_action_v308.isEnabled()
    window.future = None


def test_menu_close_uses_current_tab_save_discard_cancel(tools_window, monkeypatch):
    window = tools_window
    window.state = {'page_count': 1}
    window.document_tabs_v200.blockSignals(True)
    window.document_tabs_v200.addTab('Primero')
    window.document_tabs_v200.addTab('Segundo')
    window.document_tabs_v200.setCurrentIndex(1)
    window.document_tabs_v200.blockSignals(False)
    calls = []
    monkeypatch.setattr(window, '_close_tab_v200', lambda index: calls.append(index))
    window._refresh_menu_actions_v308()
    window.close_document_action_v308.trigger()
    assert calls == [1]


def _rich_range(window):
    editor = window.canvas.editor
    font = Path(__file__).resolve().parents[1] / 'assets/fonts/LiberationSans-Regular.ttf'
    entry = {'name': 'LiberationSans', 'family': 'Liberation Sans', 'variant': 'Regular',
             'path': str(font), 'editable': True, 'bold': False, 'italic': False}
    style = {'font_name': 'LiberationSans', 'font_xref': 7, 'font_resource': 'F1',
             'size': 12., 'color': (0., 0., 0.), 'opacity': 1., 'char_spacing': 0., 'underline': False}
    editor.load_payload({'page': 0, 'ids': list(range(7)), 'rect': (10., 10., 180., 60.),
                         'runs': [{'text': 'UNO DOS', **style}], 'revision': 'menu-test',
                         'font_previews': [{'font_xref': 7, **entry}], 'catalog': [entry]}, zoom=1.)
    window._rich_active = True
    cursor = editor.textCursor()
    cursor.setPosition(4)
    cursor.setPosition(7, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    window._sync_format_v150()
    return editor


def test_format_menu_changes_selected_range_and_respects_accept_and_save_lock(tools_window, monkeypatch):
    window = tools_window
    editor = _rich_range(window)
    assert window.font_size_action_v308.isEnabled()
    window.style_actions_v308['underline'].trigger()
    runs = editor.payload()['runs']
    assert runs[0]['text'] == 'UNO ' and not runs[0].get('underline')
    assert runs[-1]['text'] == 'DOS' and runs[-1]['underline']
    window.alignment_actions_v308['center'].trigger()
    assert editor.toolbar.align.currentData() == 'center'
    assert editor.textCursor().selectedText() == 'DOS'

    def choose_size(dialog):
        dialog.setDoubleValue(18.)
        return QDialog.Accepted
    monkeypatch.setattr(window, '_exec_edit_dialog', choose_size)
    window.font_size_action_v308.trigger()
    assert editor.payload()['runs'][0]['size'] == 12.
    assert editor.payload()['runs'][-1]['size'] == 18.
    window._populate_fonts_v308()
    assert [action.text() for action in window.font_menu_v308.actions()] == ['LiberationSans']
    window._populate_fonts_v308()
    assert len(window._font_group_v308.actions()) == 1

    window._rich_accept_pending = True
    window._refresh_menu_actions_v308()
    assert not window.font_size_action_v308.isEnabled()
    assert not any(action.isEnabled() for action in window.style_actions_v308.values())
    window._rich_accept_pending = False
    window._save_transaction_v300 = {'test': True}
    window._refresh_menu_actions_v308()
    assert not window.font_menu_v308.isEnabled()
    assert not window.exit_action_v308.isEnabled()
    window._save_transaction_v300 = None
    window._rich_active = False
