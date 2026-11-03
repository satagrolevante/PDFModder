from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject
import pytest

from tagged_corpus import make_tagged_pdf
from test_signing_v160 import certificate
from pdfmodder.model import EditError
from pdfmodder.signing import sign_pdf, verify_signed_pdf, atomic_save_signed
from pdfmodder.tagged import analyze_readonly
from pdfmodder.tagged_signature_v318 import assert_tagged_signature_v318
from pdfmodder.validation_evidence_v318 import ValidationEvidenceCacheV318, validation_scope_v318


@pytest.mark.parametrize('options', [{}, {'include_objr': True, 'named_properties': True}])
def test_visible_signature_adds_accessible_form_preserves_tags_and_crypto(certificate, options):
    data = make_tagged_pdf(**options)
    spec = {'page': 0, 'rect': [40, 270, 400, 395]}
    signed, report = sign_pdf(data, certificate, 'test-only', visible_signature=spec)
    assert verify_signed_pdf(signed)['cryptographic_integrity']
    reader = PdfReader(BytesIO(signed), strict=True)
    widget = reader.pages[0]['/Annots'][-1].get_object()
    assert widget['/FT'] == '/Sig'
    structure = analyze_readonly(signed)
    key = int(widget['/StructParent'])
    node = structure.parents[key].get_object()
    assert node['/S'] == '/Form'
    assert node['/Alt'] == 'Firma digital del documento'
    assert node['/K']['/Obj']['/T'] == widget['/T']
    with fitz.open(stream=data) as before, fitz.open(stream=signed) as after:
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[1].get_text() == after[1].get_text()
    # A valid newly added Form cannot hide an unrelated accessible edit.
    writer = PdfWriter(clone_from=reader)
    tree = writer.root_object['/StructTreeRoot']
    tree[NameObject('/Lang')] = TextStringObject('unrelated change')
    out = BytesIO(); writer.write(out)
    with pytest.raises(EditError, match='modificado'):
        assert_tagged_signature_v318(data, out.getvalue(), {
            'page': 0, 'parent_key': key, 'field_name': report['field_name']})


def test_exact_signed_bytes_reuse_crypto_verification_but_tamper_does_not(certificate, tmp_path, monkeypatch):
    import pdfmodder.signing as signing
    data = make_tagged_pdf()
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        signed, report = sign_pdf(data, certificate, 'test-only')
        original = signing.verify_signed_pdf
        def fail(*args, **kwargs):
            pytest.fail('Exact verified signature was already checked')
        monkeypatch.setattr(signing, 'verify_signed_pdf', fail)
        atomic_save_signed(signed, tmp_path / 'signed.pdf', certificate_sha256=report['certificate_sha256'])
        monkeypatch.setattr(signing, 'verify_signed_pdf', original)
        with pytest.raises(EditError):
            atomic_save_signed(signed + b'\n% bad', tmp_path / 'tampered.pdf', certificate_sha256=report['certificate_sha256'])
        assert not (tmp_path / 'tampered.pdf').exists()


def test_repeated_signing_reuses_prepared_revision_without_rewrite(certificate, monkeypatch):
    import pdfmodder.engine as engine
    calls = []
    original = engine.transaction_write_v318
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(engine, 'transaction_write_v318', counted)
    data = make_tagged_pdf()
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        first, _ = sign_pdf(data, certificate, 'test-only')
        second, _ = sign_pdf(data, certificate, 'test-only', reason='Otra copia')
        assert len(calls) == 1
        assert first != second
        assert verify_signed_pdf(first)['cryptographic_integrity']
        assert verify_signed_pdf(second)['cryptographic_integrity']


def test_tagged_document_ui_offers_visible_certificate_signing(tmp_path, monkeypatch):
    import pdfmodder.worker as worker
    import pdfmodder.signing as signing
    source = tmp_path / 'tagged.pdf'
    source.write_bytes(make_tagged_pdf())
    session = worker.Session(source, config_path=tmp_path / 'fonts.json', history_dir=tmp_path)
    try:
        monkeypatch.setattr(worker, '_session', session)
        monkeypatch.setattr(signing, 'list_signing_certificates', lambda: {'certificates': []})
        listing = worker._dispatch_command('list_signing_certificates')
        assert not listing.get('visible_signature_error')
        assert len(listing['pages']) == 2
    finally:
        session.close()
