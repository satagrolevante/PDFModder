"""Prepara el código actual para GitHub, sin archivos de trabajo ni ejecutables."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = [".gitignore", "LICENSE", "README.md", "PDFModder.spec", "pyproject.toml",
              "requirements.txt", "requirements-dev.txt", "run_pdfmodder.py"]
DIRECTORIES = ["pdfmodder", "scripts", "tests", "docs", "examples", "assets", "installer"]
IGNORED = {"__pycache__", ".pytest_cache", ".git", ".venv", "build", "dist", "output", "releases"}


def prepare():
    paths = [ROOT / name for name in ROOT_FILES]
    for name in DIRECTORIES:
        paths.extend(path for path in (ROOT / name).rglob("*") if path.is_file())
    selected = []
    for path in sorted(set(paths)):
        relative = path.relative_to(ROOT)
        if set(relative.parts) & IGNORED or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError("No se admite un enlace externo: " + str(relative))
        if path.suffix.lower() in {".exe", ".zip", ".dll", ".pyd", ".key", ".pem", ".log"}:
            raise RuntimeError("Archivo no previsto para publicar: " + str(relative))
        selected.append((path, relative.as_posix()))
    target = ROOT / "releases/v0.8/PDFModder-v0.8-proyecto-actual.zip"
    rows = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in selected:
            content = path.read_bytes()
            archive.writestr("PDFModder/" + name, content)
            rows.append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n", encoding="ascii")
    inventory = {"project": "PDF Modder 0.8", "files": rows, "archive_sha256": digest,
                 "published_to_github": False}
    (target.parent / "PROYECTO-ACTUAL.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"source_archive": str(target), "files": len(rows), "bytes": target.stat().st_size,
                      "sha256": digest, "published_to_github": False}, ensure_ascii=False))


if __name__ == "__main__":
    prepare()
