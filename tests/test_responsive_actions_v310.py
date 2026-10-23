"""Real window action policies stay coherent across background page work."""
import pytest

from test_tools_ui_v150 import tools_window, _canvas_document


def document_state(window, *, reading=False):
    _canvas_document(window)
    window.zoom = window.canvas.zoom
    window.application_mode = 'reading' if reading else 'editing'
    window.state = {'page_count': 1, 'session_id': 'one', 'document_revision': 'one-revision',
                    'path': '/tmp/test-responsive.pdf', 'editing_prepared': not reading,
                    'original_pages': [0], 'issues': [], 'dirty': False,
                    'page_capabilities': {'rotate': True, 'insert_pdf': True, 'delete': True,
                                          'extract': True, 'supported': True}}
    window._active_session_v200 = 'one'
    window._session_paths_v200 = {'one': window.state['path']}
    window._refresh_actions()


@pytest.mark.parametrize('reading', [True, False])
def test_page_render_keeps_navigation_search_zoom_and_document_commands_stable(tools_window, reading):
    window = tools_window
    document_state(window, reading=reading)
    names = ('open_action', 'save_action', 'save_as_action_v300', 'save_all_action_v300',
             'print_action_v200', 'fit_width_action', 'search_action', 'zoom_in_action',
             'zoom_out_action', 'update_action_v170')
    assert all(getattr(window, name).isEnabled() for name in names)
    events = []
    for name in names:
        getattr(window, name).changed.connect(
            lambda name=name: events.append((name, getattr(window, name).isEnabled())))
    # Discard text/tooltip notifications: availability is the state under test.
    previous = {name: getattr(window, name).isEnabled() for name in names}
    transitions = []
    def collect():
        for name, enabled in events:
            if previous[name] != enabled:
                transitions.append((name, enabled))
                previous[name] = enabled
        events.clear()
    try:
        for _ in range(3):
            window.future = object()
            window._command = 'page'
            window._refresh_actions()
            collect()
            assert window.pages.isEnabled() and window.zoom_box.isEnabled()
            assert window.document_tabs_v200.isEnabled()
            assert window.search_box.isEnabled()
            window.future = None
            window._refresh_actions()
            collect()
        assert transitions == []
    finally:
        window.future = None


@pytest.mark.parametrize('command', ['save', 'apply', 'rich_prepare'])
def test_exclusive_operations_still_disable_unsafe_commands(tools_window, command):
    window = tools_window
    document_state(window)
    try:
        window.future = object()
        window._command = command
        window._refresh_actions()
        assert window._ui_mutation_locked_v310()
        assert not window.save_action.isEnabled()
        assert not window.print_action_v200.isEnabled()
        assert not window.fit_width_action.isEnabled()
        assert not window.zoom_box.isEnabled()
        assert not window.search_action.isEnabled()
    finally:
        window.future = None


def test_save_transaction_keeps_shortcuts_and_widgets_locked(tools_window):
    window = tools_window
    document_state(window)
    try:
        window._save_transaction_v300 = {'testing': True}
        window._refresh_actions()
        assert not window.centralWidget().isEnabled()
        assert not window.toolbar.isEnabled()
        assert not window.save_action.isEnabled()
        assert not window.open_action.isEnabled()
        assert not window.search_action.isEnabled()
        assert not window.zoom_in_action.isEnabled()
    finally:
        window._save_transaction_v300 = None
        window.centralWidget().setEnabled(True)
        window.toolbar.setEnabled(True)


def test_stale_canvas_cannot_edit_while_new_zoom_is_loading(tools_window):
    window = tools_window
    document_state(window)
    try:
        window.zoom = window.canvas.zoom*1.25
        window.future = object()
        window._command = 'page'
        window._refresh_actions()
        assert window.save_action.isEnabled() and window.fit_width_action.isEnabled()
        assert window.canvas.read_only
        assert not window.edit_content_action.isEnabled()
        assert not window.add_text_action.isEnabled()
        assert not window.format_action.isEnabled()
        assert not window.native_objects_action.isEnabled()
    finally:
        window.future = None


def test_save_click_during_render_is_retained_until_worker_is_idle(tools_window, monkeypatch):
    from pdfmodder.saving_ui_v300 import SavingV300Mixin
    window = tools_window
    document_state(window)
    saved = []
    monkeypatch.setattr(SavingV300Mixin, 'save_document_v300', lambda _self: saved.append('saved') or True)
    try:
        window.future = object()
        window._command = 'page'
        window._refresh_actions()
        window.save_action.trigger()
        window.save_action.trigger()
        assert not saved
        assert len(window._read_intents_v310) == 1
        window.future = None
        window._drain_read_intents_v310()
        assert saved == ['saved']
        assert not window._read_intents_v310
    finally:
        window.future = None
        window._read_intent_timer_v310.stop()
