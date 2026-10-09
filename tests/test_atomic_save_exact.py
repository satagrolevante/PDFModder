"""Saving persists an exact verified revision without another PDF rewrite."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from pdfmodder import engine
from pdfmodder.model import EditError


def pdf_bytes():
    with fitz.open() as document:
        document.new_page().insert_text((50, 75), 'Current verified revision')
        document.new_page().insert_text((50, 75), 'Control page')
        unused = document.get_new_xref()
        document.update_object(unused, '<< /Marker (Unreferenced but unchanged) >>')
        return document.tobytes(garbage=0, deflate=False)


def test_save_keeps_exact_bytes_and_never_rewrites_or_rasterizes(tmp_path, monkeypatch):
    data = pdf_bytes()
    original = tmp_path / 'original.pdf'; original.write_bytes(data)
    destination = tmp_path / 'saved.pdf'
    monkeypatch.setattr(engine, 'full_write', lambda *args: pytest.fail('Saving must not rewrite this revision'))
    monkeypatch.setattr(engine, 'validate_transition', lambda *args: pytest.fail('Identical bytes introduce no PDF transition'))
    monkeypatch.setattr(fitz.Page, 'get_pixmap', lambda *args, **kwargs: pytest.fail('Saving identical bytes must not rasterize pages'))
    assert engine.atomic_save(data, destination, original) == str(destination.resolve())
    assert destination.read_bytes() == data
    assert sha256(destination.read_bytes()).digest() == sha256(data).digest()
    assert original.read_bytes() == data
    assert b'Unreferenced but unchanged' in destination.read_bytes()
    assert len(PdfReader(destination, strict=True).pages) == 2


def test_tampered_temporary_file_preserves_previous_destination(tmp_path, monkeypatch):
    data = pdf_bytes(); destination = tmp_path / 'saved.pdf'
    previous = b'Previous destination contents'; destination.write_bytes(previous)
    mkstemp = engine.tempfile.mkstemp; fsync = engine.os.fsync
    temporary = []

    def capture(*args, **kwargs):
        descriptor, name = mkstemp(*args, **kwargs)
        temporary.append(name)
        return descriptor, name

    def tamper(descriptor):
        fsync(descriptor)
        # Still a readable PDF with the same pages; only byte integrity detects
        # this unexpected addition before replacing the existing destination.
        with open(temporary[0], 'ab') as stream:
            stream.write(b'\n% unexpected extra data\n')

    monkeypatch.setattr(engine.tempfile, 'mkstemp', capture)
    monkeypatch.setattr(engine.os, 'fsync', tamper)
    with pytest.raises(EditError, match='integridad'):
        engine.atomic_save(data, destination)
    assert destination.read_bytes() == previous
    assert not list(tmp_path.glob('.pdfmodder-*'))


def test_failed_atomic_replace_preserves_previous_destination(tmp_path, monkeypatch):
    destination = tmp_path / 'saved.pdf'; destination.write_bytes(b'Previous contents')
    def fail(*args):
        raise OSError('Destination is locked')
    monkeypatch.setattr(engine.os, 'replace', fail)
    with pytest.raises(OSError, match='locked'):
        engine.atomic_save(pdf_bytes(), destination)
    assert destination.read_bytes() == b'Previous contents'
    assert not list(tmp_path.glob('.pdfmodder-*'))


@pytest.mark.parametrize('linked', [False, True])
def test_original_and_hard_link_are_protected(tmp_path, linked):
    data = pdf_bytes(); original = tmp_path / 'original.pdf'; original.write_bytes(data)
    destination = original
    if linked:
        destination = tmp_path / 'link.pdf'
        engine.os.link(original, destination)
    with pytest.raises(EditError, match='original'):
        engine.atomic_save(data, destination, original)
    assert original.read_bytes() == data
    assert not list(tmp_path.glob('.pdfmodder-*'))


@pytest.mark.parametrize('content', [b'ET\n', b'BT\n', b'BT BT ET ET\n'])
def test_invalid_text_object_scopes_cannot_be_saved(tmp_path, content):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf_bytes())))
    stream = DecodedStreamObject(); stream.set_data(content)
    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    destination = tmp_path / 'saved.pdf'; destination.write_bytes(b'Previous contents')
    with pytest.raises(EditError, match='BT|ET'):
        engine.atomic_save(output.getvalue(), destination)
    assert destination.read_bytes() == b'Previous contents'
    assert not list(tmp_path.glob('.pdfmodder-*'))
