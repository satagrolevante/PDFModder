"""Finish the association fix with scoped evidence, without changing live defaults."""
from pathlib import Path
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.collect_licenses import source_files
from scripts.package_v09 import BUNDLE, RELEASE, digest, read, source_fingerprint, write


def finish():
    assert __version__ == '2.0.2'
    evidence = read(RELEASE / 'ENTREGA.json')
    assert evidence['app_source_sha256'] == source_fingerprint()
    assert evidence['frozen_verified'] and evidence['exe_sha256'] == digest(BUNDLE / 'PDFModder.exe')
    installer = RELEASE / f'PDFModder-v{__version__}-Instalar.exe'
    metadata = read(RELEASE / 'INSTALADOR.json')
    assert metadata['compiled'] and metadata['installer_sha256'] == digest(installer)
    associations = read(ROOT / 'output/associations-v202.json')
    assert associations['ok'] and associations['real_registry_unchanged']
    assert associations['source_sha256']['installer'] == digest(ROOT / 'installer/PdfModderInstaller.cs')
    assert associations['source_sha256']['uninstaller'] == digest(ROOT / 'installer/PdfModderUninstaller.cs')
    write(RELEASE / 'ASOCIACIONES-VERIFICADAS.json', associations)
    metadata.update(association_registration_tested=True, full_installation_tested=False,
                    note='Registro y limpieza probados en raíz aislada; no se instala esta copia de prueba como lector real.')
    write(RELEASE / 'INSTALADOR.json', metadata)
    evidence.update(association_registration=associations, full_installation_tested=False,
                    installer_sha256=digest(installer))
    write(RELEASE / 'ENTREGA.json', evidence)
    (RELEASE / 'VERIFICACION-ENTREGA.txt').write_text(
        f'PDF Modder {__version__}\n'
        f'Pruebas dirigidas aprobadas: {evidence["pytest"]["passed"]}\n'
        f'Pasos del ejecutable Windows: {evidence["frozen_smoke"]["steps"]}\n'
        'Registro de asociaciones: código C# de producción, raíz temporal aislada.\n'
        'El registro real y UserChoice permanecen intactos durante las pruebas.\n'
        'No se repite el corpus histórico. No se realiza instalación real ni selección manual en Configuración.\n'
        f'Instalador SHA-256: {digest(installer)}\n', encoding='utf-8')
    checks = ('VERIFICACION-ENTREGA.txt', 'ENTREGA.json', 'INSTALADOR.json', 'ASOCIACIONES-VERIFICADAS.json')
    for name, files in (
        (f'PDFModder-v{__version__}-Windows-x64.zip', [(p, Path('PDFModder') / p.relative_to(BUNDLE)) for p in BUNDLE.rglob('*') if p.is_file()]),
        (f'PDFModder-v{__version__}-codigo.zip', [(p, Path('PDFModder') / rel) for p, rel in source_files()]),
    ):
        target = RELEASE / name
        if target.exists():
            raise FileExistsError(target)
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, relative in sorted(files):
                archive.write(path, relative.as_posix())
            for check in checks:
                archive.write(RELEASE / check, 'Entrega/' + check)
        target.with_suffix(target.suffix + '.sha256').write_text(f'{digest(target)}  {target.name}\n', encoding='ascii')
    print(json.dumps({'installer': str(installer), 'sha256': digest(installer),
                      'association_registration_tested': True, 'full_installation_tested': False}))


if __name__ == '__main__':
    finish()
