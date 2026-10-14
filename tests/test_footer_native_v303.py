"""Synthetic footer cells: native paint, clips and unrelated content survive."""
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from pdfmodder.clipping import _signature
from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import _new_neighbor_overlap, edit_rich_pdf, selection_payload


def footer_pdf(*, clip_top=170, rotation=0):
    with fitz.open() as document:
        page = document.new_page(width=340, height=220)
        page.insert_text((25, 50), 'CONTROL INTACTO', fontname='cour', fontsize=12)
        # An otherwise harmless, high precision source operand used to lose
        # 3e-7 during pypdf serialization and fail the native preservation proof.
        first = page.get_contents()[0]
        document.update_stream(first, b'q 123.9999053 0 0 1 0 0 cm Q\n'
                               + document.xref_stream(first))
        for left, text in ((20, 'ABCDEF'), (120, '123456'), (220, 'FEDCBA')):
            page.insert_text((left+5, 180), text, fontname='cour', fontsize=12)
            xref = page.get_contents()[-1]
            prefix = f'q {left} 39 100 {181-clip_top} re W n\n'.encode()
            document.update_stream(xref, prefix+document.xref_stream(xref)+b'\nQ')
        page.set_rotation(rotation)
        document.new_page(width=340, height=220).insert_text((25, 50), 'OTRA PAGINA')
        return document.tobytes()


def draft(data, *, columns=(0,), text=None, **options):
    with fitz.open(stream=data, filetype='pdf') as document:
        model = extract_page(document, 0, data)
    selected = [g for g in model.glyphs if abs(g.origin[1]-180)<.01
                and any(20+column*100 <= g.origin[0] < 120+column*100 for column in columns)]
    payload = selection_payload(data, 0, [g.id for g in selected])
    runs = payload['runs'] if text is None else [dict(payload['runs'][0], text=text)]
    return RichTextRequest(0, payload['ids'], runs, rect=payload['rect'],
                           paragraphs=payload['paragraphs'], revision=payload['revision'], **options)


def operations(data):
    reader = PdfReader(BytesIO(data), strict=True)
    return ContentStream(reader.pages[0].get_contents(), reader).operations


def assert_preserved(before_data, after_data):
    old = operations(before_data)
    new = operations(after_data)
    preserved = {b're', b'W', b'W*'}
    assert [(op, _signature(args)) for args, op in old if op in preserved] == [
        (op, _signature(args)) for args, op in new if op in preserved]
    # Rich insertion adds its own scoped translations; each original cm
    # operand must still remain exactly represented and in source order.
    source_matrices = [_signature(args) for args, op in old if op == b'cm']
    written_matrices = iter(_signature(args) for args, op in new if op == b'cm')
    for source in source_matrices:
        assert any(source == written for written in written_matrices)
    with fitz.open(stream=before_data, filetype='pdf') as before, \
            fitz.open(stream=after_data, filetype='pdf') as after:
        assert before[1].get_texttrace() == after[1].get_texttrace()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        before[0].set_rotation(0)
        after[0].set_rotation(0)
        for region in ((15, 30, 230, 65), (115, 165, 325, 190)):
            assert before[0].get_pixmap(clip=region).samples == after[0].get_pixmap(clip=region).samples


def test_noop_across_disjoint_cells_keeps_original_bytes():
    data = footer_pdf()
    output, report = edit_rich_pdf(data, draft(data, columns=(0, 1, 2)))
    assert output == data
    assert report['native_noop'] and report['verified']


@pytest.mark.parametrize('replacement', ['FEDCBA', 'ABC', 'FEDCBAABC'])
@pytest.mark.parametrize('rotation', [0, 90])
def test_existing_codes_fit_ink_even_when_font_metrics_cross_cell(replacement, rotation):
    data = footer_pdf(rotation=rotation)
    output, report = edit_rich_pdf(data, draft(data, text=replacement, auto_width=True))
    assert report['verified'] and report['clip_paint_verified']
    assert report['clip_metric_overhang_verified']
    assert_preserved(data, output)
    with fitz.open(stream=output, filetype='pdf') as document:
        glyphs = extract_page(document, 0, output).glyphs
    assert ''.join(g.text for g in glyphs if abs(g.origin[1]-180)<.01 and g.origin[0]<120) == replacement


