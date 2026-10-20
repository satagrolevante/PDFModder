"""Local conversion preserves originals, completed output and process ownership."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import zipfile

import pymupdf as fitz
import pytest

from pdfmodder import office_conversion_v305 as office
from pdfmodder.draft_control_v305 import DraftCancelled


def make_docx(path):
    document = '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>Informe de conversión</w:t></w:r></w:p>
<w:p><w:r><w:t>Información: revisión, año y acción. Correo: prueba@example.org.</w:t></w:r></w:p>
<w:tbl><w:tblPr><w:tblW w:w="6000" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="3000"/><w:gridCol w:w="3000"/></w:tblGrid>
<w:tr><w:tc><w:p><w:r><w:t>Parámetro</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Resultado</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>Temperatura</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>23 °C</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:t>Segunda página: comprobación final.</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
</w:body></w:document>'''
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as package:
        package.writestr('[Content_Types].xml', '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>''')
        package.writestr('_rels/.rels', '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''')
        package.writestr('word/document.xml', document)
    return path


def make_pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), 'Verified output')
        document.save(path)


@pytest.fixture
def source(tmp_path):
    return make_docx(tmp_path / "revisión ' $() ` Ω.docx")


@pytest.fixture
def renderer(monkeypatch):
    calls = []
    backend = {'id': 'libreoffice', 'name': 'LibreOffice', 'executable': '/mock/soffice'}
    monkeypatch.setattr(office, 'available_backends', lambda: [backend])

    def render(source, output, chosen, folder, timeout, cancel):
        calls.append((source, output, chosen, folder))
        assert source.parent == folder
        assert source.is_file()
        make_pdf(output)

    monkeypatch.setattr(office, '_convert_libreoffice', render)
    return calls


def test_discovery_prefers_word_and_does_not_install_anything(monkeypatch):
    monkeypatch.setattr(office, '_powershell', lambda: r'C:\Windows\powershell.exe')
    monkeypatch.setattr(office, '_word_registered', lambda: True)
    monkeypatch.setattr(office, '_libreoffice', lambda: r'C:\LibreOffice\soffice.com')
    assert [item['id'] for item in office.available_backends()] == ['word', 'libreoffice']
    monkeypatch.setattr(office, '_word_registered', lambda: False)
    assert [item['id'] for item in office.available_backends()] == ['libreoffice']


def test_missing_renderer_has_actionable_message_and_preserves_source(source, monkeypatch):
    before = source.read_bytes()
    monkeypatch.setattr(office, 'available_backends', lambda: [])
    with pytest.raises(office.ConversionError, match='instala Microsoft Word o LibreOffice'):
        office.convert_document_to_pdf(source)
    assert source.read_bytes() == before
    assert not source.with_suffix('.pdf').exists()


@pytest.mark.parametrize(('name', 'payload'), [
    ('unknown.doc', b'<!doctype html><script>not Word</script>'),
    ('unknown.docx', b'not a ZIP document'),
    ('encrypted.docx', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1more data'),
    ('renamed.pdf', b'%PDF-1.7\n'),
])
def test_invalid_source_rejected_before_renderer(tmp_path, monkeypatch, name, payload):
    source = tmp_path / name
    source.write_bytes(payload)
    monkeypatch.setattr(office, 'available_backends', lambda: pytest.fail('unexpected discovery'))
    with pytest.raises(office.ConversionError):
        office.convert_document_to_pdf(source)
    assert source.read_bytes() == payload


def test_zip_without_word_document_is_not_docx(tmp_path):
    path = tmp_path / 'fake.docx'
    with zipfile.ZipFile(path, 'w') as package:
        package.writestr('[Content_Types].xml', '<Types/>')
        package.writestr('untrusted.sh', 'echo unrelated')
    with pytest.raises(office.ConversionError, match='DOCX reconocible'):
        office.convert_document_to_pdf(path)


def test_success_preserves_unicode_name_original_and_reports_exact_bytes(source, renderer):
    before = source.read_bytes()
    report = office.convert_document_to_pdf(source)
    saved = Path(report['path'])
    assert saved == source.with_suffix('.pdf')
    assert report['pages'] == 1
    assert report['backend'] == 'libreoffice'
    assert report['sha256'] == hashlib.sha256(saved.read_bytes()).hexdigest()
    assert report['size'] == saved.stat().st_size
    assert report['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert report['source_unchanged']
    assert source.read_bytes() == before
    assert renderer[0][0].name == source.name
    assert not renderer[0][3].exists()
    assert not list(source.parent.glob('.pdfmodder-convert-*'))


def test_automatic_suffix_preserves_existing_outputs(source, renderer):
    first = source.with_suffix('.pdf')
    second = first.with_name(f'{first.stem} (1).pdf')
    first.write_bytes(b'existing first')
    second.write_bytes(b'existing second')
    report = office.convert_document_to_pdf(source)
    assert Path(report['path']).name == f'{first.stem} (2).pdf'
    assert first.read_bytes() == b'existing first'
    assert second.read_bytes() == b'existing second'


def test_explicit_destination_refuses_existing_or_dangling_link(source, renderer, tmp_path):
    destination = tmp_path / 'chosen.pdf'
    destination.write_bytes(b'keep')
    with pytest.raises(office.ConversionError, match='Ya existe'):
        office.convert_document_to_pdf(source, destination)
    assert destination.read_bytes() == b'keep'
    assert not renderer
    if os.name != 'nt':
        destination.unlink()
        destination.symlink_to(tmp_path / 'missing.pdf')
        with pytest.raises(office.ConversionError, match='Ya existe'):
            office.convert_document_to_pdf(source, destination)
        assert destination.is_symlink()
        assert not (tmp_path / 'missing.pdf').exists()


def test_destination_created_during_conversion_is_never_overwritten(source, renderer, monkeypatch):
    destination = source.with_suffix('.pdf')
    original = office._convert_libreoffice

    def racing_renderer(*args):
        original(*args)
        destination.write_bytes(b'created concurrently')

    monkeypatch.setattr(office, '_convert_libreoffice', racing_renderer)
    with pytest.raises(office.ConversionError, match='Ya existe'):
        office.convert_document_to_pdf(source, destination)
    assert destination.read_bytes() == b'created concurrently'
    assert not list(source.parent.glob('.pdfmodder-convert-*'))


@pytest.mark.parametrize('payload', [b'', b'not PDF', b'%PDF-1.7\nincomplete'])
def test_incomplete_render_never_published(source, renderer, monkeypatch, payload):
    def invalid_render(staged, output, *args):
        output.write_bytes(payload)

    monkeypatch.setattr(office, '_convert_libreoffice', invalid_render)
    with pytest.raises(office.ConversionError, match='completo y verificable'):
        office.convert_document_to_pdf(source)
    assert not source.with_suffix('.pdf').exists()


def test_source_changed_by_other_program_during_conversion_is_not_published(source, renderer, monkeypatch):
    original = office._convert_libreoffice

    def mutate_source(*args):
        original(*args)
        source.write_bytes(b'external edit')

    monkeypatch.setattr(office, '_convert_libreoffice', mutate_source)
    with pytest.raises(office.ConversionError, match='cambió durante'):
        office.convert_document_to_pdf(source)
    assert source.read_bytes() == b'external edit'
    assert not source.with_suffix('.pdf').exists()


@pytest.mark.parametrize('timeout', [0, -1, 3601, True, float('nan')])
def test_invalid_timeout_rejected(source, renderer, timeout):
    with pytest.raises(office.ConversionError, match='tiempo máximo'):
        office.convert_document_to_pdf(source, timeout=timeout)
    assert not renderer


def test_unknown_backend_rejected(source, renderer):
    with pytest.raises(office.ConversionError, match='no es compatible'):
        office.convert_document_to_pdf(source, backend='download-online')
    assert not renderer


def test_cancel_before_conversion_and_parent_checkpoint_propagate(source, renderer):
    event = threading.Event()
    event.set()
    with pytest.raises(office.ConversionCancelled):
        office.convert_document_to_pdf(source, cancel=event)

    def checkpoint():
        raise DraftCancelled('stale job')

    with pytest.raises(DraftCancelled, match='stale job'):
        office.convert_document_to_pdf(source, cancel=checkpoint)
    assert not renderer


@pytest.mark.parametrize('mode', ['timeout', 'cancel'])
def test_timeout_and_cancellation_reap_only_owned_renderer(tmp_path, monkeypatch, mode):
    real_popen = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(office.subprocess, 'Popen', capture)
    started = time.monotonic()
    cancel = (lambda: time.monotonic() - started > .12) if mode == 'cancel' else None
    exception = office.ConversionCancelled if mode == 'cancel' else office.ConversionError
    with pytest.raises(exception):
        office._run([sys.executable, '-c', 'import time; time.sleep(20)'],
                    env=os.environ.copy(), timeout=.12 if mode == 'timeout' else 10,
                    cancel=cancel)
    assert children[0].poll() is not None
    assert time.monotonic() - started < 8
    assert os.getpid() != children[0].pid


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process-group ownership')
def test_cancel_also_stops_renderer_child_that_ignores_termination(tmp_path):
    import fcntl
    lock = tmp_path / 'renderer.lock'
    ready = tmp_path / 'child-ready'
    child = """import fcntl, pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(sys.argv[1], 'w') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    pathlib.Path(sys.argv[2]).write_text('ready')
    time.sleep(20)
