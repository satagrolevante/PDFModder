"""Tr=2 deletion removes one code's two paints while retaining its neighbours."""
from dataclasses import replace
from io import BytesIO
import hashlib

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, ByteStringObject, ContentStream, DictionaryObject,
                          FloatObject, NameObject, NumberObject)
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.paired_deletion_v304 import try_delete_paired_text
from pdfmodder.clipping import _signature
from tagged_corpus import make_tagged_pdf


def source_pdf(*, mode=2, curved=False, opacity=False):
    with fitz.open() as doc:
        page = doc.new_page(width=320, height=300)
        page.insert_text((45, 70), 'ALPHA WORD END TRAIL')
        page.insert_text((45, 200), 'UNTOUCHED')
        other = doc.new_page(width=320, height=300)
        other.insert_text((40, 60), 'SECOND PAGE')
        path = ('35 205 m 290 205 l 290 275 l 250 285 60 285 35 275 c h'
                if curved else '35 205 255 85 re')
        content = ('q .3 w 2 J 1 j 3 M [2 1] 0 d '
                   '.2 .4 .6 RG .8 .1 .2 rg '+('/GS1 gs ' if opacity else '')+
                   path+' W n BT /helv 12 Tf 1 Tc 2 Tw 85 Tz '+str(mode)+' Tr '
                   '1 0 0 1 45 230 Tm [(ALPHA WORD END) -40 ( TRAIL)] TJ ET Q '
                   'q BT /helv 12 Tf 0 Tr 0 Tc 0 Tw 100 Tz 0 0 0 rg '
                   '1 0 0 1 45 100 Tm (UNTOUCHED) Tj ET Q').encode()
        xref = doc.get_new_xref()
        doc.update_object(xref, '<<>>')
        doc.update_stream(xref, content)
        doc[0].set_contents(xref)
        source = doc.tobytes()
    if opacity:
        writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
        state = DictionaryObject({NameObject('/CA'): FloatObject(.8), NameObject('/ca'): FloatObject(.6)})
        writer.pages[0]['/Resources'][NameObject('/ExtGState')] = DictionaryObject({NameObject('/GS1'): state})
        stream = BytesIO(); writer.write(stream); source = stream.getvalue()
    return source


def selected(source, text='WORD', *, mode=0):
    with fitz.open(stream=source, filetype='pdf') as doc:
        model = extract_page(doc, 0, source)
    glyphs = [g for g in model.glyphs if g.mode == mode]
    combined = ''.join(g.text for g in glyphs)
    start = combined.index(text)
    return model, [g.id for g in glyphs[start:start+len(text)]]


def ops(source):
    reader = PdfReader(BytesIO(source), strict=True)
    return ContentStream(reader.pages[0].get_contents(), reader).operations


@pytest.mark.parametrize('click_mode', [0, 1])
@pytest.mark.parametrize('curved,opacity', [(False,False), (True,False), (False,True)])
def test_partial_word_removes_both_paints_and_keeps_original_state(click_mode, curved, opacity):
    source = source_pdf(curved=curved, opacity=opacity)
    digest = hashlib.sha256(source).hexdigest()
    model, ids = selected(source, mode=click_mode)
    output, report = try_delete_paired_text(source, EditRequest(0, ids, text=''), model)
    assert report['verified'] and report['native_paired_deletion']
    assert report['paired_characters_deleted'] == 4 and report['removed_paint_glyphs'] == 8
    assert hashlib.sha256(source).hexdigest() == digest
    expected = [g for g in model.glyphs if not (g.text in 'WORD' and
                any(abs(g.origin[0]-old.origin[0]) < .001 and abs(g.origin[1]-old.origin[1]) < .001
                    for old in model.selected(ids)))]
    with fitz.open(stream=output, filetype='pdf') as after, fitz.open(stream=source, filetype='pdf') as before:
        current = extract_page(after, 0, output)
        assert len(current.glyphs) == len(expected)
        for a, b in zip(current.glyphs, expected):
            assert (a.text,a.mode,a.font,a.size,a.color,a.opacity) == (b.text,b.mode,b.font,b.size,b.color,b.opacity)
            assert a.origin == pytest.approx(b.origin, abs=.0001)
        assert 'WORD' not in after[0].get_text()
        assert before.metadata == after.metadata
        assert before[1].get_texttrace() == after[1].get_texttrace()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
    before_ops, after_ops = ops(source), ops(output)
    assert len(before_ops) == len(after_ops)
    for (a, o), (b, p) in zip(before_ops, after_ops):
        assert o == p
        if o != b'TJ': assert _signature(a) == _signature(b)


def test_rich_empty_request_and_whole_show_delete_have_no_new_paint():
    source = source_pdf()
    model, ids = selected(source, 'ALPHA WORD END TRAIL')
    output, report = try_delete_paired_text(source, RichTextRequest(0, ids, []), model)
    assert report['paired_characters_deleted'] == len(ids)
    assert report['glyphs'] == [] and report['destination_regions'] == []
    with fitz.open(stream=output, filetype='pdf') as doc:
        assert doc[0].get_text().strip() == 'UNTOUCHED'


def test_replacement_standalone_stroke_and_normal_deletion_do_not_dispatch():
    source = source_pdf(); model, ids = selected(source)
    assert try_delete_paired_text(source, EditRequest(0, ids, text='NEW'), model) is None
    assert try_delete_paired_text(source, RichTextRequest(0, ids, [{'text':'NEW'}]), model) is None
    for mode in (0, 1):
        plain = source_pdf(mode=mode); plain_model, plain_ids = selected(plain, mode=mode)
        assert try_delete_paired_text(plain, EditRequest(0, plain_ids, text=''), plain_model) is None


