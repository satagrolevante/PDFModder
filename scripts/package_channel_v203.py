"""Close the local update-channel release with current, scoped evidence.

This only reads local verification reports and packages files. It does not run
an installer, change the Registry, execute GitHub Actions or upload a release.
"""
from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.collect_licenses import source_files
from scripts.package_v09 import BUNDLE, RELEASE, digest, read, source_fingerprint, write


def finish():
    assert __version__ == '2.0.3'
    fingerprint = source_fingerprint()
    evidence = read(RELEASE / 'ENTREGA.json')
    assert evidence['application'] == 'PDF Modder ' + __version__
    assert evidence['tested'] and evidence['frozen_verified']
    assert evidence['app_source_sha256'] == fingerprint

    binding = read(ROOT / 'output/v203-source-tests.json')
    report = ROOT / 'output/pytest-v203-results.xml'
    assert binding['application_version'] == __version__
    assert binding['exit_code'] == 0 and binding['source_unchanged']
    assert binding['app_source_sha256'] == fingerprint
    assert binding['report_sha256'] == digest(report) == evidence['pytest']['report_sha256']
    assert binding['tests'] == evidence['pytest']['selection']
    suites = [s for s in ET.parse(report).getroot().iter('testsuite') if not s.findall('testsuite')]
    assert suites and all(int(s.get(k, '0')) == 0 for s in suites for k in ('failures', 'errors'))
    tests = sum(int(s.get('tests', '0')) for s in suites)
    skipped = sum(int(s.get('skipped', '0')) for s in suites)
    assert tests - skipped > 0
    assert evidence['pytest']['passed'] == tests - skipped
    assert evidence['pytest']['skipped'] == skipped

    smoke_path = ROOT / 'output/packaged-v203-smoke.json'
    smoke = read(smoke_path)
    exe_hash = digest(BUNDLE / 'PDFModder.exe')
    assert smoke['ok'] and smoke['frozen'] and smoke['stage'] == 'complete'
    assert smoke['app_version'] == __version__
    assert smoke['exe_sha256'] == exe_hash == evidence['exe_sha256']
    assert smoke['steps'] and all(step['ok'] for step in smoke['steps'])
    assert smoke['source_sha256'] == digest(smoke['source'])
    assert evidence['frozen_smoke']['report_sha256'] == digest(smoke_path)
    qt_platform = smoke.get('qt_platform', 'sin informar')
    native_ui_verified = bool(smoke.get('native_ui_verified', False) and qt_platform == 'windows')
    assert evidence['native_ui_verified'] == native_ui_verified

    files = source_files()
    inventory = [{'path': relative.as_posix(), 'sha256': digest(path)} for path, relative in files]
    assert read(BUNDLE / '_internal/source/MANIFEST.json') == inventory
    for row in inventory:
        assert digest(BUNDLE / '_internal/source/PDFModder' / row['path']) == row['sha256'], row['path']
    bridge = evidence['windows_certificate_bridge']
    assert bridge['compiled'] and bridge['retested'] is False
    assert bridge['exe_sha256'] == digest(BUNDLE / 'PDFModderSigningBridge.exe')
    assert bridge['source_sha256'] == digest(ROOT / 'installer/PdfModderSigningBridge.cs')

    installer = RELEASE / f'PDFModder-v{__version__}-Instalar.exe'
    metadata = read(RELEASE / 'INSTALADOR.json')
    installer_hash = digest(installer)
    assert metadata['application'] == 'PDF Modder ' + __version__
    assert metadata['compiled'] and metadata['installer_sha256'] == installer_hash
    staging = ROOT / f'build/installer-v{__version__}'
    assert metadata['payload_sha256'] == digest(staging / 'PDFModderPayload.zip')
    payload = {}
    for row in (staging / 'PDFModderPayload.tsv').read_text(encoding='utf-8').splitlines():
        sha256, size, name = row.split('\t')
        assert name.startswith('PDFModder/') and name not in payload, name
        payload[name] = (sha256, int(size))
    bundle_files = [p for p in BUNDLE.rglob('*') if p.is_file()]
    assert {'PDFModder/' + p.relative_to(BUNDLE).as_posix() for p in bundle_files} == set(payload)
    for path in bundle_files:
        sha256, size = payload['PDFModder/' + path.relative_to(BUNDLE).as_posix()]
        assert path.stat().st_size == size and digest(path) == sha256, path

    archives = (
        (RELEASE / f'PDFModder-v{__version__}-Windows-x64.zip',
         [(p, Path('PDFModder') / p.relative_to(BUNDLE)) for p in bundle_files]),
        (RELEASE / f'PDFModder-v{__version__}-codigo.zip',
         [(p, Path('PDFModder') / relative) for p, relative in files]),
    )
    for target, _ in archives:
        if target.exists():
            raise FileExistsError(target)
    metadata.update(tested=False, association_registration_tested=False,
                    full_installation_tested=False, native_execution_tested=False,
                    note='Instalador compilado y ligado por SHA-256 al payload actual. '
                         'No se ejecuta ni se repiten instalación, desinstalación o asociaciones en esta entrega.')
    metadata.pop('verification_report', None)
    write(RELEASE / 'INSTALADOR.json', metadata)
    evidence.update(installer_sha256=installer_hash, update_repository='satagrolevante/PDFModder',
                    remote_publication_verified=False, github_actions_run_verified=False,
                    association_registration_tested=False, full_installation_tested=False,
                    installer_native_execution_tested=False)
    evidence.pop('association_registration', None)
    write(RELEASE / 'ENTREGA.json', evidence)
    (RELEASE / 'VERIFICACION-ENTREGA.txt').write_text(
        f'PDF Modder {__version__}\n'
        f'Canal canónico de actualización: {evidence["update_repository"]}\n'
        f'Pruebas dirigidas locales aprobadas: {tests - skipped}; omitidas: {skipped}.\n'
        f'Pasos del ejecutable congelado: {len(smoke["steps"])}.\n'
        f'Plataforma Qt: {qt_platform}; GUI Windows nativa acreditada: {native_ui_verified}.\n'
        'Los workflows se incluyen como código; su ejecución en GitHub Actions y la publicación remota no se acreditan aquí.\n'
        'Instalador: compilación y payload verificados por hash; ejecución nativa, instalación y desinstalación no probadas.\n'
        'Asociaciones PDF y puente de firma no retestados; no se utiliza evidencia histórica para acreditarlos.\n'
        'Este cierre no modifica el Registro ni UserChoice. No se repite el corpus PDF histórico.\n'
        f'Ejecutable SHA-256: {exe_hash}\n'
        f'Instalador SHA-256: {installer_hash}\n', encoding='utf-8')
    checks = ('VERIFICACION-ENTREGA.txt', 'ENTREGA.json', 'INSTALADOR.json')
    for target, archived_files in archives:
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, relative in sorted(archived_files):
                archive.write(path, relative.as_posix())
            for check in checks:
                archive.write(RELEASE / check, 'Entrega/' + check)
        target.with_suffix(target.suffix + '.sha256').write_text(
            f'{digest(target)}  {target.name}\n', encoding='ascii')
    installer.with_suffix('.exe.sha256').write_text(
        f'{installer_hash}  {installer.name}\n', encoding='ascii')
    entries = [{'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
               for path in (installer, *(target for target, _ in archives))]
    write(RELEASE / 'ARCHIVOS.json', entries)
    print(json.dumps({'files': entries, 'update_repository': evidence['update_repository'],
                      'native_ui_verified': native_ui_verified,
                      'full_installation_tested': False, 'remote_publication_verified': False},
                     ensure_ascii=False))


if __name__ == '__main__':
    finish()