"""
    parent = 'import subprocess, sys, time; subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2], sys.argv[3]]); time.sleep(20)'
    with pytest.raises(office.ConversionCancelled):
        office._run([sys.executable, '-c', parent, child, str(lock), str(ready)],
                    env=os.environ.copy(), timeout=5, cancel=ready.exists)
    assert ready.is_file()
    # The child cannot still hold the lock after the parent has been reaped.
    with lock.open('r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_renderer_failure_does_not_expose_document_data_or_switch_engine(source, renderer, monkeypatch):
    monkeypatch.setattr(office, 'available_backends', lambda: [
        {'id': 'word', 'name': 'Microsoft Word', 'executable': 'powershell'},
        {'id': 'libreoffice', 'name': 'LibreOffice', 'executable': 'soffice'},
    ])

    def fail(*args):
        office._run([sys.executable, '-c', "import sys; print('PRIVATE DOCUMENT CONTENT'); sys.exit(1)"],
                    env=os.environ.copy(), timeout=5, cancel=None)

    monkeypatch.setattr(office, '_convert_word', fail)
    with pytest.raises(office.ConversionError) as raised:
        office.convert_document_to_pdf(source)
    assert 'PRIVATE' not in str(raised.value)
    assert not renderer
    assert not source.with_suffix('.pdf').exists()


def test_word_uses_static_encoded_script_and_scoped_cleanup(source, tmp_path, monkeypatch):
    calls = []

    def run(command, *, env, timeout, cancel):
        calls.append((command, env, timeout))
        Path(env['PDFMODDER_OFFICE_PID']).write_text('{"pid":123,"started":"456"}')

    cleanup = []
    monkeypatch.setattr(office, '_run', run)
    monkeypatch.setattr(office.subprocess, 'run', lambda command, **kwargs: cleanup.append((command, kwargs)))
    output = tmp_path / "destino ' ` $().pdf"
    office._convert_word(source, output, {'executable': 'powershell.exe'}, tmp_path, 30, None)
    command, env, timeout = calls[0]
    assert command[1:5] == ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand']
    decoded = base64.b64decode(command[-1]).decode('utf-16le')
    assert str(source) not in decoded and str(output) not in decoded
    assert env['PDFMODDER_OFFICE_SOURCE'] == str(source)
    assert env['PDFMODDER_OFFICE_OUTPUT'] == str(output)
    assert '$word.AutomationSecurity = 3' in decoded
    assert '$word.Options.UpdateLinksAtOpen = $false' in decoded
    assert '$existing -contains [int]$wordPid' in decoded
    assert 'if ($owned)' in decoded
    assert '$word.Documents.Open($env:PDFMODDER_OFFICE_SOURCE, $false, $true,' in decoded
    cleanup_script = base64.b64decode(cleanup[0][0][-1]).decode('utf-16le')
    assert "ProcessName -ieq 'WINWORD'" in cleanup_script
    assert 'Ticks.ToString() -eq [string]$identity.started' in cleanup_script
    assert cleanup[0][1]['timeout'] == 10


def test_libreoffice_uses_private_profile_and_separate_path_arguments(source, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(office, '_run', lambda command, **kwargs: calls.append((command, kwargs)))
    folder = tmp_path / 'perfil aislado Ω'
    folder.mkdir()
    office._convert_libreoffice(source, folder / 'result.pdf', {'executable': 'soffice'}, folder, 30, None)
    command, options = calls[0]
    assert command[1] == '-env:UserInstallation=' + (folder / 'profile').as_uri()
    assert command[-1] == str(source)
    assert command[-3:-1] == ['--outdir', str(folder)]
    assert '--headless' in command
    assert 'MacroSecurityLevel' in (folder / 'profile/user/registrymodifications.xcu').read_text()


def test_real_libreoffice_docx_and_binary_doc_preserve_two_pages_table_and_unicode(tmp_path):
    executable = office._libreoffice()
    if executable is None:
        pytest.skip('LibreOffice is not installed')
    docx = make_docx(tmp_path / 'Informe revisión.docx')
    outputs = tmp_path / 'salidas'
    outputs.mkdir()
    original = docx.read_bytes()
    report_docx = office.convert_document_to_pdf(docx, outputs / 'docx.pdf', backend='libreoffice', timeout=45)

    # Generate a genuine Word97 compound document locally, rather than merely
    # renaming RTF. The same renderer then exercises the legacy import path.
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    office._run([executable, '-env:UserInstallation=' + (tmp_path / 'legacy-profile').as_uri(),
                 '--headless', '--nologo', '--nodefault', '--nofirststartwizard', '--norestore',
                 '--convert-to', 'doc:MS Word 97', '--outdir', str(legacy), str(docx)],
                env=os.environ.copy(), timeout=45, cancel=None)
    doc = legacy / 'Informe revisión.doc'
    original_doc = doc.read_bytes()
    assert original_doc.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
    report_doc = office.convert_document_to_pdf(doc, outputs / 'doc.pdf', backend='libreoffice', timeout=45)
    assert docx.read_bytes() == original
    assert doc.read_bytes() == original_doc
    for report in (report_docx, report_doc):
        assert report['pages'] == 2
        with fitz.open(report['path']) as pdf:
            text = '\n'.join(page.get_text() for page in pdf)
            assert 'Informe de conversión' in text
            assert 'Información' in text
            assert 'prueba@example.org' in text
            assert 'Parámetro' in text and 'Resultado' in text
            assert '23 °C' in text
            assert 'Segunda página' in pdf[1].get_text()
