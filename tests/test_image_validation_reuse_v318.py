"""Image writes reuse exact candidate evidence while validating every text scope."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from pdfmodder import tagged, validation
from pdfmodder.image_transform_v160 import transform_image_instance_pdf
from pdfmodder.media import add_image_pdf, image_items
from pdfmodder.model import EditError
from pdfmodder.tagged_image_v160 import TaggedImageTransform
from pdfmodder.tagged_reuse_v318 import LazyPageOperationsV318
from pdfmodder.worker import Session
from tagged_corpus import make_tagged_pdf
from test_media import picture


@pytest.fixture(autouse=True)
def private_evidence():
    tagged.clear_readonly_cache()
    yield
    tagged.clear_readonly_cache()


def test_exact_inventory_bytes_reuse_checked_source_without_reserialization(monkeypatch):
    source = make_tagged_pdf()
    structure = tagged.analyze_readonly(source)
    def unexpected(*args, **kwargs):
        pytest.fail('Exact source bytes already have an independently checked read-only structure')
    monkeypatch.setattr(tagged, 'analyze', unexpected)
    with fitz.open(stream=source, filetype='pdf') as document:
        monkeypatch.setattr(document, 'tobytes', unexpected)
        items = image_items(document, 0, source_data=source)
    assert items[0]['editable'] and items[0]['tagged_geometry']
    assert tagged.analyze_readonly(source) is structure


def test_transform_keeps_unaffected_page_ast_lazy_and_checks_bound_candidate_scopes(monkeypatch):
    source = make_tagged_pdf()
    structure = tagged.analyze_readonly(source)
    ordinary_get = LazyPageOperationsV318._get
    def get(self):
        if self.number == 1:
            pytest.fail('The exact unchanged control page must not materialize its AST')
        return ordinary_get(self)
    monkeypatch.setattr(LazyPageOperationsV318, '_get', get)
    monkeypatch.setattr(validation, 'ContentStream',
        lambda *args, **kwargs: pytest.fail('Image scope checks must use the bound candidate operations'))
    with tagged.pin_source_analysis(source):
        output, report = transform_image_instance_pdf(source, 0, '0', (55, 215, 135, 275))
        candidate = tagged.analyze_readonly(output)
    assert report['verified'] and report['accessibility']['reading_order_preserved']
    assert candidate.reader is not structure.reader
    assert isinstance(candidate.operations[1], LazyPageOperationsV318)
    assert candidate.operations[1]._operations is None


def test_transform_rejects_structure_from_a_different_exact_revision():
    source = make_tagged_pdf()
    structure = tagged.analyze_readonly(source)
    with pytest.raises(EditError, match='versión anterior'):
        TaggedImageTransform(source+b'\n% different revision\n', 0, {}, structure=structure)


def test_transform_checks_global_tags_even_when_page_inputs_are_unchanged():
    source = make_tagged_pdf()
    with fitz.open(stream=source, filetype='pdf') as document:
        item = image_items(document, 0, source_data=source)[0]
    guard = TaggedImageTransform(source, 0, item)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    writer.root_object[NameObject('/Lang')] = TextStringObject('en-GB')
    output = BytesIO(); writer.write(output)
    with pytest.raises(EditError, match='propiedades accesibles'):
        guard.validate(output.getvalue())


def test_final_image_candidate_with_new_control_page_scope_error_cannot_commit(tmp_path, monkeypatch):
    from pdfmodder import media
    path = tmp_path/'tagged.pdf'; path.write_bytes(make_tagged_pdf())
    session = Session(path, history_dir=tmp_path/'history', config_path=tmp_path/'fonts.json')
    original = session.history.current
    ordinary_write = media._write_image_transaction
    def corrupted(document):
        candidate = ordinary_write(document)
        with fitz.open(stream=candidate, filetype='pdf') as target:
            extra = target.get_new_xref(); target.update_object(extra, '<<>>')
            target.update_stream(extra, b'ET')
            references = [*target[1].get_contents(), extra]
            target.xref_set_key(target[1].xref, 'Contents', '['+' '.join(f'{xref} 0 R' for xref in references)+']')
            return ordinary_write(target)
    monkeypatch.setattr(media, '_write_image_transaction', corrupted)
    try:
        with pytest.raises(EditError, match='ET sin apertura'):
            session.image_operation('add', 0, rect=(160, 260, 200, 284), image_bytes=picture(),
                                     accessibility_order='page_end', alt_text='Figura nueva')
        assert session.history.current == original and session.history.index == 0
        assert session.pending is None and path.read_bytes() == original
    finally:
        session.close()


@pytest.mark.parametrize('suffix', [b'ET', b'BT', b'BT BT ET ET'])
def test_image_addition_rejects_malformed_control_page_even_with_identical_page_proof(suffix):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page = writer.pages[1]
    contents = page.raw_get('/Contents')
    contents = list(contents) if isinstance(contents, ArrayObject) else [contents]
    extra = DecodedStreamObject(); extra.set_data(suffix)
    page[NameObject('/Contents')] = ArrayObject([*contents, writer._add_object(extra)])
    output = BytesIO(); writer.write(output)
    source = output.getvalue()
    tagged.analyze_readonly(source)
    with tagged.pin_source_analysis(source), pytest.raises(EditError, match='BT|ET'):
        add_image_pdf(source, 0, picture(), (160, 260, 200, 284),
                      accessibility_order='page_end', alt_text='Figura nueva')


def test_image_addition_rejects_malformed_invoked_form_scope():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    inner = DecodedStreamObject()
    inner.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                  NameObject('/BBox'): ArrayObject([NumberObject(n) for n in (0, 0, 100, 100)])})
    inner.set_data(b'ET')
    outer = DecodedStreamObject(); outer.update(dict(inner))
    outer[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'):
        DictionaryObject({NameObject('/Inner'): writer._add_object(inner)})})
    outer.set_data(b'/Inner Do')
    page = writer.pages[1]
    page['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Outer'): writer._add_object(outer)})
    extra = DecodedStreamObject(); extra.set_data(b'/Outer Do')
    page[NameObject('/Contents')] = ArrayObject([*page.raw_get('/Contents'), writer._add_object(extra)])
    output = BytesIO(); writer.write(output)
    source = output.getvalue()
    with pytest.raises(EditError, match='Form /Inner.*ET sin apertura'):
        add_image_pdf(source, 0, picture(), (160, 260, 200, 284),
                      accessibility_order='page_end', alt_text='Figura nueva')


def test_inventory_rejects_stale_source_bytes_before_using_warm_cached_items(tmp_path):
    path = tmp_path/'tagged.pdf'; path.write_bytes(make_tagged_pdf())
    session = Session(path, history_dir=tmp_path/'history', config_path=tmp_path/'fonts.json')
    try:
        assert session.page(0)['images']
        source = session.history.current
        revision = session.history.revision
        document = session._document(source, revision)
        with pytest.raises(EditError, match='versión anterior'):
            session._page_inventory_v318(document, revision, 0, ('images',),
                                         source_data=source+b'\n% stale bytes\n')
        assert session.history.current == source and session.pending is None
    finally:
        session.close()
