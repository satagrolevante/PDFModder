"""Fast full rewrites remove obsolete objects while retaining resource aliases."""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader

from pdfmodder.engine import transaction_write_v318


def test_transaction_rewrite_keeps_id_filters_and_aliases_and_discards_history(tmp_path):
    path = tmp_path/'incremental.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((50, 70), 'Initial text')
        document.new_page().insert_text((50, 70), 'Control text')
        document.save(path)
    with fitz.open(path) as document:
        one = document.get_new_xref()
        document.update_object(one, '<<>>')
        document.update_stream(one, b'q\nQ\n')
        two = document.get_new_xref()
        document.update_object(two, '<<>>')
        document.update_stream(two, b'q\nQ\n')
        document.xref_set_key(document[0].xref, 'Contents', f'[{one} 0 R {two} 0 R]')
        document[1].set_contents(one)
        unused = document.get_new_xref()
        document.update_object(unused, '<< /Marker (Unreachable prior edit) >>')
        document.saveIncr()
    source = path.read_bytes()
    original = PdfReader(BytesIO(source), strict=True)
    assert '/Prev' in original.trailer
    assert b'Unreachable prior edit' in source
    with fitz.open(stream=source, filetype='pdf') as document:
        output = transaction_write_v318(document)
    result = PdfReader(BytesIO(output), strict=True)
    assert result.trailer['/ID'] == original.trailer['/ID']
    assert '/Prev' not in result.trailer
    assert b'Unreachable prior edit' not in output
    first, second = result.pages[0]['/Contents']
    # Level 2 retains the identity of two distinct equal streams and the
    # sharing of one stream across pages. Level 4 would merge the equal pair.
    assert first.idnum != second.idnum
    assert result.pages[1].raw_get('/Contents').idnum == first.idnum
    for before, after in zip(original.pages[0]['/Contents'], result.pages[0]['/Contents']):
        a, b = before.get_object(), after.get_object()
        assert a.get('/Filter') == b.get('/Filter')
        assert a._data == b._data
        assert a.get_data() == b.get_data()
    assert path.read_bytes() == source
