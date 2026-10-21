"""Daily startup gating persists without making any network requests."""
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
import json
import multiprocessing
from pathlib import Path

from PySide6.QtCore import QLockFile
import pytest

from pdfmodder.daily_updates_v307 import DailyUpdatePreferences


TODAY = date(2026, 10, 21)


def _claim_in_process(path):
    return DailyUpdatePreferences(path).claim_check(TODAY)


def test_first_local_day_claim_is_saved_before_work_and_survives_restart(tmp_path):
    path = tmp_path / 'new-user' / 'updates.json'
    preferences = DailyUpdatePreferences(path)
    assert preferences.read() == {'schema': 1, 'enabled': True,
                                  'last_checked_on': None, 'deferred_until': None}
    assert preferences.claim_check(TODAY)
    # A network failure after claiming must not cause another attempt on restart.
    reopened = DailyUpdatePreferences(path)
    assert reopened.read()['last_checked_on'] == TODAY.isoformat()
    assert not reopened.claim_check(TODAY)
    assert reopened.claim_check(TODAY + timedelta(days=1))
    assert not reopened.claim_check(TODAY)  # Clock moved backwards.


def test_opt_out_is_persistent_and_toggling_preserves_calendar_fields(tmp_path):
    path = tmp_path / 'updates.json'
    preferences = DailyUpdatePreferences(path)
    preferences.set_enabled(False)
    assert DailyUpdatePreferences(path).read()['enabled'] is False
    assert not preferences.claim_check(TODAY)
    assert not preferences.claim_check(TODAY + timedelta(days=1))
    preferences.set_enabled(True)
    assert preferences.claim_check(TODAY)
    preferences.postpone(TODAY)
    before = preferences.read()
    preferences.set_enabled(False)
    preferences.set_enabled(True)
    assert preferences.read() == before
    assert not preferences.claim_check(TODAY)


def test_postponement_reaches_next_calendar_day_across_year_boundary(tmp_path):
    path = tmp_path / 'updates.json'
    end_of_year = date(2026, 12, 31)
    preferences = DailyUpdatePreferences(path)
    preferences.postpone(end_of_year)
    reopened = DailyUpdatePreferences(path)
    assert reopened.read()['deferred_until'] == '2027-01-01'
    assert not reopened.claim_check(end_of_year)
    assert reopened.claim_check(date(2027, 1, 1))
    assert reopened.read()['deferred_until'] is None


def test_future_deferral_and_future_checked_day_are_not_repeated_after_clock_change(tmp_path):
    path = tmp_path / 'updates.json'
    preferences = DailyUpdatePreferences(path)
    preferences.postpone(TODAY + timedelta(days=2))
    assert not preferences.claim_check(TODAY)
    assert not preferences.claim_check(TODAY + timedelta(days=2))
    assert preferences.claim_check(TODAY + timedelta(days=3))


def test_multiple_processes_share_one_daily_claim(tmp_path):
    path = str(tmp_path / 'updates.json')
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context('spawn')) as pool:
        results = list(pool.map(_claim_in_process, [path] * 6))
    assert results.count(True) == 1
    assert DailyUpdatePreferences(path).read()['last_checked_on'] == TODAY.isoformat()


def test_busy_preferences_do_not_block_startup_or_trigger_a_check(tmp_path):
    path = tmp_path / 'updates.json'
    lock = QLockFile(str(path) + '.lock')
    assert lock.tryLock(0)
    try:
        preferences = DailyUpdatePreferences(path)
        assert not preferences.claim_check(TODAY)
        with pytest.raises(OSError, match='están en uso'):
            preferences.set_enabled(False)
    finally:
        lock.unlock()
    assert preferences.claim_check(TODAY)


@pytest.mark.parametrize('raw', [
    b'{broken json', b'\xff', b'[]', b'{"schema":true}', b'{"schema":2}',
    b'{"schema":1,"enabled":"false"}',
    b'{"schema":1,"last_checked_on":"20261021"}',
    b'{"schema":1,"deferred_until":"2026-02-30"}',
    b'{"schema":1,"deferred_until":123}', b'x' * 8193,
])
def test_invalid_preferences_skip_network_and_can_be_repaired_explicitly(tmp_path, raw):
    path = tmp_path / 'updates.json'
    path.write_bytes(raw)
    preferences = DailyUpdatePreferences(path)
    assert preferences.read()['enabled'] is True
    assert not preferences.claim_check(TODAY)
    assert path.read_bytes() == raw
    preferences.set_enabled(False)
    assert DailyUpdatePreferences(path).read()['enabled'] is False
    assert not preferences.claim_check(TODAY)


def test_read_or_write_failures_cannot_claim_or_erase_existing_preferences(tmp_path, monkeypatch):
    path = tmp_path / 'updates.json'
    preferences = DailyUpdatePreferences(path)
    preferences.set_enabled(False)
    original = path.read_bytes()
    real_open = Path.open

    def inaccessible(self, *args, **kwargs):
        if self == path:
            raise PermissionError('Synthetic read denial')
        return real_open(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', inaccessible)
        assert preferences.read()['enabled'] is True
        assert not preferences.claim_check(TODAY)
        with pytest.raises(OSError):
            preferences.set_enabled(True)
    assert path.read_bytes() == original

    def cannot_replace(*_args, **_kwargs):
        raise PermissionError('Synthetic write denial')

    monkeypatch.setattr(Path, 'replace', cannot_replace)
    with pytest.raises(OSError):
        preferences.set_enabled(True)
    assert path.read_bytes() == original
    assert list(tmp_path.glob('updates-*.tmp')) == []


def test_failed_first_claim_is_not_recorded_and_can_succeed_later(tmp_path, monkeypatch):
    preferences = DailyUpdatePreferences(tmp_path / 'updates.json')

    def failed_write(_value):
        raise OSError('Synthetic full disk')

    with monkeypatch.context() as patch:
        patch.setattr(preferences, '_write', failed_write)
        assert not preferences.claim_check(TODAY)
        assert not preferences.path.exists()
    assert preferences.claim_check(TODAY)
    assert json.loads(preferences.path.read_text())['last_checked_on'] == TODAY.isoformat()
