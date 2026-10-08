"""Packaging must preserve attribution when Qt wheels omit notice files."""
from email.message import Message
from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from scripts import collect_licenses as collector


class Distribution:
    def __init__(self, root, name="PySide6", version="6.10.2", *, notice=False, license=None):
        self.root, self.version = root, version
        self.metadata = Message()
        for key, value in (("Name", name), ("Version", version),
                           ("License", license or collector.QT_LICENSE_DECLARATION),
                           ("Author-email", "Qt for Python Team <pyside@qt-project.org>"),
                           ("Project-URL", "Repository, https://code.qt.io/cgit/pyside/pyside-setup.git/")):
            self.metadata[key] = value
        self.raw = self.metadata.as_string()
        self.files = [Path("wheel/LICENSE.txt")] if notice else []
        if notice:
            path = self.locate_file(self.files[0])
            path.parent.mkdir(parents=True)
            path.write_text("Synthetic upstream notice retained verbatim.\n", encoding="utf-8")

    def locate_file(self, file):
        return self.root / file

    def read_text(self, name):
        return self.raw if name == "METADATA" else None


@pytest.fixture
def project(tmp_path, monkeypatch):
    source_root = collector.ROOT
    root = tmp_path / "project"
    (root / "docs/licenses").mkdir(parents=True)
    for filename, _, _ in collector.QT_STANDARD_LICENSES:
        shutil.copy2(source_root / "docs/licenses" / filename, root / "docs/licenses" / filename)
    (root / "LICENSE").write_text("Synthetic application licence fixture.\n", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.mkdir()
    (interpreter / "LICENSE.txt").write_text("Synthetic interpreter licence fixture.\n", encoding="utf-8")
    monkeypatch.setattr(collector, "ROOT", root)
    monkeypatch.setattr(collector, "sys", SimpleNamespace(base_prefix=str(interpreter), version="test"))
    return root


def collect_one(root, monkeypatch, distribution, expected=None):
    monkeypatch.setattr(collector.metadata, "distributions", lambda: [distribution])
    monkeypatch.setattr(collector, "EXPECTED_RUNTIME", expected or {
        collector.normalized(distribution.metadata["Name"]): distribution.version,
    })
    destination = root / "build/delivery"
    collector.collect(destination)
    inventory = json.loads((destination / "licenses/INVENTARIO.json").read_text(encoding="utf-8"))
    return destination / "licenses", inventory["packages"][0]


@pytest.mark.parametrize("name", ["PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6"])
def test_exact_qt_wheel_without_notices_keeps_attribution_and_verified_texts(project, monkeypatch, name):
    distribution = Distribution(project, name)
    licenses, row = collect_one(project, monkeypatch, distribution)
    assert row["standard_license_fallback"] and len(row["notice_files"]) == 3
    metadata = licenses / row["metadata_file"]["path"]
    assert metadata.read_text(encoding="utf-8") == distribution.raw
    assert sha256(metadata.read_bytes()).hexdigest() == row["metadata_file"]["sha256"]
    assert row["license"] == collector.QT_LICENSE_DECLARATION
    for notice in row["notice_files"]:
        actual = (licenses / notice["path"]).read_bytes()
        assert actual == (project / notice["source"]).read_bytes()
        assert sha256(actual).hexdigest() == notice["sha256"]
        assert sha256(actual.replace(b"\r\n", b"\n")).hexdigest() == notice["lf_normalized_sha256"]
        assert notice["source_url"].startswith("https://www.gnu.org/licenses/")
        assert notice["provenance"] == "standard_text_fallback_for_missing_qt_6.10.2_wheel_notices"


def test_windows_checkout_crlf_keeps_exact_inventory_hash(project, monkeypatch):
    for path in (project / "docs/licenses").iterdir():
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    licenses, row = collect_one(project, monkeypatch, Distribution(project))
    assert all(b"\r\n" in (licenses / notice["path"]).read_bytes() for notice in row["notice_files"])
    assert all(notice["sha256"] != notice["lf_normalized_sha256"] for notice in row["notice_files"])


def test_other_runtime_without_notice_still_blocks_packaging(project, monkeypatch):
    with pytest.raises(RuntimeError, match="No se encontró el texto de licencia de pymupdf"):
        collect_one(project, monkeypatch, Distribution(project, "PyMuPDF", "1.26.7"))


def test_unexpected_qt_version_still_blocks_before_fallback(project, monkeypatch):
    with pytest.raises(RuntimeError, match="Entorno no reproducible"):
        collect_one(project, monkeypatch, Distribution(project, version="6.10.3"), {"pyside6": "6.10.2"})


def test_other_qt_version_has_no_automatic_notice_exception(project, monkeypatch):
    with pytest.raises(RuntimeError, match="No se encontró el texto de licencia de pyside6"):
        collect_one(project, monkeypatch, Distribution(project, version="6.10.3"))


def test_unrecognized_qt_license_metadata_cannot_use_fallback(project, monkeypatch):
    with pytest.raises(RuntimeError, match="Los metadatos no identifican"):
        collect_one(project, monkeypatch, Distribution(project, license="Unverified licence declaration"))


@pytest.mark.parametrize("damage", ["missing", "modified"])
def test_missing_or_modified_standard_text_blocks_packaging(project, monkeypatch, damage):
    path = project / "docs/licenses/LGPL-3.0.txt"
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"Changed licence text.\n")
    with pytest.raises(RuntimeError, match="texto estándar"):
        collect_one(project, monkeypatch, Distribution(project))


def test_real_wheel_notice_is_preserved_without_using_fallback(project, monkeypatch):
    distribution = Distribution(project, notice=True)
    shutil.rmtree(project / "docs/licenses")
    licenses, row = collect_one(project, monkeypatch, distribution)
    assert not row["standard_license_fallback"] and len(row["notice_files"]) == 1
    notice = row["notice_files"][0]
    assert "provenance" not in notice
    assert (licenses / notice["path"]).read_bytes() == distribution.locate_file(distribution.files[0]).read_bytes()
