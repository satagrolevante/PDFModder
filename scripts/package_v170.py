"""Empaqueta la versión actual con evidencia de sus propias pruebas dirigidas."""
import argparse
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_licenses import source_files
from scripts.package_v09 import (BUNDLE, RELEASE, application_sources, digest,
                                 finish, read, source_fingerprint, write)
from pdfmodder import __version__

SUITE = 'v' + __version__.replace('.', '')


def prepare():
    if int(__version__.split('.')[0])>=3:
        raise SystemExit('Utiliza scripts/package_v300.py; este protocolo histórico no acredita las mejoras 3.0.0.')
    binding = read(ROOT / f'output/{SUITE}-source-tests.json')
    xml = ROOT / f'output/pytest-{SUITE}-results.xml'
    assert binding['exit_code'] == 0 and binding['source_unchanged']
    assert binding.get('application_version', __version__) == __version__
    assert binding['app_source_sha256'] == source_fingerprint()
    assert binding['report_sha256'] == digest(xml)
    suites = [s for s in ET.parse(xml).getroot().iter('testsuite') if not s.findall('testsuite')]
    assert suites and all(int(s.get(k, '0')) == 0 for s in suites for k in ('failures', 'errors'))
    tests = sum(int(s.get('tests', '0')) for s in suites)
    skipped = sum(int(s.get('skipped', '0')) for s in suites)
    for path in application_sources():
        assert digest(path) == digest(BUNDLE / '_internal/source/PDFModder' / path.relative_to(ROOT)), path
    smoke_path = ROOT / f'output/packaged-{SUITE}-smoke.json'
    smoke = read(smoke_path)
    exe_hash = digest(BUNDLE / 'PDFModder.exe')
    assert smoke['ok'] and smoke['frozen'] and smoke['stage'] == 'complete'
    assert smoke['app_version'] == __version__ and smoke['exe_sha256'] == exe_hash
    assert smoke['steps'] and all(step['ok'] for step in smoke['steps'])
    assert smoke['source_sha256'] == digest(smoke['source'])
    if SUITE in ('v202', 'v203'):
        bridge = {'compiled': True, 'retested': False,
                  'exe_sha256': digest(BUNDLE / 'PDFModderSigningBridge.exe'),
                  'source_sha256': digest(ROOT / 'installer/PdfModderSigningBridge.cs')}
    else:
        bridge = read(ROOT / 'output/signing-bridge-v160.json')
        assert bridge['ok'] and bridge['temporary_certificate_and_key_removed']
        assert bridge['signature_verified_independently'] and not bridge['private_keys_exported']
        assert bridge['exe_sha256'] == digest(BUNDLE / 'PDFModderSigningBridge.exe')
        assert bridge['source_sha256'] == digest(ROOT / 'installer/PdfModderSigningBridge.cs')
    if SUITE == 'v203':
        checked_scope = 'Canal de actualización canónico satagrolevante/PDFModder, metadatos públicos y preparación de releases'
        checked_note = 'Se comprueban las rutas del actualizador y la preparación de releases con datos aislados. Los workflows se incluyen como código; su ejecución en GitHub Actions y la subida remota no se acreditan con estas pruebas locales. No se repiten las pruebas de asociaciones, del puente de firma ni de instalación y desinstalación.'
    elif SUITE == 'v202':
        checked_scope = 'Registro de asociaciones PDF, actualización de comandos y limpieza por instalación propietaria'
        checked_note = 'Pruebas del código C# con registro temporal aislado y recorrido del ejecutable nativo. No se altera UserChoice ni se repite el corpus PDF histórico; la elección manual en Configuración de Windows queda fuera de estas pruebas.'
    elif SUITE == 'v201':
        checked_scope = 'Impresora, color y grises, páginas, copias, dúplex, escala, papel, orientación y vista previa paginada'
        checked_note = 'Se comprueban configuración y capacidades simuladas, salida PDF de impresión, conversión a grises y vista previa nativa. No se envían trabajos a impresoras físicas.'
    elif SUITE == 'v200':
        checked_scope = 'Instancias de texto, fuentes CFF, celdas, imágenes giradas, formularios, preflight, aceptación, pestañas, recuperación, cachés, censura e impresión'
        checked_note = 'Se comprueban las operaciones nuevas con corpus sintético, estructura y extracción independiente, y la interfaz y el ejecutable.'
    elif SUITE == 'v181':
        checked_scope = 'Actualizador público sin consulta REST habitual, espera de consultas y caché de metadatos'
        checked_note = 'Se comprueban límites de consultas, caché, descarga segura y el recorrido del ejecutable.'
    elif SUITE == 'v180':
        checked_scope = 'Lectura continua, copia entre páginas, etiquetas y actualización con corpus sintético'
        checked_note = 'Se comprueban lectura continua, copia entre páginas, etiquetas y actualización con documentos e instalaciones aislados.'
    elif SUITE == 'v171':
        checked_scope = 'Lectura, selección de texto y navegación con documentos sintéticos'
        checked_note = 'Se comprueban lectura, selección de texto y navegación con documentos sintéticos.'
    else:
        checked_scope = 'Cifrado y portapapeles con corpus sintético'
        checked_note = 'Se contrastan metadatos y cifrado con documentos y certificados sintéticos.'
    native_ui_verified = smoke.get('native_ui_verified', SUITE != 'v203')
    qt_platform = smoke.get('qt_platform', 'sin informar' if SUITE == 'v203' else 'windows')
    if SUITE == 'v203':
        native_ui_verified = bool(native_ui_verified and qt_platform == 'windows')
    evidence = {
        'application': 'PDF Modder ' + __version__, 'platform': platform.platform(),
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'delivery_status': 'targeted_checks_passed' if native_ui_verified else 'targeted_checks_passed_native_ui_pending',
        'tested': True, 'frozen_verified': True, 'native_ui_verified': native_ui_verified,
        'app_source_sha256': source_fingerprint(), 'exe_sha256': exe_hash,
        'pytest': {'passed': tests-skipped, 'skipped': skipped, 'failures': 0,
                   'report_sha256': digest(xml), 'selection': binding['tests']},
        'frozen_smoke': {'steps': len(smoke['steps']), 'seconds': smoke['elapsed_seconds'],
                         'qt_platform': qt_platform,
                         'report_sha256': digest(smoke_path)},
        'windows_certificate_bridge': bridge,
        'private_documents_included': False, 'personal_certificates_included': False,
        'source_manifest': '_internal/source/MANIFEST.json',
        'scope': f'Comprobaciones dirigidas a los cambios de {__version__} y recorrido del ejecutable. '
                 'No se repite la batería completa ni el corpus completo de 1.5.0. '
                 f'{checked_scope}; sin publicación remota acreditada. '
                 'Instalación y retirada se acreditan por separado; no otro ordenador físico. '
                 + ('La plataforma Windows nativa de la GUI no está acreditada.' if not native_ui_verified else ''),
    }
    if SUITE == 'v203':
        evidence.update(update_repository='satagrolevante/PDFModder',
                        remote_publication_verified=False, github_actions_run_verified=False,
                        association_registration_tested=False, full_installation_tested=False)
        evidence['scope'] = (
            f'Comprobaciones locales dirigidas al canal de actualización de {__version__}: '
            f'{checked_scope}. Ejecutable congelado acreditado por su hash; '
            f'plataforma Qt {qt_platform}, GUI Windows nativa acreditada: {native_ui_verified}. '
            'Los workflows se incluyen como código; su ejecución y la subida remota no se acreditan aquí. '
            'El instalador se documenta como compilado; no se prueban su ejecución nativa, instalación o retirada. '
            'No se repiten asociaciones, puente de firma, batería completa ni corpus histórico; '
            'no se prueba otro ordenador físico.'
        )
    (ROOT / f'docs/RESULTADOS_{SUITE.upper()}.md').write_text(
        f'# Comprobaciones de PDF Modder {__version__}\n\n'
        f'- Pruebas dirigidas: {tests-skipped} aprobadas; {skipped} omitidas; cero fallos.\n'
        f'- Ejecutable Windows: {len(smoke["steps"])} pasos aprobados.\n'
        f'- Plataforma GUI de la prueba: {qt_platform}; escritorio nativo verificado: {native_ui_verified}.\n'
        f'- {checked_note} '
        'No se prueba una clave personal ni otro ordenador físico.\n'
        + ('- Instalador: compilación y hash documentados aparte; sin ejecución nativa, instalación, desinstalación ni cambios en el Registro acreditados para esta entrega.\n' if SUITE == 'v203' else
           '- Registro y limpieza: ASOCIACIONES-VERIFICADAS.json; no se instala la copia de prueba como lector real.\n' if SUITE == 'v202' else
           '- Instalación y desinstalación: informe separado INSTALACION-VERIFICADA.json.\n')
        +
        '- No se ha repetido la batería completa ni las 64 operaciones de la versión 1.5.0.\n'
        f'- No se ha probado en otro equipo físico. Límites en GUIA_{SUITE.upper()}.md.\n', encoding='utf-8')
    RELEASE.mkdir(parents=True, exist_ok=True)
    for target in (BUNDLE / 'ENTREGA.json', RELEASE / 'ENTREGA.json'):
        write(target, evidence)
    for path in [ROOT / 'README.md', *[p for p in (ROOT / 'docs').rglob('*') if p.is_file()]]:
        target = BUNDLE / '_internal' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(ROOT / 'README.md', BUNDLE / 'README.md')
    inventory = []
    for path, relative in source_files():
        target = BUNDLE / '_internal/source/PDFModder' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        inventory.append({'path': relative.as_posix(), 'sha256': digest(path)})
    write(BUNDLE / '_internal/source/MANIFEST.json', inventory)
    print(json.dumps(evidence, ensure_ascii=False))


def finish_delivery(installation):
    if SUITE in ('v180', 'v181'):
        state = read(ROOT / f'output/release-{SUITE}-state.json')
        upgrade = read(state['upgrade'])
        installer = RELEASE / f'PDFModder-v{__version__}-Instalar.exe'
        assert upgrade['ok'] and upgrade['application_version'] == __version__
        assert upgrade['installer_sha256'] == digest(installer)
        assert len(upgrade['tests']) == 4 and all(t['passed'] for t in upgrade['tests'])
        summary = {k: upgrade[k] for k in ('ok', 'application_version', 'previous_version',
                                         'fixture', 'installer_sha256', 'started_utc')}
        summary['tests'] = [{k: v for k, v in t.items() if k in ('name', 'passed', 'verified_new_files')}
                            for t in upgrade['tests']]
        write(RELEASE / 'ACTUALIZACION-VERIFICADA.json', summary)
        evidence = read(RELEASE / 'ENTREGA.json')
        evidence['upgrade'] = summary
        write(RELEASE / 'ENTREGA.json', evidence)
    finish(installation)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--prepare', action='store_true')
    choices.add_argument('--finish', type=Path)
    args = parser.parse_args()
    prepare() if args.prepare else finish_delivery(args.finish)
