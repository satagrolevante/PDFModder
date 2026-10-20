import json
from pathlib import Path
import uuid

import pytest

from pdfmodder.shell_requests_v305 import consume_shell_request, request_directory, validate_selection


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    root = request_directory()
    root.mkdir(parents=True)
    return root


def write_request(inbox, action='combine', paths=None, **changes):
    request = dict(schema=1, action=action, paths=paths or [str(inbox / 'a.pdf')])
    request.update(changes)
    path = inbox / (uuid.uuid4().hex + '.request.json')
    path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    return path


def test_complete_selection_order_unicode_and_single_use(inbox):
    paths = [str(inbox / 'Segundo ñ.pdf'), str(inbox / 'Primero con espacios.pdf')]
    path = write_request(inbox, paths=paths + paths[:1])
    assert consume_shell_request(path) == ('combine', paths)
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        consume_shell_request(path)


@pytest.mark.parametrize('payload', [b'no json', b'{}', b'\xef\xbb\xbf{}',
                                    b'{"schema":true,"action":"combine","paths":[]}'])
def test_invalid_owned_request_is_removed(inbox, payload):
    path = write_request(inbox)
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        consume_shell_request(path)
    assert not path.exists()


def test_unrelated_file_is_neither_read_nor_deleted(inbox, tmp_path):
    outside = write_request(tmp_path)
    content = outside.read_bytes()
    with pytest.raises(ValueError):
        consume_shell_request(outside)
    assert outside.read_bytes() == content
    other = inbox / 'my-document.request.json'
    other.write_bytes(b'private')
    with pytest.raises(ValueError):
        consume_shell_request(other)
    assert other.read_bytes() == b'private'


def test_request_symlink_does_not_touch_target(inbox, tmp_path):
    target = tmp_path / 'original.txt'
    target.write_bytes(b'original')
    link = inbox / (uuid.uuid4().hex + '.request.json')
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('El usuario no puede crear enlaces simbólicos.')
    with pytest.raises(ValueError):
        consume_shell_request(link)
    assert target.read_bytes() == b'original'
    assert not link.is_symlink()


def test_oversize_and_unknown_fields_are_rejected(inbox):
    path = write_request(inbox)
    with path.open('wb') as stream:
        stream.truncate(4 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match='tamaño'):
        consume_shell_request(path)
    assert not path.exists()
    path = write_request(inbox, command='arbitrary')
    with pytest.raises(ValueError, match='formato'):
        consume_shell_request(path)
    assert not path.exists()


@pytest.mark.parametrize('action,paths', [
    ('combine', ['relative.pdf']), ('combine', ['/tmp/example.docx']),
    ('convert', ['/tmp/example.pdf']), ('execute', ['/tmp/example.pdf']),
    ('convert', []), ('convert', 'not-a-list.docx'),
    ('combine', ['/tmp/file.pdf'] * 2001), ('convert', [None]),
])
def test_selection_validation(action, paths):
    with pytest.raises(ValueError):
        validate_selection(action, paths)


def test_doc_and_docx_selection_uses_no_pdf_merge(inbox):
    paths = [str(inbox / 'Legacy.DOC'), str(inbox / 'Actual.DOCX')]
    assert consume_shell_request(write_request(inbox, 'convert', paths)) == ('convert', paths)


@pytest.mark.parametrize('action,extension', [('convert', '.docx'), ('combine', '.pdf')])
def test_main_consumes_request_and_routes_after_show(inbox, monkeypatch, action, extension):
    from pdfmodder import app
    from PySide6.QtGui import QIcon
    events = []
    class Application:
        @staticmethod
        def instance(): return Application()
        def setApplicationName(self, *args): pass
        def setOrganizationName(self, *args): pass
        def setStyle(self, *args): pass
        def exec(self): return 0
    class Window:
        def __init__(self, initial):
            assert initial is None
        def show(self): events.append('show')
        def start_shell_action_v305(self, action, paths): events.append((action, paths))
    monkeypatch.setattr(app, 'QApplication', Application)
    monkeypatch.setattr(app, 'MainWindow', Window)
    monkeypatch.setattr(app, '_application_icon', lambda: QIcon())
    from types import SimpleNamespace
    monkeypatch.setattr(app, 'QTimer', SimpleNamespace(singleShot=lambda delay, callback: callback()))
    paths = [str(inbox / ('archivo con ñ' + extension))]
    request = write_request(inbox, action, paths)
    assert app.main(['--shell-request', str(request)]) == 0
    assert events == ['show', (action, paths)]
    assert not request.exists()
