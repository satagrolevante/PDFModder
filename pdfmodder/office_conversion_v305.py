"""Local Word-document conversion through an installed document renderer.

Word and LibreOffice own pagination, fonts, images and tables. This module never
substitutes a text-only PDF for a document. Inputs remain untouched and a result
is published only after both PDF parsers accept the complete temporary output.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile

from .model import EditError


class ConversionError(EditError):
    pass


class ConversionCancelled(ConversionError):
    pass


def _is_windows():
    return sys.platform == 'win32'


def _powershell():
    if not _is_windows():
        return None
    root = os.environ.get('SystemRoot', r'C:\Windows')
    executable = Path(root) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return str(executable) if executable.is_file() else shutil.which('powershell.exe')


def _word_registered():
    if not _is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'Word.Application\CLSID') as key:
            clsid, _ = winreg.QueryValueEx(key, '')
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf'CLSID\{clsid}\LocalServer32') as key:
            command, _ = winreg.QueryValueEx(key, '')
        return bool(command)
    except (OSError, ImportError):
        return False


def _libreoffice():
    candidates = [shutil.which('soffice'), shutil.which('libreoffice')]
    if _is_windows():
        for variable in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
            if os.environ.get(variable):
                candidates.append(str(Path(os.environ[variable]) / 'LibreOffice/program/soffice.exe'))
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe',
                                            0, winreg.KEY_READ | view) as key:
                            candidates.append(winreg.QueryValueEx(key, '')[0])
                    except OSError:
                        pass
        except ImportError:
            pass
    elif sys.platform == 'darwin':
        candidates.append('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            path = Path(candidate).resolve()
            # The console launcher waits for conversion; the GUI launcher can
            # return early on Windows. Both belong to the same installation.
            console = path.with_suffix('.com')
            if _is_windows() and console.is_file():
                path = console
            return str(path)
    return None


def available_backends():
    """Return renderers that are already installed, in preferred order."""
    found = []
    shell = _powershell()
    if shell and _word_registered():
        found.append({'id': 'word', 'name': 'Microsoft Word', 'executable': shell})
    libreoffice = _libreoffice()
    if libreoffice:
        found.append({'id': 'libreoffice', 'name': 'LibreOffice', 'executable': libreoffice})
    return found


def _check_cancel(cancel):
    if cancel is not None:
        check = cancel if callable(cancel) else getattr(cancel, 'is_set', None)
        if check is None:
            raise TypeError('cancel debe ser una función o un Event.')
        if check():
            raise ConversionCancelled('Conversión cancelada. El documento original se conserva.')


def _digest(path, cancel=None):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            _check_cancel(cancel)
            value.update(chunk)
    return value.hexdigest()


def _validate_source(path):
    if path.suffix.lower() not in {'.doc', '.docx'}:
        raise ConversionError('Selecciona un archivo DOC o DOCX.')
    if not path.is_file():
        raise ConversionError('No se encuentra el documento que se quiere convertir.')
    with path.open('rb') as stream:
        signature = stream.read(16)
    compound = signature.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
    if path.suffix.lower() == '.doc':
        if not compound and not signature.lstrip().startswith(b'{\\rtf'):
            raise ConversionError('El archivo no tiene una cabecera DOC o RTF reconocible.')
    else:
        if compound:
            raise ConversionError('El DOCX está cifrado o no tiene el formato esperado. Ábrelo y prepara una copia sin contraseña.')
        try:
            with zipfile.ZipFile(path) as package:
                names = set(package.namelist())
            if not {'[Content_Types].xml', 'word/document.xml'} <= names:
                raise ConversionError('El archivo no contiene un documento DOCX reconocible.')
        except (zipfile.BadZipFile, OSError) as exc:
            raise ConversionError('El archivo no es un DOCX válido.') from exc


# Path values are environment data, never interpolated into PowerShell code.
# The COM server must have a new PID before we open a document or call Quit.
_WORD_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$word = $null; $document = $null; $owned = $false; $settings = $null
try {
    Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class PdfModderOfficePid { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId); }'
    $existing = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $word = New-Object -ComObject Word.Application
    [uint32]$wordPid = 0
    [void][PdfModderOfficePid]::GetWindowThreadProcessId([IntPtr]$word.Hwnd, [ref]$wordPid)
    if ($wordPid -eq 0 -or $existing -contains [int]$wordPid) { throw 'No se pudo crear una instancia independiente de Word.' }
    $owned = $true
    $process = Get-Process -Id $wordPid
    @{pid=[int]$wordPid; started=$process.StartTime.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:PDFMODDER_OFFICE_PID -Encoding UTF8
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $settings = @($word.Options.UpdateLinksAtOpen, $word.Options.UpdateFieldsAtPrint, $word.Options.UpdateLinksAtPrint)
    $word.Options.UpdateLinksAtOpen = $false
    $word.Options.UpdateFieldsAtPrint = $false
    $word.Options.UpdateLinksAtPrint = $false
    $word.ScreenUpdating = $false
    $document = $word.Documents.Open($env:PDFMODDER_OFFICE_SOURCE, $false, $true, $false, '', '', $true, '', '', 0, 0, $false, $false, 0, $true)
    $document.ExportAsFixedFormat($env:PDFMODDER_OFFICE_OUTPUT, 17, $false, 0, 0, 1, 1, 0, $true, $true, 1, $true, $true, $false)
} finally {
    if ($document -ne $null) {
        try { $document.Close(0) } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    }
    if ($word -ne $null) {
        if ($owned -and $settings -ne $null) {
            try {
                $word.Options.UpdateLinksAtOpen = $settings[0]
                $word.Options.UpdateFieldsAtPrint = $settings[1]
                $word.Options.UpdateLinksAtPrint = $settings[2]
            } catch {}
        }
        if ($owned) { try { $word.Quit(0) } catch {} }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
    }
}
'''


_WORD_CLEANUP_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $env:PDFMODDER_OFFICE_PID) {
    $identity = Get-Content -LiteralPath $env:PDFMODDER_OFFICE_PID -Raw | ConvertFrom-Json
    $process = Get-Process -Id ([int]$identity.pid) -ErrorAction SilentlyContinue
    if ($process -ne $null -and $process.ProcessName -ieq 'WINWORD' -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq [string]$identity.started) {
        Stop-Process -Id $process.Id -Force
    }
}
'''


def _powershell_command(executable, script):
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return [executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]


def _stop_process(process):
    if process.poll() is None:
        if not _is_windows():
            # All inputs/profile/output belong to our temporary workspace.
            # Stop the entire new session before reaping its leader, including
            # children that ignore TERM or would otherwise outlive a launcher.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
            return
        if _is_windows():
            # Only our renderer process and its descendants are targeted. A
            # separate LibreOffice profile prevents attaching to a user's UI.
            killer = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/taskkill.exe'
            try:
                subprocess.run([str(killer), '/PID', str(process.pid), '/T', '/F'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5, check=False,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is None:
                process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def _run(command, *, env, timeout, cancel):
    # A file avoids stdout/stderr pipe deadlocks in a document renderer. Its
    # messages may contain private document data, so they are not returned.
    with tempfile.TemporaryFile() as log:
        options = {'stdout': log, 'stderr': subprocess.STDOUT, 'env': env,
                   'stdin': subprocess.DEVNULL, 'shell': False}
        if _is_windows():
            options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        else:
            options['start_new_session'] = True
        try:
            process = subprocess.Popen(command, **options)
        except OSError as exc:
            raise ConversionError('No se pudo iniciar el programa de conversión instalado.') from exc
        started = time.monotonic()
        try:
            while process.poll() is None:
                _check_cancel(cancel)
                if time.monotonic() - started >= timeout:
                    raise ConversionError('La conversión superó el tiempo disponible. El documento original se conserva.')
                time.sleep(.05)
            _check_cancel(cancel)
            if process.returncode:
                raise ConversionError('El programa no pudo convertir el documento. Puede estar protegido, dañado o requerir intervención al abrirlo.')
        finally:
            _stop_process(process)


def _convert_word(source, output, backend, folder, timeout, cancel):
    env = os.environ.copy()
    identity = folder / 'word-process.json'
    env.update(PDFMODDER_OFFICE_SOURCE=str(source), PDFMODDER_OFFICE_OUTPUT=str(output),
               PDFMODDER_OFFICE_PID=str(identity))
    try:
        _run(_powershell_command(backend['executable'], _WORD_SCRIPT), env=env,
             timeout=timeout, cancel=cancel)
    finally:
        # Only the PID and creation time recorded for our new COM instance can
        # be stopped; an existing Word process is never used or terminated.
        if identity.is_file():
            try:
                subprocess.run(_powershell_command(backend['executable'], _WORD_CLEANUP_SCRIPT),
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10, check=False,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired):
                pass


def _convert_libreoffice(source, output, backend, folder, timeout, cancel):
    profile = folder / 'profile'
    user = profile / 'user'
    user.mkdir(parents=True)
    # A fresh profile has no trusted document folders or active user session.
    (user / 'registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
</oor:items>''', encoding='utf-8')
    command = [backend['executable'], '-env:UserInstallation=' + profile.as_uri(),
               '--headless', '--invisible', '--nologo', '--nodefault', '--nofirststartwizard',
               '--norestore', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(output.parent), str(source)]
    _run(command, env=os.environ.copy(), timeout=timeout, cancel=cancel)


def _validate_pdf(path):
    import pymupdf as fitz
    from pypdf import PdfReader
    try:
        if not path.is_file() or path.stat().st_size < 8:
            raise ValueError('Missing PDF')
        with path.open('rb') as stream:
            if not stream.read(8).startswith(b'%PDF-'):
                raise ValueError('Invalid PDF header')
        with fitz.open(path) as document:
            if not document.is_pdf or document.needs_pass or document.is_repaired or document.page_count < 1:
                raise ValueError('Invalid PDF')
            pages = document.page_count
        with path.open('rb') as stream:
            independent = PdfReader(stream, strict=True)
            if independent.is_encrypted or len(independent.pages) != pages:
                raise ValueError('Inconsistent PDF')
        return pages
    except Exception as exc:
        raise ConversionError('El programa de conversión no produjo un PDF completo y verificable.') from exc


def _publish(output, destination, *, automatic, cancel):
    """Publish complete bytes atomically, refusing any existing destination."""
    parent = destination.parent
    if not parent.is_dir():
        raise ConversionError('La carpeta de destino no existe.')
    handle, temporary_name = tempfile.mkstemp(prefix='.pdfmodder-convert-', suffix='.pdf', dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, 'wb') as target, output.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                _check_cancel(cancel)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        for suffix in range(10000):
            candidate = destination if suffix == 0 else destination.with_name(f'{destination.stem} ({suffix}){destination.suffix}')
            _check_cancel(cancel)
            try:
                if _is_windows():
                    # Windows rename is atomic and fails when target exists.
                    os.rename(temporary, candidate)
                else:
                    # POSIX rename would overwrite. A same-directory hard link
                    # publishes the completed inode with O_EXCL semantics.
                    os.link(temporary, candidate)
                    temporary.unlink()
                return candidate
            except FileExistsError:
                if not automatic:
                    raise ConversionError('Ya existe un archivo con ese nombre. Elige otro destino.')
        raise ConversionError('No se encontró un nombre libre para guardar el PDF.')
    except OSError as exc:
        raise ConversionError('No se pudo guardar el PDF en la carpeta de destino.') from exc
    finally:
        temporary.unlink(missing_ok=True)


def convert_document_to_pdf(source, destination=None, *, backend='auto', timeout=180, cancel=None):
    """Convert one DOC/DOCX locally and return metadata about its saved PDF.

    An omitted destination saves next to the input, choosing ``(1)``, ``(2)``…
    when needed. An explicit destination must be a new .pdf filename. No engine
    is installed or downloaded and an engine failure never switches renderers.
    """
    source = Path(source).resolve()
    _check_cancel(cancel)
    try:
        _validate_source(source)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise ConversionError('El tiempo máximo de conversión no es válido.')
        if backend not in ('auto', 'word', 'libreoffice'):
            raise ConversionError('El programa de conversión seleccionado no es compatible.')
        backends = available_backends()
        chosen = next((item for item in backends if backend == 'auto' or item['id'] == backend), None)
        if chosen is None:
            raise ConversionError('Para convertir DOC y DOCX instala Microsoft Word o LibreOffice. PDF Modder utiliza uno de ellos para conservar el formato.')
        if destination is not None:
            requested = Path(destination).absolute()
            # Resolve the folder, not the filename: a dangling link is an
            # existing destination too and must never redirect publication.
            target = requested.parent.resolve() / requested.name
        else:
            target = source.with_suffix('.pdf')
        if target.suffix.lower() != '.pdf' or target == source:
            raise ConversionError('El destino debe ser un archivo PDF nuevo.')
        if destination is not None and (target.exists() or target.is_symlink()):
            raise ConversionError('Ya existe un archivo con ese nombre. Elige otro destino.')
        original_hash = _digest(source, cancel)
        with tempfile.TemporaryDirectory(prefix='pdfmodder-office-') as working:
            folder = Path(working)
            staged_source = folder / source.name
            shutil.copyfile(source, staged_source)
            if _digest(staged_source, cancel) != original_hash:
                raise ConversionError('El documento cambió mientras se preparaba la conversión. Vuelve a intentarlo.')
            output = staged_source.with_suffix('.pdf')
            converter = _convert_word if chosen['id'] == 'word' else _convert_libreoffice
            converter(staged_source, output, chosen, folder, timeout, cancel)
            _check_cancel(cancel)
            pages = _validate_pdf(output)
            digest = _digest(output, cancel)
            size = output.stat().st_size
            if _digest(source, cancel) != original_hash:
                raise ConversionError('El documento cambió durante la conversión. El resultado no se ha guardado.')
            published = _publish(output, target, automatic=destination is None, cancel=cancel)
        return {'path': str(published), 'backend': chosen['id'], 'backend_name': chosen['name'],
                'pages': pages, 'size': size, 'sha256': digest,
                'source': str(source), 'source_sha256': original_hash, 'source_unchanged': True}
    except ConversionError:
        raise
    except (OSError, ValueError) as exc:
        raise ConversionError('No se pudo leer el documento o preparar su conversión a PDF.') from exc
