"""Real PDF transactions; no private invoice is included in the source tree."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from pdfmodder.clipping import _signature
from pdfmodder.engine import extract_page
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload


VISIBLE = 'ALFA BETA ORG'
FULL = VISIBLE+'ANIC'


def document(*, split=False, other_scope=False, rotation=0, prefix=False):
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=220)
        start = 30
        text = ('XX ' if prefix else '')+FULL
        if split:
            page.insert_text((start, 90), text[:9], fontname='cour', fontsize=12)
            page.insert_text((start+9*7.2, 90), text[9:], fontname='cour', fontsize=12)
        else:
            page.insert_text((start, 90), text, fontname='cour', fontsize=12)
        glyphs = [c for s in page.get_texttrace() for c in s['chars']]
        end = glyphs[-5][2][0]+5.0  # Clip the G; ANIC is wholly hidden.
        left = start+3*7.2 if prefix else 25
        contents = b'\n'.join(doc.xref_stream(x) for x in page.get_contents())
        stream = doc.get_new_xref(); doc.update_object(stream, '<<>>')
        clip = f'{left} 126 {end-left} 20 re W n\n'.encode()
        doc.update_stream(stream, b'q '+clip+contents+b'\nQ')
        page.set_contents(stream)
        if other_scope:
            page.insert_text((end+10, 90), 'HIDDEN OTHER', fontname='cour', fontsize=12)
            x = page.get_contents()[-1]
            doc.update_stream(x, b'q '+clip+doc.xref_stream(x)+b'\nQ')
        page.draw_line((end+1, 70), (end+1, 110), color=(0, 0, .5))
        page.insert_text((220, 90), 'NEIGHBOR', fontsize=12)
        page.set_rotation(rotation)
        doc.new_page(width=420, height=220).insert_text((30, 50), 'OTHER PAGE')
        return doc.tobytes()


def request(data, text, *, selection=VISIBLE):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
    joined = ''.join(g.text for g in model.glyphs)
    start = joined.index(selection)
    ids = [g.id for g in model.glyphs[start:start+len(selection)]]
    payload = selection_payload(data, 0, ids)
    return RichTextRequest(0, ids, [dict(payload['runs'][0], text=text)],
        rect=payload['rect'], revision=payload['revision'], auto_width=True, auto_height=True)


def trace(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return ''.join(chr(c[0]) for s in doc[0].get_texttrace() for c in s['chars'])


def assert_preserved(data, output):
    def clips(b):
        reader = PdfReader(BytesIO(b))
        return [(op, _signature(args)) for args, op in ContentStream(reader.pages[0].get_contents(), reader).operations
                if op in (b're', b'W', b'W*')]
    assert clips(data) == clips(output)
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        assert before.metadata == after.metadata
        assert before[0].rotation == after[0].rotation
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        before[0].set_rotation(0); after[0].set_rotation(0)
        # The source hidden suffix shares coordinates with this control area;
        # its removal must not change any paint beyond the original cell.
        assert before[0].get_pixmap(clip=(150, 65, 410, 120)).samples == after[0].get_pixmap(clip=(150, 65, 410, 120)).samples
        drawings = lambda p:[{k:v for k,v in d.items() if k!='seqno'} for d in p.get_drawings()]
        assert drawings(before[0]) == drawings(after[0])


@pytest.mark.parametrize('split,rotation,prefix', [(False,0,False),(True,0,False),(False,90,False),(False,0,True)])
@pytest.mark.parametrize('replacement', ['BETA', ''])
def test_complete_field_removes_hidden_codes_and_preserves_neighbors(split, rotation, prefix, replacement):
    data = document(split=split, rotation=rotation, prefix=prefix)
    output, report = edit_rich_pdf(data, request(data, replacement))
    assert report['verified'] and report['hidden_field_characters_removed'] == (7 if prefix else 4)
    assert trace(output) == replacement+'NEIGHBOR'
    assert 'ANIC' not in PdfReader(BytesIO(output)).pages[0].extract_text()
    assert_preserved(data, output)


@pytest.mark.parametrize('replacement', ['ALFA', ''])
def test_word_change_keeps_other_visible_and_hidden_text(replacement):
    data = document()
    output, report = edit_rich_pdf(data, request(data, replacement, selection='BETA'))
    assert report['verified'] and not report.get('hidden_field_characters_removed')
    assert trace(output) == 'ALFA '+replacement+' ORGANICNEIGHBOR'
    assert_preserved(data, output)


def test_equal_rectangles_in_separate_scopes_do_not_own_each_others_text():
    data = document(other_scope=True)
    output, report = edit_rich_pdf(data, request(data, 'BETA'))
    assert report['hidden_field_characters_removed'] == 4
    assert trace(output) == 'BETAHIDDEN OTHERNEIGHBOR'
    assert_preserved(data, output)


def test_new_overflow_stays_blocked_even_with_overlap_enabled():
    data = document()
    with pytest.raises(EditError, match='recorte'):
        edit_rich_pdf(data, replace(request(data, FULL*2), allow_overlap=True))


def test_reopen_and_edit_replacement_has_no_hidden_old_suffix():
    data = document()
    first, _ = edit_rich_pdf(data, request(data, 'BETA'))
    second, report = edit_rich_pdf(first, request(first, 'ALFA', selection='BETA'))
    assert report['verified'] and trace(second) == 'ALFANEIGHBOR'
    assert_preserved(data, second)
