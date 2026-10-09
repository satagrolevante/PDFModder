"""Unchanged page graphs can also prove unchanged marked-content text."""
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ByteStringObject, ContentStream, NameObject, TextStringObject
import pytest

from pdfmodder.model import EditError
from pdfmodder.tagged import TaggedEdit, TaggedStructure, analyze
from tagged_corpus import make_tagged_pdf
from test_engine import select


def guard(source):
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    return TaggedEdit(analyze(source), 0, model, chosen, chosen, chosen, True)


def test_identical_control_page_needs_no_second_glyph_probe(monkeypatch):
    from pdfmodder import tagged
    source = make_tagged_pdf()
    checked = guard(source)
    probed = []
    analyzed = []
    original = TaggedStructure.glyph_contexts
    analyze_output = tagged.analyze_readonly

    def record_analysis(data):
        analyzed.append(data)
        return analyze_output(data)

    def record(self, page, model):
        probed.append(page)
        return original(self, page, model)

    monkeypatch.setattr(TaggedStructure, 'glyph_contexts', record)
    monkeypatch.setattr(tagged, 'analyze_readonly', record_analysis)
    assert checked.validate(source)['logical_text_verified']
    assert probed == [0]
    assert analyzed == [source]


def test_changed_control_text_still_requires_and_fails_logical_validation():
    source = make_tagged_pdf()
    checked = guard(source)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    contents = ContentStream(writer.pages[1]['/Contents'], writer)
    for args, operator in contents.operations:
        if operator in (b'Tj', b'TJ'):
            strings = args if operator == b'Tj' else args[0]
            position = next(i for i, value in enumerate(strings) if isinstance(value, (str, bytes)))
            strings[position] = ByteStringObject(b'ALTERADO')
            break
    else:
        pytest.fail('Control fixture lacks native text')
    writer.pages[1][NameObject('/Contents')] = writer._add_object(contents)
    output = BytesIO(); writer.write(output)
    with pytest.raises(EditError, match='texto lógico'):
        checked.validate(output.getvalue())


def test_global_accessible_semantics_are_checked_even_when_page_content_matches():
    source = make_tagged_pdf()
    checked = guard(source)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    paragraph = writer.root_object['/StructTreeRoot']['/K']['/K'][0].get_object()
    paragraph[NameObject('/Alt')] = TextStringObject('Unexpected alternate text')
    output = BytesIO(); writer.write(output)
    with pytest.raises(EditError, match='cambios ajenos'):
        checked.validate(output.getvalue())
