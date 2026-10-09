"""Empaqueta 3.0.x con pruebas de esta revisión y del mismo ejecutable.

--prepare valida pruebas/GUI y prepara las fuentes antes del instalador.
--finish exige instalación y retirada aisladas y genera ZIP/sumas SHA-256.
Este script no publica en GitHub ni consulta documentos privados.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.collect_licenses import source_files
from scripts.package_v09 import BUNDLE, RELEASE, application_sources, digest, finish, read, source_fingerprint, write

# Each feature also has behavioral tests. These steps ensure the frozen GUI
# exercises the new opening/selection/capability/save paths with its real worker.
REQUIRED_SMOKE_STEPS = frozenset({
    "apertura_progresiva_v300", "seleccion_por_alcance_v300",
    "compatibilidad_por_operacion_v300", "guardar_todo_v300",
    "guardar_destino_recordado_v300", "cancelar_cierre_v300",
    "guardar_antes_de_cerrar_v300", "motor_objetos_v300", "tipografia_pdf_v300",
})


def checked_test_report() -> tuple[dict, int, int]:
    binding = read(ROOT / "output/v300-source-tests.json")
    xml = ROOT / "output/pytest-v300-results.xml"
    if (binding.get("application_version") != __version__ or binding.get("exit_code") != 0
            or not binding.get("source_unchanged") or binding.get("app_source_sha256") != source_fingerprint()
            or binding.get("report_sha256") != digest(xml)):
        raise RuntimeError("La evidencia de pytest no corresponde a las fuentes actuales de " + __version__ + ".")
    suites = [suite for suite in ET.parse(xml).getroot().iter("testsuite") if not suite.findall("testsuite")]
    if not suites or any(int(suite.get(key, "0")) for suite in suites for key in ("failures", "errors")):
        raise RuntimeError("Las pruebas tienen fallos o faltan resultados.")
    total = sum(int(suite.get("tests", "0")) for suite in suites)
    skipped = sum(int(suite.get("skipped", "0")) for suite in suites)
    if total <= skipped:
        raise RuntimeError("Ninguna prueba de la versión ha aprobado.")
    return binding, total - skipped, skipped


def checked_smoke() -> dict:
    report = read(ROOT / "output/packaged-v300-smoke.json")
    if (not report.get("ok") or not report.get("frozen") or report.get("stage") != "complete"
            or report.get("app_version") != __version__ or report.get("exe_sha256") != digest(BUNDLE / "PDFModder.exe")
            or report.get("source_sha256") != digest(report["source"])):
        raise RuntimeError("El recorrido no acredita el ejecutable actual de " + __version__ + " ni su corpus.")
    steps = report.get("steps", [])
    if not steps or not all(step.get("ok") for step in steps) or not REQUIRED_SMOKE_STEPS.issubset({step.get("step") for step in steps}):
        raise RuntimeError("Faltan pasos aprobados del recorrido 3.0.0.")
    return report


def prepare() -> None:
    if not re.fullmatch(r"3\.0\.\d+", __version__):
        raise RuntimeError("Este empaquetado corresponde a la familia 3.0.x.")
    binding, passed, skipped = checked_test_report()
    smoke = checked_smoke()
    for path in application_sources():
        if digest(path) != digest(BUNDLE / "_internal/source/PDFModder" / path.relative_to(ROOT)):
            raise RuntimeError(f"Las fuentes incluidas en el ejecutable difieren: {path}")
    bridge = read(ROOT / "output/signing-bridge-v160.json")
    if (not bridge.get("ok") or not bridge.get("temporary_certificate_and_key_removed")
            or not bridge.get("signature_verified_independently") or bridge.get("private_keys_exported")
            or bridge.get("exe_sha256") != digest(BUNDLE / "PDFModderSigningBridge.exe")
            or bridge.get("source_sha256") != digest(ROOT / "installer/PdfModderSigningBridge.cs")):
        raise RuntimeError("El puente de certificados no tiene comprobación del binario actual.")
    qt_platform = smoke.get("qt_platform", "sin informar")
    native = bool(smoke.get("native_ui_verified") and qt_platform == "windows")
    evidence = {
        "application": "PDF Modder " + __version__, "platform": platform.platform(),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "delivery_status": "targeted_checks_passed" if native else "targeted_checks_passed_native_ui_pending",
        "tested": True, "frozen_verified": True, "native_ui_verified": native,
        "app_source_sha256": source_fingerprint(), "exe_sha256": digest(BUNDLE / "PDFModder.exe"),
        "pytest": {"passed": passed, "skipped": skipped, "failures": 0, "errors": 0,
                   "report_sha256": binding["report_sha256"], "selection": binding["tests"]},
        "frozen_smoke": {"steps": len(smoke["steps"]), "seconds": smoke["elapsed_seconds"],
                         "qt_platform": qt_platform, "report_sha256": digest(ROOT / "output/packaged-v300-smoke.json")},
        "windows_certificate_bridge": bridge,
        "source_manifest": "_internal/source/MANIFEST.json",
        "private_documents_included": False, "personal_certificates_included": False,
        "remote_publication_verified": False, "github_actions_run_verified": False,
        "scope": "Pruebas de esta revisión y recorrido GUI/worker con corpus sintético: apertura progresiva, "
                 "selección por alcance, guardado y cierre, compatibilidad por operación, objetos y tipografía. "
                 "Las pruebas dirigidas no acreditan todos los PDF posibles ni otro ordenador físico. "
                 "La instalación y retirada se comprueban por separado. "
                 + ("GUI Windows nativa pendiente." if not native else "GUI Windows nativa ejecutada."),
    }
    RELEASE.mkdir(parents=True, exist_ok=True)
    for target in (BUNDLE / "ENTREGA.json", RELEASE / "ENTREGA.json"):
        write(target, evidence)
    for path in [ROOT / "README.md", *sorted(p for p in (ROOT / "docs").rglob("*") if p.is_file())]:
        target = BUNDLE / "_internal" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(ROOT / "README.md", BUNDLE / "README.md")
    inventory = []
    for path, relative in source_files():
        target = BUNDLE / "_internal/source/PDFModder" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        inventory.append({"path": relative.as_posix(), "sha256": digest(path)})
    write(BUNDLE / "_internal/source/MANIFEST.json", inventory)
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--finish", type=Path, metavar="INFORME_INSTALACION")
    args = parser.parse_args()
    prepare() if args.prepare else finish(args.finish)
