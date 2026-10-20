"""Consume once the private, bounded selection handed over by Windows Explorer."""
import json
import os
from pathlib import Path
import re
import stat


MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_SELECTION = 2000
_REQUEST_NAME = re.compile(r'[0-9a-fA-F]{32}\.request\.json\Z')


def request_directory():
    local = os.environ.get('LOCALAPPDATA')
    if not local or not Path(local).is_absolute():
        raise ValueError('No se encuentra la carpeta local del usuario de Windows.')
    return Path(local) / 'PDFModder' / 'shell-requests'


def validate_selection(action, paths):
    """Keep Explorer order, with one occurrence of each absolute source path."""
    if action not in ('convert', 'combine'):
        raise ValueError('La acción del menú contextual no es válida.')
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_SELECTION:
        raise ValueError('Selecciona entre 1 y 2000 archivos cada vez.')
    extensions = {'.pdf'} if action == 'combine' else {'.doc', '.docx'}
    result, seen = [], set()
    for value in paths:
        if not isinstance(value, str) or not value or '\x00' in value or len(value) > 32767:
            raise ValueError('La selección contiene una ruta no válida.')
        path = Path(value)
        if not path.is_absolute() or path.suffix.lower() not in extensions:
            kind = 'PDF' if action == 'combine' else 'DOC o DOCX'
            raise ValueError(f'Esta acción requiere rutas completas de archivos {kind}.')
        normalized = str(path.resolve())
        key = os.path.normcase(normalized)
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def consume_shell_request(filename):
    """Never open or delete a caller-supplied file outside our private inbox."""
    path = Path(filename)
    root = request_directory()
    # Check the lexical parent as well as its resolved value. A redirected inbox
    # or request must not let a command-line argument nominate arbitrary files.
    if (not path.is_absolute() or not _REQUEST_NAME.fullmatch(path.name)
            or os.path.normcase(str(path.parent)) != os.path.normcase(str(root))
            or root.resolve() != root.absolute()):
        raise ValueError('La solicitud del menú contextual no está en su carpeta privada.')
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('La solicitud del menú contextual no es un archivo normal.')
        if info.st_size > MAX_REQUEST_BYTES:
            raise ValueError('La selección supera el tamaño permitido.')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError('La solicitud ha cambiado antes de abrirse.')
            raw = stream.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError('La selección supera el tamaño permitido.')
        try:
            request = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError) as exc:
            raise ValueError('La solicitud del menú contextual está dañada.') from exc
        if (not isinstance(request, dict) or set(request) != {'schema', 'action', 'paths'}
                or type(request['schema']) is not int or request['schema'] != 1):
            raise ValueError('El formato de la solicitud del menú contextual no es compatible.')
        return request['action'], validate_selection(request['action'], request['paths'])
    finally:
        # Malformed requests within our inbox are also single-use. Do not follow
        # a request symlink; unlinking it leaves its target intact.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
