"""Compile the per-user Explorer selection bridge; no Explorer injection."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__


def build(destination: Path | None = None) -> Path:
    target = destination or ROOT / 'dist/PDFModder/PDFModderShellActions.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'installer/PdfModderShellActions.cs'
    generated = ROOT / 'build' / ('shell-actions-v' + __version__) / source.name
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(source.read_text(encoding='utf-8-sig').replace('1.7.0.0', __version__ + '.0'),
                         encoding='utf-8-sig')
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([
        str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/out:' + str(target),
        '/win32manifest:' + str(ROOT / 'installer/asInvoker.manifest'),
        '/win32icon:' + str(ROOT / 'assets/icons/pdfmodder.ico'),
        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
        '/reference:System.Web.Extensions.dll', str(generated),
    ], check=True, cwd=ROOT)
    return target


if __name__ == '__main__':
    print(build())
