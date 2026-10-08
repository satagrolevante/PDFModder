"""Re-edit native text without letting redaction damage its BT/ET scopes."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import atomic_save, edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.objects_v300 import object_graph
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, move_rich_pdf, selection_payload
from pdfmodder.validation import assert_text_object_structure, trace_chars, validate_transition


def selected(data, text):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
    start = ''.join(g.text for g in model.glyphs).index(text)
    return [g.id for g in model.glyphs[start:start+len(text)]]


def replace_contents(doc, streams):
    refs = []
    for content in streams:
        ref = doc.get_new_xref()
        doc.update_object(ref, '<<>>')
        doc.update_stream(ref, content)
        refs.append(ref)
    doc.xref_set_key(doc[0].xref, 'Contents', '['+' '.join(f'{ref} 0 R' for ref in refs)+']')


def test_rich_move_save_reopen_and_panel_reedit_preserve_text_scopes(tmp_path):
    before = (Path(__file__).parents[1]/'examples/digital.pdf').read_bytes()
    ids = selected(before, '10/09/2026')
    payload = selection_payload(before, 0, ids)
    # Preserve all source runs just as the on-page editor does.
    runs = [dict(run) for run in payload['runs']]
    runs[0]['text'] = '11'
    rich, _ = edit_rich_pdf(before, RichTextRequest(0, ids, runs, rect=payload['rect'],
                                                   auto_width=True, auto_height=True))
    moved, _ = move_rich_pdf(rich, EditRequest(0, selected(rich, '11/09/2026'), dx=12, dy=10))
    path = tmp_path/'edited.pdf'
    atomic_save(moved, path)
    reopened = path.read_bytes()
    output, report = edit_pdf(reopened, EditRequest(0, selected(reopened, '11/09/2026'),
                                                    text='12/09/2026', auto_width=True))
    assert report['verified'] and report['native_panel']
    assert_text_object_structure(output)
    assert object_graph(output, 0)['items']
    reader = PdfReader(BytesIO(output), strict=True)
    assert '12/09/2026' in reader.pages[0].extract_text()
    assert '11/09/2026' not in reader.pages[0].extract_text()
    assert '10/09/2026' in reader.pages[1].extract_text()


def test_external_text_wrappers_work_without_pdfmodder_metadata():
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=200)
        page.insert_font(fontname='helv')
        widget = fitz.Widget()
        widget.field_name, widget.field_value = 'Retained', 'Original value'
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect = fitz.Rect(220, 100, 380, 140)
        page.add_widget(widget)
        replace_contents(doc, [b'BT /helv 12 Tf 1 0 0 1 35 150 Tm '
            b'q 1 0 0 1 0 0 cm (DATE 11) Tj Q ET\n'
            b'BT /helv 12 Tf 1 0 0 1 35 50 Tm (NEIGHBOUR) Tj ET'])
        data = doc.tobytes()
    output, report = edit_pdf(data, EditRequest(0, selected(data, 'DATE 11'), text='DATE 1E', auto_width=True))
    assert report['verified'] and report['native_panel']
    assert_text_object_structure(output)
    with fitz.open(stream=output, filetype='pdf') as doc:
        assert 'DATE 1E' in doc[0].get_text() and 'NEIGHBOUR' in doc[0].get_text()
        assert [(w.field_name, w.field_value) for w in doc[0].widgets()] == [('Retained', 'Original value')]


@pytest.mark.parametrize('content,reason', [(b'ET', 'ET sin apertura'),
    (b'BT BT ET ET', 'BT anidados'), (b'BT', 'BT sin cierre')])
def test_malformed_text_scopes_rejected_by_transaction_validator(content, reason):
    with fitz.open() as doc:
        doc.new_page(width=100, height=100)
        replace_contents(doc, [b''])
        before = doc.tobytes()
        expected = trace_chars(doc[0])
        replace_contents(doc, [content])
        after = doc.tobytes()
    with pytest.raises(EditError, match=reason):
        validate_transition(before, after, 0, expected, [])


def test_text_scope_may_cross_page_content_streams():
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        page.insert_text((20, 40), 'VISIBLE', fontsize=10)
        source = page.read_contents()
        before = doc.tobytes()
        expected = trace_chars(page)
        split = source.index(b'ET')
        replace_contents(doc, [source[:split], source[split:]])
        after = doc.tobytes()
    assert_text_object_structure(after)
    assert validate_transition(before, after, 0, expected, [])['verified']


def test_only_invoked_form_text_scopes_are_checked():
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        ref = doc.get_new_xref()
        doc.update_object(ref, '<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << >> >>')
        doc.update_stream(ref, b'ET')
        doc.xref_set_key(page.xref, 'Resources', f'<< /XObject << /Invalid {ref} 0 R >> >>')
        replace_contents(doc, [b'BT ET'])
        unused = doc.tobytes()
        replace_contents(doc, [b'/Invalid Do'])
        used = doc.tobytes()
    assert_text_object_structure(unused)
    with pytest.raises(EditError, match='Form /Invalid.*ET sin apertura'):
        assert_text_object_structure(used)


def test_empty_page_and_form_without_resources_use_valid_page_context():
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        assert_text_object_structure(doc.tobytes())  # No /Contents at all.
        refs = []
        for content in (b'BT ET', b'/Inner Do'):
            ref = doc.get_new_xref()
            doc.update_object(ref, '<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] >>')
            doc.update_stream(ref, content)
            refs.append(ref)
        doc.xref_set_key(page.xref, 'Resources',
            f'<< /XObject << /Inner {refs[0]} 0 R /Outer {refs[1]} 0 R >> >>')
        replace_contents(doc, [b'/Outer Do'])
        assert_text_object_structure(doc.tobytes())
