"""Rich candidates retain integrity without global stream deduplication."""
from io import BytesIO
import hashlib

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.draft_control_v305 import DraftCancelled, DraftControl, controlled_draft
from pdfmodder.richtext import _write_rich_transaction, edit_rich_pdf
from pdfmodder.engine import extract_page
from test_richtext_v09 import document, request


def test_candidate_returned_is_exactly_the_candidate_checked(monkeypatch):
    import pdfmodder.richtext as richtext
    source = document()
    req = request(source)
    req.runs = [dict(req.runs[0], text='Hola nuevo')]
    written, checked = [], []
    original_write = richtext._write_rich_transaction
    original_validate = richtext._validate

    def write(doc):
        candidate = original_write(doc)
        written.append(candidate)
        return candidate

    def validate(before, after, *args, **kwargs):
        checked.append(after)
        return original_validate(before, after, *args, **kwargs)

    def no_legacy_write(*_):
        pytest.fail('Rich editing must not run document-wide stream deduplication.')

    monkeypatch.setattr(richtext, '_write_rich_transaction', write)
    monkeypatch.setattr(richtext, '_validate', validate)
    monkeypatch.setattr(richtext, 'full_write', no_legacy_write)
    output, report = richtext.edit_rich_pdf(source, req)
    assert report['verified'] and written == checked == [output]
    assert len(PdfReader(BytesIO(output), strict=True).pages) == 2


def test_repeated_rich_edits_collect_obsolete_streams_and_bound_file_growth():
    source = document()
    digest = hashlib.sha256(source).hexdigest()
    current = source
    previous = 'Hola mundo'
    lengths, xrefs = [], []
    with fitz.open(stream=source, filetype='pdf') as original:
        unchanged_pixels = original[1].get_pixmap().samples
    for index in range(20):
        req = request(current, previous)
        replacement = 'Hola nuevo' if index % 2 == 0 else 'Hola mundo'
        req.runs = [dict(req.runs[0], text=replacement)]
        current, report = edit_rich_pdf(current, req)
        assert report['verified'] and report['pages'][1]['rasterized'] is False
        with fitz.open(stream=current, filetype='pdf') as doc:
            assert doc[0].get_text().count(replacement) == 1
            assert 'VECINO INTACTO' in doc[0].get_text()
            assert doc[1].get_pixmap().samples == unchanged_pixels
            xrefs.append(doc.xref_length())
        lengths.append(len(current))
        previous = replacement
    assert hashlib.sha256(source).hexdigest() == digest
    assert max(xrefs) - min(xrefs) <= 1
    # Content metadata and compensated cursors may grow; discarded streams and
    # their xref entries must not accumulate at every transaction.
    assert max(lengths) < lengths[0] + 12_000


def test_existing_filters_metadata_and_distinct_font_resources_survive():
    with fitz.open(stream=document(), filetype='pdf') as doc:
        doc.set_metadata({'title': 'Immutable resources', 'author': 'Synthetic fixture'})
        doc.set_xml_metadata('<fixture><value>preserved</value></fixture>')
        doc.set_toc([[1, 'First page', 1], [1, 'Second page', 2]])
        font = doc[0].get_fonts()[0][0]
        duplicate = doc.get_new_xref()
        doc.update_object(duplicate, doc.xref_object(font))
        resources = int(doc.xref_get_key(doc[0].xref, 'Resources')[1].split()[0])
        doc.xref_set_key(resources, 'Font/Duplicate', f'{duplicate} 0 R')
        source = doc.tobytes(garbage=0, deflate=True, no_new_id=True)
    with fitz.open(stream=source, filetype='pdf') as before:
        original_metadata = before.metadata
        original_xml = before.get_xml_metadata()
        original_toc = before.get_toc()
        original_streams = [before.xref_stream_raw(xref) for xref in range(1, before.xref_length())
                            if before.xref_is_stream(xref)]
        original_filters = [before.xref_get_key(xref, 'Filter') for xref in range(1, before.xref_length())
                            if before.xref_is_stream(xref)]
        output = _write_rich_transaction(before)
    with fitz.open(stream=output, filetype='pdf') as after:
        assert after.metadata == original_metadata
        assert after.get_xml_metadata() == original_xml
        assert after.get_toc() == original_toc
        streams = [after.xref_stream_raw(xref) for xref in range(1, after.xref_length())
                   if after.xref_is_stream(xref)]
        filters = [after.xref_get_key(xref, 'Filter') for xref in range(1, after.xref_length())
                   if after.xref_is_stream(xref)]
        assert streams == original_streams and filters == original_filters
    fonts = PdfReader(BytesIO(output), strict=True).pages[0]['/Resources']['/Font']
    assert fonts.raw_get('/helv').idnum != fonts.raw_get('/Duplicate').idnum


def test_superseded_before_serialization_aborts_without_writing(monkeypatch):
    import pdfmodder.richtext as richtext
    source = document()
    req = request(source)
    req.runs = [dict(req.runs[0], text='Hola nuevo')]
    control = DraftControl()
    ticket = control.ticket()
    original_write = richtext._write_rich_transaction
    candidates = []

    def supersede(doc):
        control.invalidate()
        result = original_write(doc)
        candidates.append(result)
        return result

    monkeypatch.setattr(richtext, '_write_rich_transaction', supersede)
    try:
        with pytest.raises(DraftCancelled), controlled_draft(ticket):
            richtext.edit_rich_pdf(source, req)
    finally:
        control.close()
    assert candidates == []


