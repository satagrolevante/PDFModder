"""Search from the real window keeps counters, navigation and revision scope coherent."""
from concurrent.futures import Future
from pathlib import Path

import pymupdf as fitz
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from pdfmodder.app import MainWindow


def make_search_pdf(path, one=False):
    with fitz.open() as document:
        page = document.new_page(width=500, height=1200)
        page.insert_text((45, 100), 'mail@example.org primer resultado', fontsize=12)
        if not one:
            page.insert_text((45, 1020), 'Otro mail@example.org segundo resultado', fontsize=12)
            page = document.new_page(width=500, height=1200)
            page.insert_text((45, 1050), 'mail@example.org tercer resultado', fontsize=12)
        document.save(path)
    return str(path)


@pytest.fixture
def search_window(qtbot, tmp_path):
    source = make_search_pdf(tmp_path / 'buscar.pdf')
    original = Path(source).read_bytes()
    history = tmp_path / 'history'
    history.mkdir()
    window = MainWindow(config_path=tmp_path / 'fonts.json', history_dir=history)
    qtbot.addWidget(window, before_close_func=lambda widget: setattr(widget, '_allow_close', True))
    window.resize(1100, 720)
    window.show()
    window.thumbnail_timer.stop()
    assert window.open_document(source)
    qtbot.waitUntil(lambda: bool(window.state) and not window.busy
                   and window.reader.model_for_page(0) is not None, timeout=30000)
    yield window
    assert Path(source).read_bytes() == original
    window._allow_close = True
    window.close()


def search(qtbot, window, text):
    window.search_box.setText(text)
    assert window.search()
    qtbot.waitUntil(lambda: window._search_result_key_v306 is not None
                   and window._search_result_key_v306[1] == text
                   and window._search_running_v306 is None
                   and window._search_pending_v306 is None, timeout=30000)


def settled(qtbot, window):
    qtbot.waitUntil(lambda: not window.busy and window._search_navigation_v306 is None,
                   timeout=30000)


def result_visible(window, index):
    match = window._search_matches[index]
    if window.reader._pending_reveal is not None:
        return False
    model = window.reader.model_for_page(match['page'])
    if model is None:
        return False
    rect = match.get('rects', [match['rect']])[0]
    page = window.reader._rects[match['page']]
    point = window.reader.mapFromScene(QPointF(
        page.left() + (rect[0] + rect[2]) * window.reader.zoom / 2,
        page.top() + (rect[1] + rect[3]) * window.reader.zoom / 2))
    return window.reader.viewport().rect().contains(point)


def test_real_results_count_context_click_and_exact_scroll(search_window, qtbot):
    window = search_window
    revision = window.state['document_revision']
    search(qtbot, window, 'mail@example.org')
    panel = window.search_panel_v306
    assert window.search_dock_v306.isVisible()
    assert panel.model.rowCount() == 3
    assert panel.count_label.text() == 'Resultado 1 de 3'
    assert all('mail@example.org' in match['context'] for match in window._search_matches)
    assert 'tercer resultado' in panel.model.data(panel.model.index(2))
    index = panel.model.index(2)
    panel.results_view.scrollTo(index)
    QApplication.processEvents()
    qtbot.mouseClick(panel.results_view.viewport(), Qt.LeftButton,
                     pos=panel.results_view.visualRect(index).center())
    qtbot.waitUntil(lambda: window._search_index == 2 and result_visible(window, 2), timeout=30000)
    assert window.page_number == 1
    assert panel.count_label.text() == 'Resultado 3 de 3'
    assert window.reader._active_search_index == 2
    assert window.state['document_revision'] == revision
    assert not window.state.get('dirty') and not window.state.get('preview')


def test_arrows_and_f3_navigate_both_directions_without_research(search_window, qtbot, monkeypatch):
    window = search_window
    requests = []
    submit = window._submit
    def record(command, payload=None, callback=None):
        if command == 'search':
            requests.append(payload)
        return submit(command, payload, callback)
    monkeypatch.setattr(window, '_submit', record)
    search(qtbot, window, 'mail@example.org')
    qtbot.mouseClick(window.search_panel_v306.next_button, Qt.LeftButton)
    assert window._search_index == 1
    window.search_panel_v306.query.setFocus()
    qtbot.keyClick(window.search_panel_v306.query, Qt.Key_F3)
    assert window._search_index == 2
    qtbot.keyClick(window.search_panel_v306.query, Qt.Key_F3, Qt.ShiftModifier)
    assert window._search_index == 1
    qtbot.mouseClick(window.search_panel_v306.previous_button, Qt.LeftButton)
    assert window._search_index == 0
    qtbot.mouseClick(window.search_panel_v306.previous_button, Qt.LeftButton)
    assert window._search_index == 2
    assert len(requests) == 1


def test_zero_and_empty_search_clear_results_and_do_not_repeat_known_query(search_window, qtbot, monkeypatch):
    window = search_window
    requests = []
    submit = window._submit
    def record(command, payload=None, callback=None):
        if command == 'search':
            requests.append(payload)
        return submit(command, payload, callback)
    monkeypatch.setattr(window, '_submit', record)
    search(qtbot, window, 'absent literal')
    assert window.search_panel_v306.count_label.text() == 'Sin resultados'
    assert not window._search_matches
    assert window.search()
    window._next_match()
    assert len(requests) == 1
    window.search_box.clear()
    assert not window.search()
    assert window.search_panel_v306.model.rowCount() == 0
    assert not window.reader._search_matches
    assert not window.canvas.search_rects and not window.canvas.active_search_rects


