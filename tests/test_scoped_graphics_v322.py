"""Selected text can change without changing unrelated graphics effects."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject,
                          DictionaryObject, NameObject, NumberObject)
import pytest

from pdfmodder.engine import edit_pdf
from pdfmodder.graphics_state import COLOR_ISSUE, BLEND_ISSUE
from pdfmodder.model import EditError, EditRequest
from pdfmodder.pageops import _semantic
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.validation import scope_text_graphics_v322, assert_pixels
from test_color_state import _pdf, _select, _function


VALUES = [
    {'/OP':BooleanObject(True)},
    {'/BM':NameObject('/Multiply')},
    {'/TR2':_function()},
]


def distant_effect(values):
    return _pdf({'/Danger':values}, prefix=b'',
                suffix=b'\nq /Danger gs .2 .6 .3 rg 330 220 20 20 re f Q\n')


def soft_mask(data):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
    group=DecodedStreamObject()
    group.set_data(b'.7 g 0 0 400 300 re f')
    group.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
        NameObject('/BBox'):ArrayObject([NumberObject(n) for n in (0,0,400,300)]),
        NameObject('/Group'):DictionaryObject({NameObject('/S'):NameObject('/Transparency'),
                                             NameObject('/CS'):NameObject('/DeviceGray')}),
        NameObject('/Resources'):DictionaryObject()})
    gs=writer.pages[0]['/Resources']['/ExtGState']['/Danger']
    gs[NameObject('/SMask')]=DictionaryObject({NameObject('/S'):NameObject('/Luminosity'),
                                            NameObject('/G'):writer._add_object(group)})
    target=BytesIO();writer.write(target)
    return target.getvalue()


@pytest.mark.parametrize('values', VALUES)
def test_only_owned_show_state_decides_the_local_colour_gate(values):
    data = distant_effect(values)
    model, chosen = _select(data)
    assert {COLOR_ISSUE,BLEND_ISSUE}.intersection(model.issues)
    refined = scope_text_graphics_v322(data,model,chosen)
    assert not {COLOR_ISSUE,BLEND_ISSUE}.intersection(refined.issues)
    assert refined.glyphs is model.glyphs
    unsafe = _pdf({'/Danger':values},prefix=b'/Danger gs\n')
    other, selected = _select(unsafe)
    assert {COLOR_ISSUE,BLEND_ISSUE}.intersection(scope_text_graphics_v322(unsafe,other,selected).issues)


@pytest.mark.parametrize('route', ['rich','native'])
@pytest.mark.parametrize('values', VALUES)
def test_real_text_edit_keeps_distant_effect_resource_and_control_page(route, values):
    data = distant_effect(values)
    model, chosen = _select(data)
    ids = [g.id for g in chosen]
    if route=='rich':
        payload = selection_payload(data,0,ids)
        request = RichTextRequest(0,ids,[dict(payload['runs'][0],text='2026')],rect=payload['rect'])
        output,report = edit_rich_pdf(data,request)
    else:
        # auto_adapt uses native in-place composition; no redaction/reinsertion
        # is authorized to inherit the unrelated final graphics state.
        output,report = edit_pdf(data,EditRequest(0,ids,text='2026',revision=model.revision,auto_adapt=True))
    assert report['verified']
    readers = [PdfReader(BytesIO(b),strict=True) for b in (data,output)]
    assert _semantic(readers[0].pages[0]['/Resources']['/ExtGState']) == _semantic(readers[1].pages[0]['/Resources']['/ExtGState'])
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert '2026' in after[0].get_text()
        assert 'VECINO 2025' in after[0].get_text()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        # This is a real full-page comparison outside the source/replacement
        # text rectangles, including the distant effected rectangle.
        regions = report['source_regions']+report['destination_regions']
        assert assert_pixels(before[0],after[0],regions)['pixels_above_8']==0


def test_append_requires_explicit_isolation_or_neutral_final_state():
    data = _pdf({'/Danger':{'/BM':NameObject('/Multiply')}}, prefix=b'',suffix=b'\n/Danger gs')
    model,selected = _select(data)
    assert BLEND_ISSUE in model.issues
    assert BLEND_ISSUE not in scope_text_graphics_v322(data,model,selected).issues
    assert BLEND_ISSUE in scope_text_graphics_v322(data,model,selected,require_neutral_final=True).issues
    assert BLEND_ISSUE in scope_text_graphics_v322(data,model).issues
    assert BLEND_ISSUE not in scope_text_graphics_v322(data,model,isolated_append=True).issues


def test_scoped_proof_does_not_clear_other_structural_issues_or_accept_stale_revision():
    data = distant_effect({'/BM':NameObject('/Multiply')})
    model,selected = _select(data)
    model=replace(model,issues=model.issues+['Otra estructura no verificable.'])
    assert scope_text_graphics_v322(data,model,selected).issues == ['Otra estructura no verificable.']
    with pytest.raises(EditError,match='revisión'):
        scope_text_graphics_v322(data,replace(model,revision='outdated'),selected)


def test_nested_unselected_form_effects_are_preserved_but_not_owned_by_page_text():
    data = _pdf({'/Danger':{'/BM':NameObject('/Multiply')}},prefix=b'\nq /Form Do Q\n',
                form=b'/Danger gs 0 0 4 4 re f')
    model,selected = _select(data)
    assert BLEND_ISSUE in model.issues
    assert BLEND_ISSUE not in scope_text_graphics_v322(data,model,selected).issues


def test_real_soft_mask_outside_selection_does_not_become_a_text_permission():
    data=soft_mask(distant_effect({}))
    model,selected=_select(data)
    assert BLEND_ISSUE in model.issues
    assert BLEND_ISSUE not in scope_text_graphics_v322(data,model,selected).issues
    affected=soft_mask(_pdf({'/Danger':{}},prefix=b'/Danger gs\n'))
    current,chosen=_select(affected)
    assert BLEND_ISSUE in scope_text_graphics_v322(affected,current,chosen).issues
