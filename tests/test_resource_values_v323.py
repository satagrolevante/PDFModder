"""Numerical normalization must not hide actual program/resource changes."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, FloatObject, NameObject, NumberObject

from pdfmodder.clipping import _signature
from pdfmodder.engine import edit_pdf
from pdfmodder.model import EditRequest
from pdfmodder.resource_values_v323 import same_resource_values
from tagged_corpus import dictionary
from test_clip_move_v150 import fixture,selection


def test_only_same_finite_binary32_decimal_representations_are_equivalent():
    old=dictionary(Ascent=FloatObject('905.27344'),Descent=FloatObject('-376.46484'))
    new=dictionary(Ascent=FloatObject('905.27346'),Descent=FloatObject('-376.46485'))
    assert _signature(old)!=_signature(new)
    assert same_resource_values(old,new)
    new[NameObject('/Ascent')]=FloatObject('905.274')
    assert not same_resource_values(old,new)
    assert not same_resource_values(NumberObject(16777216),NumberObject(16777217))
    assert not same_resource_values(FloatObject('1e99'),FloatObject('2e99'))


@pytest.mark.parametrize('changed',['program','cmap','key','integer','width'])
def test_resource_mutations_still_rejected(changed):
    def resource():
        stream=DecodedStreamObject();stream.set_data(b'exact embedded font bytes')
        cmap=DecodedStreamObject();cmap.set_data(b'exact original cmap')
        return dictionary(FontFile2=stream,ToUnicode=cmap,FirstChar=NumberObject(7),
                          Widths=ArrayObject([FloatObject('905.27344')]))
    a=resource();b=resource()
    if changed=='program':b['/FontFile2'].set_data(b'changed embedded font bytes')
    elif changed=='cmap':b['/ToUnicode'].set_data(b'changed cmap')
    elif changed=='key':b[NameObject('/NewProperty')]=NumberObject(1)
    elif changed=='integer':b[NameObject('/FirstChar')]=NumberObject(8)
    else:b['/Widths'][0]=FloatObject('905.274')
    assert not same_resource_values(a,b)


def test_clipped_move_does_not_fail_on_writer_number_normalization():
    source=fixture()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    writer.pages[0]['/Resources'][NameObject('/ExtGState')]=dictionary(
        Unused=dictionary(LW=FloatObject('905.27344')))
    saved=BytesIO();writer.write(saved);source=saved.getvalue()
    model,selected=selection(source,'2026')
    output,report=edit_pdf(source,EditRequest(0,[g.id for g in selected],dx=12,dy=85))
    assert report['verified'] and report['clip_translated']
    a=PdfReader(BytesIO(source)).pages[0]['/Resources']
    b=PdfReader(BytesIO(output)).pages[0]['/Resources']
    assert _signature(a)!=_signature(b) and same_resource_values(a,b)
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
