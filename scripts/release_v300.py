"""Comprueba y construye PDF Modder 3.0.x sin publicar archivos remotos.

En Linux, --source-only --headless-qa ejecuta las pruebas y el recorrido Qt.
La construcción, el ejecutable y el instalador requieren Windows/Python 3.12 x64.
--start permite reanudar una entrega sólo si sigue correspondiendo a las fuentes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.package_v09 import digest, read, source_fingerprint, write

SUITE = "v300"
STATE = ROOT / "output/release-v300-state.json"
PHASES = ("source", "build", "binary", "installer", "finish")


def python_executable() -> str:
    configured = os.environ.get("PDFMODDER_BUILD_PYTHON")
    if configured:
        return configured
    venv = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    return str(venv) if venv.is_file() else sys.executable


def run(name: str, args: list[str], *, headless: bool, clean: bool = False) -> str:
    print(name + "...", flush=True)
    environment = os.environ.copy()
    if clean:
        for key in list(environment):
            if key.startswith(("PYTHON", "PYSIDE", "QT_", "QML", "VIRTUAL_ENV", "CONDA", "_PYI")):
                environment.pop(key, None)
        windows = Path(environment.get("SystemRoot", "C:/Windows"))
        environment["PATH"] = os.pathsep.join(str(windows / p) for p in ("System32", "", "System32/Wbem"))
    environment["PYTHONIOENCODING"] = "utf-8"
    if headless:
        environment["QT_QPA_PLATFORM"] = "offscreen"
    log = ROOT / f"output/release-{SUITE}-{name}.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, env=environment)
    value = log.read_text(encoding="utf-8", errors="replace")
    if result.returncode:
        print("\n".join(value.splitlines()[-55:]), flush=True)
        raise RuntimeError(f"{name}: código {result.returncode}; {log}")
    print(name + ": terminado.", flush=True)
    return value


def default_tests() -> list[str]:
    """Always include the new behavioral tests; never borrow a historical report."""
    tests = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_*v300*.py"))
    if not tests:
        raise RuntimeError("Faltan las pruebas de comportamiento de 3.0.0; indique --tests.")
    return tests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", choices=PHASES, default="source")
    parser.add_argument("--tests", nargs="+")
    parser.add_argument("--source-only", action="store_true", help="Pruebas y GUI desde las fuentes; sin construir Windows")
    parser.add_argument("--source-ui-only", action="store_true", help="Sólo recorrido de GUI desde fuentes; no acredita la batería")
    parser.add_argument("--headless-qa", action="store_true", help="Qt offscreen; no acredita el escritorio nativo de Windows")
    args = parser.parse_args()
    if not re.fullmatch(r"3\.0\.\d+", __version__):
        parser.error("Este protocolo corresponde a la familia 3.0.x.")
    if args.source_only and args.start != "source":
        parser.error("--source-only exige --start source.")
    if os.name != "nt" and not (args.source_only or args.source_ui_only):
        parser.error("La construcción del ejecutable e instalador exige Windows; use --source-only aquí.")
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "tmp").mkdir(exist_ok=True)
    python = python_executable()
    execute = lambda name, command, **kwargs: run(name, command, headless=args.headless_qa, **kwargs)
    source_ui = [python, "run_pdfmodder.py", "--smoke-v300", str(ROOT / "output/source-v300-smoke.json")]
    if args.source_ui_only:
        execute("source-ui", source_ui)
        return
    start = PHASES.index(args.start)
    state = read(STATE) if STATE.exists() else {}
    if start == 0:
        tests = args.tests or default_tests()
        fingerprint = source_fingerprint()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        execute("source-tests", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                "--basetemp", "tmp/pytest-v300-" + stamp,
                "--junitxml", "output/pytest-v300-results.xml", *tests])
        if fingerprint != source_fingerprint():
            raise RuntimeError("El código cambió durante las pruebas; vuelva a ejecutarlas sobre la revisión final.")
        write(ROOT / "output/v300-source-tests.json", {
            "application_version": __version__, "exit_code": 0, "source_unchanged": True,
            "app_source_sha256": fingerprint, "report_sha256": digest(ROOT / "output/pytest-v300-results.xml"),
            "tests": tests,
        })
        execute("source-ui", source_ui)
        state = {"application_version": __version__, "app_source_sha256": fingerprint,
                 "qa_headless": args.headless_qa}
        write(STATE, state)
        if args.source_only:
            return
    if state.get("application_version") != __version__ or state.get("app_source_sha256") != source_fingerprint():
        raise RuntimeError("Ejecute las pruebas de " + __version__ + " sobre el código actual antes de reanudar.")
    if start <= 1:
        execute("build", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                "scripts/build.ps1", "-SkipTests", "-PythonExecutable", python])
    if start <= 2:
        execute("windows-certificate", [python, "scripts/build_signing_bridge.py", "--self-test"])
        execute("binary", [str(ROOT / "dist/PDFModder/PDFModder.exe"), "--smoke-v300",
                str(ROOT / "output/packaged-v300-smoke.json")], clean=True)
        smoke = read(ROOT / "output/packaged-v300-smoke.json")
        expected_platform = "offscreen" if args.headless_qa else "windows"
        if smoke.get("qt_platform") != expected_platform or smoke.get("native_ui_verified") != (not args.headless_qa):
            raise RuntimeError("La plataforma de la GUI no corresponde a la prueba solicitada.")
    if start <= 3:
        execute("prepare", [python, "scripts/package_v300.py", "--prepare"])
        execute("installer-build", [python, "scripts/build_current_installer.py"])
        result = execute("installer-tests", [python, "scripts/verify_install_uninstall_v09.py", "--suite", "v300"])
        state["installation"] = json.loads(result)["report"]
        write(STATE, state)
    if start <= 4:
        execute("finish", [python, "scripts/package_v300.py", "--finish", state["installation"]])
        execute("update-manifest", [python, "scripts/publish_github_releases.py", "--prepare-only"])
    print("Entrega local lista: " + str(ROOT / ("releases/v" + __version__)), flush=True)


if __name__ == "__main__":
    main()
