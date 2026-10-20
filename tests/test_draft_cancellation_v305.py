"""Superseded validation stops safely in the real serial PDF process."""
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import multiprocessing
from pathlib import Path
import time

import pytest

from pdfmodder.draft_control_v305 import (
    DraftCancelled, DraftControl, checkpoint, controlled_draft,
)
from pdfmodder.worker import dispatch
from test_richtext_v09 import document, request


def _slow_preview(request_value, ticket, marker):
    """Compute real validated bytes, then expose a cancellable publication gap."""
    import pdfmodder.richtext as richtext
    original = richtext.edit_rich_pdf
    def edit(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(marker).write_text('validated', encoding='ascii')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            checkpoint()
            time.sleep(.01)
        raise AssertionError('The obsolete validation was not cancelled.')
    richtext.edit_rich_pdf = edit
    try:
        return dispatch('rich_prepare', {
            'request': request_value, '_draft_control_v305': ticket,
        })
    finally:
        richtext.edit_rich_pdf = original


def _private_worker_state():
    import pdfmodder.worker as worker
    session = worker._session
    return {
        'revision': session.history.revision, 'index': session.history.index,
        'states': len(session.history.states), 'pending': session.pending is not None,
        'prepared': getattr(session, '_prepared_rich', None) is not None,
        'validated': getattr(session, '_validated_rich', None) is not None,
        'metadata': deepcopy(session.history.metadata),
    }


def test_ticket_supersession_context_reset_and_channel_close():
    channel = DraftControl()
    try:
        ticket = channel.ticket()
        with controlled_draft(ticket):
            checkpoint()
        channel.invalidate()
        with pytest.raises(DraftCancelled):
            with controlled_draft(ticket):
                pytest.fail('An obsolete job must not begin.')
        checkpoint()  # No cancellation escapes its job context.
        fresh = channel.ticket()
        with controlled_draft(fresh):
            checkpoint()
        path = Path(fresh['path'])
        channel.close()
        assert not path.parent.exists()
        with pytest.raises(DraftCancelled):
            with controlled_draft(fresh):
                pass
        checkpoint()
    finally:
        channel.close()


def test_channel_is_bounded_and_crashed_owner_cleanup_resets_context(monkeypatch):
    import pdfmodder.draft_control_v305 as control_module
    channel = DraftControl()
    try:
        for _ in range(100):
            ticket = channel.ticket()
        assert len(list(channel._directory.iterdir())) == 1
        with pytest.raises(DraftCancelled):
            with controlled_draft(dict(ticket, nonce='0' * 32)):
                pass
        class DeadParent:
            def is_alive(self):
                return False
        monkeypatch.setattr(control_module.multiprocessing, 'parent_process', lambda: DeadParent())
        with pytest.raises(DraftCancelled):
            with controlled_draft(ticket):
                pass
        assert not channel._directory.exists()
        checkpoint()
    finally:
        channel.close()


def test_real_spawn_cancel_never_publishes_cache_history_or_prepared_token(tmp_path):
    path = tmp_path / 'source.pdf'
    data = document()
    path.write_bytes(data)
    req = request(data)
    req.runs[0]['text'] = 'Hola nuevo'
    channel = DraftControl()
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        try:
            pool.submit(dispatch, 'open', {
                'path': str(path), 'config_path': str(tmp_path / 'fonts.json'),
                'history_dir': str(tmp_path / 'history'),
            }).result(timeout=30)
            before = pool.submit(_private_worker_state).result(timeout=10)
            marker = tmp_path / 'validated'
            future = pool.submit(_slow_preview, req, channel.ticket(), str(marker))
            deadline = time.monotonic() + 30
            while not marker.exists() and not future.done() and time.monotonic() < deadline:
                time.sleep(.01)
            assert marker.exists(), future.result(timeout=1) if future.done() else 'validation did not start'
            channel.invalidate()
            assert future.result(timeout=5) == {'draft_cancelled_v305': True}
            assert pool.submit(_private_worker_state).result(timeout=10) == before
            # The same process remains healthy, validates the latest draft, and
            # a commit ignores cancellation tickets: acceptance is atomic.
            prepared = pool.submit(dispatch, 'rich_prepare', {
                'request': req, '_draft_control_v305': channel.ticket(),
            }).result(timeout=30)
            assert prepared['report']['verified']
            stale = channel.ticket()
            channel.invalidate()
            result = pool.submit(dispatch, 'rich_commit', {
                'token': prepared['token'], '_draft_control_v305': stale,
            }).result(timeout=30)
            assert result['state']['history_index'] == 1
            assert path.read_bytes() == data
        finally:
            pool.submit(dispatch, 'close_all', {}).result(timeout=10)
            channel.close()


# Reuse the existing real-window fixture and navigation helpers, not a mocked
# scheduler: this covers the Qt timers and Windows-spawn worker handoff.
from test_rich_ui_v09 import window, idle, select
from PySide6.QtGui import QTextCursor


def _replace_day(editor, value):
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(2, QTextCursor.KeepAnchor)
    cursor.insertText(value)


def test_latest_draft_wins_and_accepting_same_preview_does_not_cancel_it(qtbot, window):
    select(window, '10/09/2026')
    window.start_edit()
    qtbot.waitUntil(lambda: window.canvas.editor.isVisible(), timeout=30000)
    editor = window.canvas.editor
    _replace_day(editor, '12')
    window._rich_timer.stop()
    window._rich_pump()
    assert window.busy and window._command == 'rich_preview'
    assert window._draft_submission_v305 is not None
    obsolete = window._draft_control_v305._path
    _replace_day(editor, '13')
    assert not obsolete.exists()
    editor.accept_draft()
    idle(qtbot, window)
    assert not window.last_error
    assert window.state['history_index'] == 1
    assert '13/09/2026' in ''.join(g.text for g in window.model.glyphs)
    window.history('undo')
    idle(qtbot, window)
    select(window, '10/09/2026')
    window.start_edit()
    qtbot.waitUntil(lambda: window.canvas.editor.isVisible(), timeout=30000)
    _replace_day(editor, '14')
    window._rich_timer.stop()
    window._rich_pump()
    ticket = window._draft_control_v305._path
    editor.accept_draft()
    assert window._draft_control_v305._path == ticket and ticket.exists()
    idle(qtbot, window)
    assert not window.last_error
    assert window.state['history_index'] == 1
    assert '14/09/2026' in ''.join(g.text for g in window.model.glyphs)
