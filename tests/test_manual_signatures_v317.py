"""Named local artwork stays transparent, bounded and independent of PDFs."""
from io import BytesIO
import json

from PIL import Image, ImageDraw
import pytest

from pdfmodder.manual_signatures_v317 import (
    SignatureLibraryV317, normalise_manual_signature_png_v317,
)


def artwork():
    image = Image.new('RGBA', (180, 70), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(20, 50), (60, 15), (90, 55), (155, 25)],
                              fill=(0, 0, 0, 255), width=3)
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def test_named_signatures_survive_reopen_rename_and_remove(tmp_path):
    library = SignatureLibraryV317(tmp_path / 'firmas')
    first = library.add('  Firma  habitual ', artwork())
    second = library.add('Firma corta', artwork())
    reopened = SignatureLibraryV317(library.directory)
    assert [item['name'] for item in reopened.entries()] == ['Firma habitual', 'Firma corta']
    assert first['id'] != second['id']
    assert reopened.get(first['id'])['png'] == first['png']
    reopened.rename(second['id'], 'Firma de trabajo')
    reopened.remove(first['id'])
    assert reopened.entries()[0]['name'] == 'Firma de trabajo'
    assert not (library.directory / (first['id'] + '.png')).exists()
    with pytest.raises(ValueError, match='ya no'):
        reopened.get(first['id'])


def test_artwork_crops_canvas_and_preserves_only_black_alpha():
    png = normalise_manual_signature_png_v317(artwork())
    assert normalise_manual_signature_png_v317(png) == png
    with Image.open(BytesIO(png)) as image:
        assert image.mode == 'RGBA' and image.width < 180 and image.height < 70
        assert image.getchannel('A').getextrema() == (0, 255)
        assert all(image.getchannel(channel).getextrema() == (0, 0) for channel in 'RGB')


@pytest.mark.parametrize('value', [b'not an image', b'', b'X' * (4 * 1024 * 1024 + 1)])
def test_invalid_artwork_never_creates_a_manifest(tmp_path, value):
    library = SignatureLibraryV317(tmp_path / 'firmas')
    with pytest.raises(ValueError):
        library.add('Firma', value)
    assert not library.manifest.exists()


@pytest.mark.parametrize('mode,color', [('RGBA', (0, 0, 0, 0)), ('RGB', (255, 255, 255))])
def test_blank_or_opaque_artwork_is_rejected(mode, color):
    output = BytesIO()
    Image.new(mode, (50, 20), color).save(output, format='PNG')
    with pytest.raises(ValueError):
        normalise_manual_signature_png_v317(output.getvalue())


def test_corrupt_manifest_is_not_silently_replaced(tmp_path):
    library = SignatureLibraryV317(tmp_path)
    library.manifest.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError, match='conservan'):
        library.add('Firma', artwork())
    assert library.manifest.read_text() == '{broken'


def test_manifest_identifier_cannot_escape_library(tmp_path):
    library = SignatureLibraryV317(tmp_path / 'firmas')
    library.directory.mkdir()
    malicious = {'schema': 1, 'signatures': [{'id': '../outside', 'name': 'Otra'}]}
    library.manifest.write_text(json.dumps(malicious))
    with pytest.raises(ValueError):
        library.entries()
    with pytest.raises(ValueError):
        library.get('../outside')


def test_failed_manifest_write_preserves_old_collection(tmp_path, monkeypatch):
    library = SignatureLibraryV317(tmp_path)
    first = library.add('Primera', artwork())
    original_files = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    def fail(_records):
        raise OSError('write failure')
    monkeypatch.setattr(library, '_write', fail)
    with pytest.raises(OSError):
        library.add('Segunda', artwork())
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == original_files
    assert library.get(first['id'])['name'] == 'Primera'
