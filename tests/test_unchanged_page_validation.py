"""Graph identity bypasses raster work only on unedited, identical pages."""
import pymupdf as fitz
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError
from pdfmodder import richtext, validation


def document():
    with fitz.open() as doc:
        for text in ('Edited page', 'Control page'):
            doc.new_page(width=200, height=150).insert_text((25, 50), text)
        return doc.tobytes()


def validate(kind, source, output):
    with fitz.open(stream=source, filetype='pdf') as doc:
        if kind == 'native':
            return validation.validate_transition(source, output, 0,
                                                  validation.trace_chars(doc[0]), ())
        model = extract_page(doc, 0, source)
    return richtext._validate(source, output, 0, model.glyphs, [], [], [], None)


@pytest.mark.parametrize('kind', ['native', 'rich'])
def test_only_unchanged_control_page_can_skip_rasterization(kind, monkeypatch):
    source = document()
    rendered = []
    original = validation.assert_pixels

    def record(before, after, *args, **kwargs):
        rendered.append(before.number)
        return original(before, after, *args, **kwargs)

    monkeypatch.setattr(validation, 'assert_pixels', record)
    report = validate(kind, source, source)
    assert report['verified']
    assert rendered == [0]
    assert report['pages'][1]['verification'] == 'identical_page_graph_sha256'
    assert report['pages'][1]['rasterized'] is False
    assert report['pages'][1]['pixel_measurements'] is False


@pytest.mark.parametrize('kind', ['native', 'rich'])
def test_altered_control_page_is_still_rejected(kind):
    source = document()
    with fitz.open(stream=source, filetype='pdf') as doc:
        doc[1].draw_rect((10, 80, 100, 100), fill=(1, 0, 0))
        damaged = doc.tobytes()
    with pytest.raises(EditError, match='vectores'):
        validate(kind, source, damaged)


@pytest.mark.parametrize('kind', ['native', 'rich'])
def test_uncertain_graph_keeps_full_validation(kind, monkeypatch):
    from pdfmodder.page_fingerprint import PageProof
    source = document()
    rendered = []
    original = validation.assert_pixels
    monkeypatch.setattr(PageProof, 'unchanged', lambda self, page: False)

    def record(before, after, *args, **kwargs):
        rendered.append(before.number)
        return original(before, after, *args, **kwargs)

    monkeypatch.setattr(validation, 'assert_pixels', record)
    assert validate(kind, source, source)['verified']
    assert rendered == [0, 1]
