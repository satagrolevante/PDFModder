"""Certificate artwork includes optional local handwriting without certifying."""
from datetime import datetime, timezone
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.model import EditError
from pdfmodder.signature_appearance import appearance_pdf
from pdfmodder.signing import preview_signature, sign_pdf, verify_signed_pdf
from test_signature_appearance import visible_certificate, source_document


def handwriting_png():
    image = Image.new('RGBA', (240, 90), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line([(10, 70), (30, 15), (50, 65), (85, 25), (110, 60),
               (150, 45), (200, 60), (230, 20)], fill=(0, 0, 0, 255), width=3)
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_handwriting_preview_and_signed_stamp_preserve_geometry_and_certificate_data(
        visible_certificate, rotation):
    path, der = visible_certificate
    original = source_document(rotation)
    rect = [95, 180, 455, 305]
    specification = {'page': 0, 'rect': rect, 'manual_signature_png': handwriting_png()}
    preview = preview_signature(original, path, 'test-only', visible_signature=specification)
    signed, report = sign_pdf(original, path, 'test-only', visible_signature=specification)
    assert preview['manual_signature'] is True
    assert report['visible_signature']['manual_signature'] is True
    assert verify_signed_pdf(signed)['cryptographic_integrity']
    assert 'manual_signature_png' not in report['visible_signature']
    assert 'María Núñez' in report['visible_signature']['text']
    assert 'Fecha:' in report['visible_signature']['text']
    with fitz.open(stream=original) as before, fitz.open(stream=signed) as after:
        assert after[0].rotation == rotation and after[0].cropbox == before[0].cropbox
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        old = before[0].get_pixmap(matrix=fitz.Matrix(2, 2))
        new = after[0].get_pixmap(matrix=fitz.Matrix(2, 2))
        a = np.frombuffer(old.samples, np.uint8).reshape(old.height, old.width, 3)
        b = np.frombuffer(new.samples, np.uint8).reshape(new.height, new.width, 3)
        changed = np.any(a != b, axis=2)
        changed[rect[1]*2:rect[3]*2, rect[0]*2:rect[2]*2] = False
        assert not changed.any(), 'The drawing changed pixels outside the signature rectangle'
        crop = after[0].get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(rect))
        shown = fitz.Pixmap(preview['appearance_png'])
        c = np.frombuffer(crop.samples, np.uint8).reshape(crop.height, crop.width, 3)
        p = np.frombuffer(shown.samples, np.uint8).reshape(shown.height, shown.width, 3)
        # Signing updates the time in the right column. The drawing must be
        # exactly the same as the public-key-only preview, at every rotation.
        assert np.array_equal(c[:, :int(crop.width*.4)], p[:, :int(crop.width*.4)])
        assert 'María' in after[0].get_text() and 'Fecha:' in after[0].get_text()
    artwork, details = appearance_pdf(der, 360, 125, datetime.now(timezone.utc),
                                      manual_signature_png=handwriting_png())
    with fitz.open(stream=artwork) as art:
        images = art[0].get_images(full=True)
        assert len(images) == 1 and images[0][1] > 0, 'The handwriting needs a transparency mask'
        assert 'María' in art[0].get_text() and 'TEST-2026-001' in art[0].get_text()


@pytest.mark.parametrize('operation', [preview_signature, sign_pdf])
def test_invalid_handwriting_is_rejected_before_private_key_access(monkeypatch, operation):
    import pdfmodder.signing as signing
    def no_key(*args, **kwargs):
        pytest.fail('Invalid handwriting must not trigger private-key access')
    monkeypatch.setattr(signing, '_windows_signer', no_key)
    monkeypatch.setattr(signing, 'list_signing_certificates', no_key)
    with pytest.raises(EditError, match='garabato'):
        operation(source_document(), certificate_thumbprint='AB'*20,
                  visible_signature={'page': 0, 'rect': [95, 180, 455, 305],
                                     'manual_signature_png': b'not a PNG'})


def test_invisible_signature_is_normal_approval_without_docmdp(visible_certificate):
    path, _ = visible_certificate
    original = source_document()
    signed, report = sign_pdf(original, path, 'test-only', visible_signature=None)
    reader = PdfReader(BytesIO(signed))
    assert reader.trailer['/Root'].get('/Perms') is None
    widget = reader.pages[0]['/Annots'][-1].get_object()
    signature = widget['/V'].get_object()
    assert not any(reference.get('/TransformMethod') == '/DocMDP'
                   for reference in signature.get('/Reference', []))
    assert report['visible_signature'] is None
    assert verify_signed_pdf(signed)['covers_entire_file']
    with fitz.open(stream=original) as before, fitz.open(stream=signed) as after:
        assert all(p.get_pixmap().samples == q.get_pixmap().samples for p, q in zip(before, after))
