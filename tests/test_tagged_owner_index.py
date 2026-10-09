"""A global accessible text value keeps all of its cross-page owners."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest
from tagged_corpus import make_tagged_pdf


def test_document_actualtext_cannot_be_rewritten_as_one_page_fragment():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    document = writer.root_object['/StructTreeRoot']['/K'].get_object()
    document[NameObject('/ActualText')] = TextStringObject('Logical text spanning both pages')
    output = BytesIO(); writer.write(output)
    source = output.getvalue()
    with fitz.open(stream=source, filetype='pdf') as pdf:
        model = extract_page(pdf, 0, source)
    ids = [g.id for g in model.glyphs if abs(g.origin[1] - 100) < .03 and g.origin[0] >= 99.9]
    assert ''.join(g.text for g in model.selected(ids)) == '10/09/2026'
    with pytest.raises(EditError, match='ActualText abarca contenido fuera'):
        edit_pdf(source, EditRequest(0, ids, text='11/09/2026', revision=model.revision))