def tagged_source(*, actual_text=False):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(actual_text='Fecha: 10/09/2026' if actual_text else None))))
    page = writer.pages[0]; content = ContentStream(page.get_contents(), writer)
    altered = []; mcid = None
    for args, operator in content.operations:
        if operator == b'BDC': mcid = args[1].get('/MCID')
        if operator == b'EMC': mcid = None
        if operator in (b'Tj', b'TJ') and mcid == 0:
            altered.extend([([NumberObject(2)], b'Tr'), (args,operator), ([NumberObject(0)],b'Tr')])
        else:
            altered.append((args,operator))
    content.operations = altered; page.replace_contents(content)
    target = BytesIO(); writer.write(target); return target.getvalue()


def test_tagged_partial_word_keeps_paired_ownership_and_surviving_text():
    source = tagged_source(); model, ids = selected(source, '10/09/2026')
    output, report = try_delete_paired_text(source, EditRequest(0, ids, text=''), model)
    assert report['accessibility']['verified'] and report['paired_characters_deleted'] == len(ids)
    assert report['accessibility']['actual_text_updates'] == 0
    with fitz.open(stream=output, filetype='pdf') as doc:
        assert '10/09/2026' not in doc[0].get_text()
        assert 'Fecha:' in doc[0].get_text()


def test_actualtext_with_single_logical_copy_needs_explicit_semantic_review():
    source = tagged_source(actual_text=True); model, ids = selected(source, '10/09/2026')
    with pytest.raises(EditError, match='ActualText.*difiere'):
        try_delete_paired_text(source, EditRequest(0, ids, text=''), model)


def test_selection_touching_link_cannot_leave_an_active_stale_target():
    source = source_pdf()
    with fitz.open(stream=source, filetype='pdf') as doc:
        doc[0].insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(35,45,280,85),'uri':'https://example.org'})
        source = doc.tobytes()
    model, ids = selected(source)
    with pytest.raises(EditError, match='enlace'):
        try_delete_paired_text(source, EditRequest(0, ids, text=''), model)


def test_stale_revision_is_rejected_before_preparing_output():
    source = source_pdf(); model, ids = selected(source)
    with pytest.raises(EditError, match='cambió'):
        try_delete_paired_text(source, EditRequest(0, ids, text='', revision='stale'), model)


@pytest.mark.parametrize('route',['panel','layout','rich'])
@pytest.mark.parametrize('click_mode',[0,1])
def test_public_deletion_routes_remove_both_components(route,click_mode):
    from pdfmodder.engine import edit_pdf
    from pdfmodder.textlayout import edit_with_layout
    from pdfmodder.richtext import edit_rich_pdf
    source=source_pdf(curved=True)
    model,ids=selected(source,mode=click_mode)
    request=EditRequest(0,ids,text='',revision=model.revision)
    if route=='rich':
        output,report=edit_rich_pdf(source,RichTextRequest(0,ids,[],revision=model.revision))
    else:
        output,report=(edit_pdf if route=='panel' else edit_with_layout)(source,request)
    assert report['verified'] and report['native_paired_deletion']
    assert report['removed_paint_glyphs']==8
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert 'WORD' not in doc[0].get_text()
        assert 'UNTOUCHED' in doc[0].get_text()


def appended_show(source, args, operator):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    page = writer.pages[0]; stream = ContentStream(page.get_contents(), writer)
    index = next(i for i, (_, op) in enumerate(stream.operations) if op == b'TJ')
    stream.operations.insert(index+1, (args, operator))
    page.replace_contents(stream)
    buffer = BytesIO(); writer.write(buffer)
    return buffer.getvalue(), index+1


@pytest.mark.parametrize('operator,args', [
    (b'Tj', [ByteStringObject(b'')]),
    (b'TJ', [ArrayObject([ByteStringObject(b''), NumberObject(125),
                          ByteStringObject(b''), NumberObject(-75)])]),
    (b'TJ', [ArrayObject([NumberObject(125), NumberObject(-75)])]),
])
def test_empty_unselected_show_keeps_its_operator_and_cursor_adjustments(operator, args):
    source, index = appended_show(source_pdf(), args, operator)
    model, ids = selected(source)
    output, report = try_delete_paired_text(source, EditRequest(0, ids, text=''), model)
    assert report['verified'] and report['removed_paint_glyphs'] == 8
    before_args, before_op = ops(source)[index]
    after_args, after_op = ops(output)[index]
    assert after_op == before_op == operator
    assert _signature(after_args) == _signature(before_args)


def test_missing_trace_glyphs_do_not_authorize_a_nonempty_show(monkeypatch):
    import pdfmodder.clipping as clipping
    source = source_pdf()
    index = next(i for i, (_, operator) in enumerate(ops(source)) if operator == b'TJ')
    model, ids = selected(source)
    original_map = clipping.operator_glyph_map

    def incomplete_trace(*args):
        reader, operations, shows, mapping = original_map(*args)
        shows = [dict(show, glyphs=[]) if show['operation'] == index else show for show in shows]
        return reader, operations, shows, mapping

    monkeypatch.setattr(clipping, 'operator_glyph_map', incomplete_trace)
    with pytest.raises(EditError, match='verificar cada pareja'):
        try_delete_paired_text(source, EditRequest(0, ids, text=''), model)
