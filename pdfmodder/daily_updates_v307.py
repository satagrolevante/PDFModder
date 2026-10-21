"""Persist the opt-out and calendar-day gate for startup update checks.

Only preferences and dates are stored here. A claim is saved before any network
work starts, so another window or restart cannot repeat the same day's check.
"""
from contextlib import contextmanager
from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QLockFile


class _InvalidPreferences(OSError):
    pass


class DailyUpdatePreferences:
    MAX_BYTES = 8192

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _defaults():
        return {'schema': 1, 'enabled': True, 'last_checked_on': None,
                'deferred_until': None}

    @staticmethod
    def _day(value):
        if type(value) is not date:
            raise TypeError('La fecha de comprobación debe ser una fecha local.')
        return value.isoformat()

    def _load(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(self.MAX_BYTES + 1)
        except FileNotFoundError:
            return self._defaults()
        try:
            if len(raw) > self.MAX_BYTES:
                raise ValueError('archivo demasiado grande')
            saved = json.loads(raw)
            if (not isinstance(saved, dict) or type(saved.get('schema')) is not int
                    or saved['schema'] != 1):
                raise ValueError('esquema desconocido')
            result = self._defaults()
            result.update({key: saved[key] for key in result if key in saved})
            if type(result['enabled']) is not bool:
                raise ValueError('opción no válida')
            for key in ('last_checked_on', 'deferred_until'):
                value = result[key]
                if value is not None and (not isinstance(value, str)
                        or date.fromisoformat(value).isoformat() != value):
                    raise ValueError('fecha no válida')
            return result
        except (ValueError, TypeError, UnicodeError) as error:
            raise _InvalidPreferences('Las preferencias de actualizaciones no son válidas.') from error

    def read(self):
        """Return usable defaults on damage; claiming still requires valid data."""
        try:
            return self._load()
        except OSError:
            return self._defaults()

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.path) + '.lock')
        lock.setStaleLockTime(30000)
        if not lock.tryLock(0):
            raise OSError('No se pudieron guardar las preferencias de actualizaciones: están en uso.')
        try:
            yield
        finally:
            lock.unlock()

    def _write(self, value):
        handle, name = tempfile.mkstemp(prefix='updates-', suffix='.tmp', dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise TypeError('La opción de actualizaciones debe ser verdadera o falsa.')
        with self._locked():
            # An explicit preference change can repair a malformed file. It
            # cannot override an actual read/permission failure silently.
            try:
                value = self._load()
            except _InvalidPreferences:
                value = self._defaults()
            value['enabled'] = enabled
            self._write(value)

    def claim_check(self, today):
        day = self._day(today)
        try:
            with self._locked():
                value = self._load()
                if (not value['enabled']
                        or (value['last_checked_on'] is not None and value['last_checked_on'] >= day)
                        or (value['deferred_until'] is not None and value['deferred_until'] > day)):
                    return False
                value.update(last_checked_on=day, deferred_until=None)
                self._write(value)
                return True
        except OSError:
            # No persistent claim means no automatic request this startup.
            return False

    def postpone(self, today):
        day = self._day(today)
        tomorrow = (today + timedelta(days=1)).isoformat()
        with self._locked():
            value = self._load()
            value['last_checked_on'] = max(value['last_checked_on'] or day, day)
            value['deferred_until'] = tomorrow
            self._write(value)