@pytest.mark.parametrize('clip_top', [170, 176])
def test_delete_three_cells_preserves_clips_even_if_source_ink_was_cut(clip_top):
    data = footer_pdf(clip_top=clip_top)
    output, report = edit_rich_pdf(data, draft(data, columns=(0, 1, 2), text=''))
    assert report['verified'] and report['glyphs'] == []
    with fitz.open(stream=output, filetype='pdf') as document:
        assert 'ABCDEF' not in document[0].get_text()
        assert '123456' not in document[0].get_text()
        assert 'CONTROL INTACTO' in document[0].get_text()
        assert document[1].get_text().strip() == 'OTRA PAGINA'
    old, new = operations(data), operations(output)
    assert [(op, _signature(args)) for args, op in old if op in (b'W', b'W*', b're', b'cm')] == [
        (op, _signature(args)) for args, op in new if op in (b'W', b'W*', b're', b'cm')]


def test_replacement_of_genuinely_clipped_ink_stays_blocked():
    data = footer_pdf(clip_top=176)
    with pytest.raises(EditError, match='original.*recorte'):
        edit_rich_pdf(data, draft(data, text='FEDCBA', auto_width=True))


@pytest.mark.parametrize('kind', ['move', 'grow', 'overflow'])
def test_metric_exception_does_not_authorize_new_geometry(kind):
    data = footer_pdf()
    request = draft(data, text='FEDCBA', auto_width=True)
    if kind == 'move':
        request = replace(request, rect=tuple(v+(2 if i%2 else 0) for i, v in enumerate(request.rect)))
    elif kind == 'grow':
        request = replace(request, runs=[dict(request.runs[0], size=18)], auto_height=True)
    else:
        request = replace(request, runs=[dict(request.runs[0], text='ABCDEF'*4)])
    with pytest.raises(EditError, match='recorte'):
        edit_rich_pdf(data, request)


def test_equal_width_native_replacement_preserves_high_precision_operands():
    data = footer_pdf()
    request = draft(data, columns=(1,), text='654321')
    output, report = edit_pdf(data, EditRequest(0, request.ids, text='654321', revision=request.revision))
    assert report['verified'] and report['operators_preserved'] and report['font_resources_unchanged']
    old, new = operations(data), operations(output)
    assert len(old) == len(new)
    for (a, op), (b, newop) in zip(old, new):
        assert op == newop
        if op not in (b'Tj', b'TJ'):
            assert _signature(a) == _signature(b)
    assert any(op == b'cm' and float(args[0]) == 123.9999053 for args, op in new)


def test_float32_residual_strip_uses_existing_overlap_tolerance():
    glyph = lambda bbox: SimpleNamespace(bbox=bbox)
    neighbor = glyph((100, 100, 500, 130))
    selected = [glyph((200, 100, 300, 130))]
    assert not _new_neighbor_overlap(glyph((200, 100, 300.1200305175781, 130)), neighbor, selected)
    assert _new_neighbor_overlap(glyph((200, 100, 301, 130)), neighbor, selected)


def test_narrower_existing_codes_with_tight_leading_preserve_styles_and_neighbors():
    from test_rich_overlap_preservation import tight_lines
    data, selected, neighbors, payload = tight_lines()
    request = RichTextRequest(0, payload['ids'], [dict(payload['runs'][0], text='ABC')],
                              rect=payload['rect'], revision=payload['revision'],
                              auto_width=True, auto_height=True)
    output, report = edit_rich_pdf(data, request)
    assert report['verified'] and report['pages'][0]['pixels_above_8'] == 0
    with fitz.open(stream=output, filetype='pdf') as document:
        model = extract_page(document, 0, output)
    changed = [g for g in model.glyphs if abs(g.origin[1]-74)<.01 and g.origin[0]>=50]
    assert ''.join(g.text for g in changed) == 'ABC'
    assert {(g.font, g.size, g.color, g.opacity) for g in changed} == {
        (g.font, g.size, g.color, g.opacity) for g in selected}
    untouched = [g for g in model.glyphs if g not in changed]
    assert [(g.text, g.origin, g.font, g.size, g.color) for g in untouched] == [
        (g.text, g.origin, g.font, g.size, g.color) for g in neighbors]