@pytest.mark.parametrize('narrow', [False, True])
def test_editing_same_page_next_scrolls_without_reloading_page(search_window, qtbot, monkeypatch, narrow):
    window = search_window
    settled(qtbot, window)
    window._tools_mode_v171(True)
    qtbot.waitUntil(lambda: window.application_mode == 'editing' and not window.busy
                   and window.model is not None, timeout=30000)
    if narrow:
        window.canvas.setFixedWidth(60)
    search(qtbot, window, 'mail@example.org')
    settled(qtbot, window)
    loads = []
    load_page = window.load_page
    def record():
        loads.append(window.page_number)
        return load_page()
    monkeypatch.setattr(window, 'load_page', record)
    assert window._select_search_match_v306(1)
    settled(qtbot, window)
    assert loads == []
    assert window.page_number == 0
    assert window.canvas.active_search_rects == window._search_matches[1]['rects']
    match = window._search_matches[1]['rect']
    point = window.canvas.mapFromScene(window.canvas.scene_rect(match).center())
    assert window.canvas.viewport().rect().contains(point)
    assert not window.state.get('dirty')


@pytest.mark.parametrize('change', ['query', 'clear', 'close', 'revision', 'original'])
def test_obsolete_search_error_cannot_replace_current_ui(search_window, qtbot, monkeypatch, change):
    window = search_window
    settled(qtbot, window)
    window.reader_timer_v180.stop()
    pending = Future()
    original_submit = window.pool.submit
    def intercept(function, command, payload):
        return pending if command == 'search' else original_submit(function, command, payload)
    monkeypatch.setattr(window.pool, 'submit', intercept)
    window.search_box.setText('mail@example.org')
    assert window.search()
    assert window.busy and window._command == 'search'
    if change == 'query':
        window.search_panel_v306.query.setText('different query')
    elif change == 'clear':
        window.search_box.clear()
    elif change == 'close':
        window.search_dock_v306.hide()
    elif change == 'revision':
        window.state = dict(window.state, document_revision='different revision')
        window._refresh_actions()
    else:
        previous = window.compare_action.blockSignals(True)
        window.compare_action.setChecked(True)
        window.compare_action.blockSignals(previous)
        window._refresh_actions()
    pending.set_exception(RuntimeError('Obsolete search error must never be displayed'))
    window._poll()
    assert not window.busy
    assert window.last_error == ''
    assert window.search_panel_v306.model.rowCount() == 0
    assert not window.reader._search_matches
    assert not window.canvas.active_search_rects


def test_opening_and_switching_tabs_clear_old_search_scope(search_window, qtbot, tmp_path):
    window = search_window
    search(qtbot, window, 'mail@example.org')
    settled(qtbot, window)
    first = window._active_session_v200
    other = make_search_pdf(tmp_path / 'otro.pdf', one=True)
    assert window.open_document(other)
    qtbot.waitUntil(lambda: window._active_session_v200 != first and not window.busy, timeout=30000)
    assert not window._search_matches
    assert window.search_panel_v306.model.rowCount() == 0
    search(qtbot, window, 'mail@example.org')
    assert len(window._search_matches) == 1
    settled(qtbot, window)
    window._switch_tab_v200(0)
    qtbot.waitUntil(lambda: window._active_session_v200 == first and not window.busy, timeout=30000)
    assert not window._search_matches
    assert window.search_panel_v306.model.rowCount() == 0
    assert not window.reader._search_matches
    # Tab restoration deliberately schedules its scroll update 200 ms later.
    # Let that visible navigation complete before Qt deletes this window.
    qtbot.wait(220)


def test_only_latest_pending_query_runs_after_obsolete_job(search_window, qtbot, monkeypatch):
    window = search_window
    settled(qtbot, window)
    obsolete = Future()
    original_submit = window.pool.submit
    calls = []

    def intercept(function, command, payload):
        if command == 'search':
            calls.append(payload['text'])
            if len(calls) == 1:
                return obsolete
        return original_submit(function, command, payload)

    monkeypatch.setattr(window.pool, 'submit', intercept)
    window.search_box.setText('obsolete query')
    assert window.search()
    assert calls == ['obsolete query']
    window.search_panel_v306.query.setText('mail@example.org')
    window.search_panel_v306.find_button.click()
    window.search_panel_v306.query.setText('tercer resultado')
    window.search_panel_v306.find_button.click()
    assert window.busy
    assert calls == ['obsolete query']
    obsolete.set_exception(RuntimeError('Obsolete work must not report an error'))
    qtbot.waitUntil(lambda: window._search_result_key_v306 is not None
                   and window._search_result_key_v306[1] == 'tercer resultado', timeout=30000)
    assert calls == ['obsolete query', 'tercer resultado']
    assert window.search_panel_v306.count_label.text() == 'Resultado 1 de 1'
    assert len(window._search_matches) == 1 and window._search_matches[0]['page'] == 1
    assert not window.last_error


def test_case_option_reaches_real_search_worker(search_window, qtbot):
    window = search_window
    search(qtbot, window, 'MAIL@EXAMPLE.ORG')
    assert len(window._search_matches) == 3
    panel = window.search_panel_v306
    panel.case_box.setChecked(True)
    qtbot.keyClick(panel.query, Qt.Key_Return)
    qtbot.waitUntil(lambda: window._search_result_key_v306 is not None
                   and window._search_result_key_v306[2]
                   and window._search_running_v306 is None, timeout=30000)
    assert panel.count_label.text() == 'Sin resultados'
    assert not window._search_matches