def test_resource_probe_propagates_cancellation_instead_of_hiding_it(monkeypatch):
    import pdfmodder.clipping as clipping
    source = document()
    with fitz.open(stream=source, filetype='pdf') as doc:
        model = extract_page(doc, 0)
    def cancelled(*_):
        raise DraftCancelled('obsolete')
    monkeypatch.setattr(clipping, 'operator_glyph_map', cancelled)
    with pytest.raises(DraftCancelled):
        clipping.annotate_font_resources(source, 0, model)


def test_repeated_scope_validation_reuses_only_proven_unchanged_pages(monkeypatch):
    from pdfmodder import validation
    from pdfmodder import analysis_reuse_v315
    from pdfmodder.page_fingerprint import PageProof
    validation.clear_text_scope_cache()
    source = document()
    validation.assert_text_object_structure(source, before_data=source,
                                             unchanged_pages=PageProof(source, source))
    with fitz.open(stream=source, filetype='pdf') as doc:
        doc[0].insert_text((35, 210), 'Added text')
        output = _write_rich_transaction(doc)
    parsed = []
    original = analysis_reuse_v315.ContentStream
    def count(*args):
        parsed.append(True)
        return original(*args)
    monkeypatch.setattr(analysis_reuse_v315, 'ContentStream', count)
    validation.assert_text_object_structure(output, before_data=source,
                                             unchanged_pages=PageProof(source, output))
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert len(parsed) == len(doc[0].get_contents())


@pytest.mark.parametrize('kind', ['stale', 'fake', 'budget'])
def test_scope_cache_never_trusts_stale_fake_or_overbudget_proofs(kind):
    from pdfmodder import validation
    from pdfmodder.page_fingerprint import PageProof
    from pdfmodder.model import EditError
    validation.clear_text_scope_cache()
    source = document()
    validation.assert_text_object_structure(source, before_data=source,
                                             unchanged_pages=PageProof(source, source))
    with fitz.open(stream=source, filetype='pdf') as doc:
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, doc[1].read_contents() + b'\nET')
        doc[1].set_contents(stream)
        bad = _write_rich_transaction(doc)
    if kind == 'stale':
        proof = PageProof(source, source)
    elif kind == 'fake':
        class FakeProof:
            def matches(self, *_):return True
            def report(self, *_):return {'fingerprint': next(iter(validation._verified_text_scope_graphs))}
        proof = FakeProof()
    else:
        proof = PageProof(source, bad, max_nodes=1)
    with pytest.raises(EditError, match='ET sin apertura'):
        validation.assert_text_object_structure(bad, before_data=source, unchanged_pages=proof)


def test_verified_page_scope_cache_does_not_hide_changed_invoked_form():
    from pdfmodder import validation
    from pdfmodder.page_fingerprint import PageProof
    from pdfmodder.model import EditError
    validation.clear_text_scope_cache()
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        form = doc.get_new_xref()
        doc.update_object(form, '<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources <<>> >>')
        doc.update_stream(form, b'BT ET')
        doc.xref_set_key(page.xref, 'Resources', f'<< /XObject << /Fixture {form} 0 R >> >>')
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, b'/Fixture Do')
        page.set_contents(stream)
        source = doc.tobytes(no_new_id=True)
        validation.assert_text_object_structure(source, before_data=source,
                                                unchanged_pages=PageProof(source, source))
        doc.update_stream(form, b'ET')
        bad = doc.tobytes(no_new_id=True)
    with pytest.raises(EditError, match='Form /Fixture.*ET sin apertura'):
        validation.assert_text_object_structure(bad, before_data=source,
                                                unchanged_pages=PageProof(source, bad))


def test_cancelled_scope_validation_commits_no_partial_cache(monkeypatch):
    from pdfmodder import validation
    from pdfmodder.page_fingerprint import PageProof
    validation.clear_text_scope_cache()
    source = document()
    checkpoints = []
    def cancel_later():
        checkpoints.append(True)
        if len(checkpoints) == 3:
            raise DraftCancelled('obsolete')
    monkeypatch.setattr(validation, 'checkpoint', cancel_later)
    with pytest.raises(DraftCancelled):
        validation.assert_text_object_structure(source, before_data=source,
                                                unchanged_pages=PageProof(source, source))
    assert not validation._verified_text_scope_graphs


def test_verified_scope_cache_has_fixed_entry_budget(monkeypatch):
    from pdfmodder import validation
    from pdfmodder.page_fingerprint import PageProof
    validation.clear_text_scope_cache()
    monkeypatch.setattr(validation, '_TEXT_SCOPE_CACHE_LIMIT', 1)
    source = document()
    validation.assert_text_object_structure(source, before_data=source,
                                             unchanged_pages=PageProof(source, source))
    assert len(validation._verified_text_scope_graphs) == 1
    validation.clear_text_scope_cache()


def test_stale_supplied_reader_cannot_poison_verified_scope_cache():
    from pdfmodder import validation
    from pdfmodder.page_fingerprint import PageProof
    from pdfmodder.model import EditError
    validation.clear_text_scope_cache()
    source = document()
    with fitz.open(stream=source, filetype='pdf') as doc:
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, b'ET')
        doc[0].set_contents(stream)
        bad = doc.tobytes(no_new_id=True)
    for supplied in [PdfReader(BytesIO(source), strict=True), None]:
        with pytest.raises(EditError, match='ET sin apertura'):
            validation.assert_text_object_structure(bad, reader=supplied, before_data=bad,
                                                     unchanged_pages=PageProof(bad, bad))
        assert not validation._verified_text_scope_graphs
