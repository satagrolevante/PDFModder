"""Read-only rendering keeps controls stable and accepts real user commands."""
import pymupdf as fitz
import pytest

from test_saving_v300 import saving_window, change_metadata, open_editing


def long_pdf(path):
    with fitz.open() as document:
        for number in range(123):
            page = document.new_page(width=500, height=720)
            page.insert_text((30, 60), f'Pagina {number+1} contacto@example.org')
        document.save(path)
    return path


def open_reading(qtbot, window, source):
    window.reader_timer_v180.start()
    assert window.open_document(source)
    qtbot.waitUntil(lambda: window.reader.model_for_page(0) is not None
                   and not window.busy and not window._reader_queue_v180, timeout=30000)


def test_long_reading_navigation_never_flashes_global_controls(qtbot, saving_window, tmp_path):
    window = saving_window
    source = long_pdf(tmp_path/'largo.pdf')
    before = source.read_bytes()
    open_reading(qtbot, window, source)
    names = ('open_action', 'save_action', 'save_all_action_v300', 'print_action_v200',
             'fit_width_action', 'search_action', 'zoom_in_action', 'update_action_v170')
    changes = []
    for name in names:
        action = getattr(window, name)
        assert action.isEnabled()
        # QAction.changed includes legitimate tooltip changes; only enabled
        # state changes are the regression measured here.
        previous = [action.isEnabled()]
        def changed(action=action, name=name, previous=previous):
            if previous[0] != action.isEnabled():
                changes.append((name, action.isEnabled()))
                previous[0] = action.isEnabled()
        action.changed.connect(changed)
    for number in (15, 16, 35):
        window.go_page(number)
        qtbot.waitUntil(lambda: window.reader.model_for_page(number) is not None
                       and not window.busy and not window._reader_queue_v180, timeout=30000)
    assert changes == []
    assert source.read_bytes() == before


def test_save_requested_during_render_waits_and_writes_verified_copy(qtbot, saving_window, tmp_path):
    window = saving_window
    source = long_pdf(tmp_path/'original.pdf')
    original = source.read_bytes()
    open_reading(qtbot, window, source)
    window.reader_timer_v180.stop()
    target = tmp_path/'copia.pdf'
    # Start a real render, then request Save before its result can be polled.
    assert window._submit('page', {'number': 40, 'zoom': window.zoom, 'reading': True}, lambda _: None)
    assert window.busy and window._render_busy_v310()
    assert window.save_action.isEnabled()
    assert window.save_as(target)
    assert window._save_transaction_v300 is None
    assert len(window._read_intents_v310) == 1
    qtbot.waitUntil(lambda: target.is_file() and not window.busy
                   and window._save_transaction_v300 is None, timeout=30000)
    assert not window.last_error
    assert target.read_bytes() == original
    assert source.read_bytes() == original


def test_search_and_compounding_zoom_survive_page_loading(qtbot, saving_window, tmp_path):
    window = saving_window
    source = long_pdf(tmp_path/'buscar.pdf')
    open_reading(qtbot, window, source)
    start_zoom = window.zoom
    assert window._submit('page', {'number': 30, 'zoom': window.zoom, 'reading': True}, lambda _: None)
    assert window._request_search_v306('contacto@example.org')
    window.go_page(35)
    window.step_zoom_v160(1)
    window.step_zoom_v160(1)
    window.step_zoom_v160(-1)
    expected = min(4., min(4., start_zoom*1.25)*1.25)*.8
    assert window.zoom == pytest.approx(expected)
    qtbot.waitUntil(lambda: window._search_result_key_v306 is not None
                   and not window._search_pending_v306 and not window._search_running_v306
                   and not window.busy, timeout=30000)
    assert len(window._search_matches) == 123
    assert window.zoom == pytest.approx(expected)
    # Repeated F3 requests while a render occupies the worker compose from
    # the requested result index, and the final match remains selected.
    assert window._submit('page', {'number': 60, 'zoom': window.zoom, 'reading': True}, lambda _: None)
    window._next_match()
    window._next_match()
    window._previous_match_v306()
    wanted = window._search_index
    qtbot.waitUntil(lambda: not window.busy and window._search_navigation_v306 is None, timeout=30000)
    assert wanted == window._search_index == 1
    assert window.page_number == window._search_matches[wanted]['page']


def test_pending_commands_cannot_apply_to_a_new_document_revision(qtbot, saving_window, tmp_path):
    window = saving_window
    source = long_pdf(tmp_path/'vigencia.pdf')
    open_reading(qtbot, window, source)
    window.reader_timer_v180.stop()
    assert window._submit('page', {'number': 5, 'zoom': window.zoom, 'reading': True}, lambda _: None)
    called = []
    assert window._run_after_read_v310('test', lambda: called.append(True))
    revision = window.state['document_revision']
    qtbot.waitUntil(lambda: not window.busy, timeout=30000)
    window._read_intent_timer_v310.stop()
    window.state['document_revision'] = 'different'
    window._drain_read_intents_v310()
    assert not called and not window._read_intents_v310
    window.state['document_revision'] = revision


def test_repeated_undo_and_subsequent_save_follow_owned_revision_changes(qtbot, saving_window, tmp_path):
    window = saving_window
    source = long_pdf(tmp_path/'historial.pdf')
    original = source.read_bytes()
    open_editing(qtbot, window, source)
    change_metadata(qtbot, window, 'Uno')
    change_metadata(qtbot, window, 'Dos')
    assert window.state['history_index'] == 2
    target = tmp_path/'deshecho.pdf'
    assert window._submit('page', {'number': 0, 'zoom': window.zoom}, lambda _: None)
    assert window.history('undo')
    assert window.history('undo')
    assert window.save_as(target)
    qtbot.waitUntil(lambda: target.is_file() and not window.busy
                   and window._save_transaction_v300 is None
                   and not window._read_intents_v310, timeout=30000)
    assert not window.last_error
    assert window.state['history_index'] == 0
    assert target.read_bytes() == original == source.read_bytes()
