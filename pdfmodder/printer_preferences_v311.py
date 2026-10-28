"""Bounded, local printer profiles; document ranges and copies are never saved."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QLockFile


DEFAULT_PRINT_SETTINGS_V311 = {
    'color': 1, 'duplex': 0, 'collate': True, 'fit': True,
    'orientation': 0, 'paper': 1, 'dpi': 300,
}


def print_profile_v311(settings):
    """Accept only explicit application options, ignoring corrupt/unknown fields."""
    result = {}
    for key, values in {'color': (0, 1), 'duplex': (0, 1, 2, 3),
                        'orientation': (0, 1, 2), 'paper': (0, 1, 2, 3)}.items():
        value = settings.get(key)
        value = getattr(value, 'value', value)
        if type(value) is int and value in values:
            result[key] = value
    for key in ('collate', 'fit'):
        if type(settings.get(key)) is bool:
            result[key] = settings[key]
    value = settings.get('dpi')
    if type(value) is int and 72 <= value <= 600:
        result['dpi'] = value
    return result


class PrinterPreferencesV311:
    MAX_BYTES = 262144
    MAX_PRINTERS = 128

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _defaults():
        return {'schema': 1, 'enabled': True, 'printers': {}}

    def _load(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(self.MAX_BYTES + 1)
        except FileNotFoundError:
            return self._defaults()
        if len(raw) > self.MAX_BYTES:
            raise ValueError('Preferencias de impresión demasiado grandes.')
        saved = json.loads(raw)
        if (not isinstance(saved, dict) or type(saved.get('schema')) is not int
                or saved['schema'] != 1 or type(saved.get('enabled')) is not bool
                or not isinstance(saved.get('printers'), dict)):
            raise ValueError('Preferencias de impresión no válidas.')
        result = self._defaults()
        result['enabled'] = saved['enabled']
        for name, settings in list(saved['printers'].items())[-self.MAX_PRINTERS:]:
            if isinstance(name, str) and 0 < len(name) <= 512 and isinstance(settings, dict):
                result['printers'][name] = print_profile_v311(settings)
        return result

    def read(self):
        try:
            return self._load()
        except (OSError, ValueError, UnicodeError):
            return self._defaults()

    def settings_for(self, name):
        value = self.read()
        return dict(value['printers'].get(name, {})) if value['enabled'] else {}

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.path) + '.lock')
        lock.setStaleLockTime(30000)
        if not lock.tryLock(0):
            raise OSError('Las preferencias de impresión están en uso.')
        try:
            yield
        finally:
            lock.unlock()

    def _write(self, value):
        handle, name = tempfile.mkstemp(prefix='printer-', suffix='.tmp', dir=self.path.parent)
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

    def _value_for_write(self):
        try:
            return self._load()
        except (ValueError, UnicodeError):
            return self._defaults()

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise TypeError('La opción de impresión debe ser verdadera o falsa.')
        with self._locked():
            value = self._value_for_write()
            value['enabled'] = enabled
            self._write(value)

    def remember(self, name, settings):
        if not isinstance(name, str) or not 0 < len(name) <= 512:
            return
        with self._locked():
            value = self._value_for_write()
            if not value['enabled']:
                return
            # Refresh the insertion order so a bounded store retains recent printers.
            value['printers'].pop(name, None)
            value['printers'][name] = print_profile_v311(settings)
            while len(value['printers']) > self.MAX_PRINTERS:
                del value['printers'][next(iter(value['printers']))]
            self._write(value)
