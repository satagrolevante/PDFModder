"""Reuse parsed tags without weakening independent page/Form BT/ET guards."""
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
import pytest

from pdfmodder import validation
from pdfmodder.model import EditError
from pdfmodder.tagged import analyze
from tagged_corpus import make_tagged_pdf


def changed_pdf(suffix, form_kind=None):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page = writer.pages[0]
    original = page.get_contents().get_data()
    if form_kind:
        outer = DecodedStreamObject()
        outer.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                      NameObject('/BBox'): ArrayObject([NumberObject(n) for n in (0, 0, 100, 100)])})
        outer_ref = writer._add_object(outer)
        if form_kind == 'recursive':
            outer.set_data(b'/Outer Do')
            child = outer_ref
            name = '/Outer'
        else:
            inner = DecodedStreamObject()
            inner.update(dict(outer))
            inner.set_data(b'ET')
            child = writer._add_object(inner)
            name = '/Inner'
            outer.set_data(b'/Inner Do')
        outer[NameObject('/Resources')] = DictionaryObject({
            NameObject('/XObject'): DictionaryObject({NameObject(name): child})})
        page['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Outer'): outer_ref})
        suffix += b'\n/Outer Do'
    stream = DecodedStreamObject()
    stream.set_data(original+b'\n'+suffix)
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_bound_strict_structure_avoids_reparsing_pages(monkeypatch):
    data = make_tagged_pdf()
    structure = analyze(data)
    validation.assert_text_object_structure(data)
    monkeypatch.setattr(validation, 'ContentStream',
                        lambda *args: pytest.fail('Page operations were already parsed for these exact bytes'))
    validation.assert_text_object_structure(data, reader=structure.reader, tagged_structure=structure)


@pytest.mark.parametrize('suffix,reason', [(b'ET', 'ET sin apertura'),
                                          (b'BT', 'BT sin cierre'),
                                          (b'BT BT ET ET', 'BT anidados')])
def test_reuse_rejects_the_same_malformed_page_scopes(suffix, reason):
    data = changed_pdf(suffix)
    structure = analyze(data)
    for kwargs in ({}, {'reader': structure.reader, 'tagged_structure': structure}):
        with pytest.raises(EditError, match=reason):
            validation.assert_text_object_structure(data, **kwargs)


@pytest.mark.parametrize('kind,reason', [('invalid', 'Form /Inner.*ET sin apertura'),
                                        ('recursive', 'invocación recursiva')])
def test_reuse_still_checks_invoked_nested_forms(kind, reason):
    data = changed_pdf(b'', form_kind=kind)
    structure = analyze(data)
    for kwargs in ({}, {'reader': structure.reader, 'tagged_structure': structure}):
        with pytest.raises(EditError, match=reason):
            validation.assert_text_object_structure(data, **kwargs)


@pytest.mark.parametrize('supplied_reader', [False, True])
def test_stale_structure_and_reader_cannot_validate_new_revision(supplied_reader):
    structure = analyze(make_tagged_pdf())
    bad = changed_pdf(b'ET')
    kwargs = {'tagged_structure': structure}
    if supplied_reader:
        kwargs['reader'] = structure.reader
    with pytest.raises(EditError, match='ET sin apertura'):
        validation.assert_text_object_structure(bad, **kwargs)


def test_incomplete_page_binding_falls_back_to_parser(monkeypatch):
    data = make_tagged_pdf()
    structure = analyze(data)
    structure.operations.pop()
    original = validation.ContentStream
    parsed = []
    def parse(*args):
        parsed.append(True)
        return original(*args)
    monkeypatch.setattr(validation, 'ContentStream', parse)
    validation.assert_text_object_structure(data, reader=structure.reader, tagged_structure=structure)
    assert len(parsed) == len(structure.reader.pages)
