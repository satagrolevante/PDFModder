"""Deleting native codes keeps genuine curved clips and all surviving paint."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from pdfmodder.clipping import _signature
from pdfmodder.engine import extract_page
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from test_clip_paths_v304 import fixture, draft


@pytest.mark.parametrize('partial',[False,True])
def test_deletion_preserves_curved_clip_and_cursor_for_survivors(partial):
    source=fixture(curved=True)
    request=draft(source,'')
    if partial:request=replace(request,ids=request.ids[:2])
    with fitz.open(stream=source,filetype='pdf') as doc:
        original=extract_page(doc,0,source)
        expected=[g for g in original.glyphs if g.id not in request.ids]
    output,report=edit_rich_pdf(source,request)
    assert report['verified'] and report['complex_clip_preserved_by_deletion']
    assert not report['glyphs']
    path_ops={b'q',b'Q',b'cm',b'm',b'l',b'c',b'v',b'y',b'h',b're',b'W',b'W*'}
    def paths(data):
        reader=PdfReader(BytesIO(data),strict=True)
        # Native rich writing adds one balanced outer q/Q; path geometry stays exact.
        return [(op,_signature(args)) for args,op in ContentStream(reader.pages[0].get_contents(),reader).operations
                if op in path_ops-{b'q',b'Q'}]
    assert paths(output)==paths(source)
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        current=extract_page(after,0,output)
        assert len(current.glyphs)==len(expected)
        for a,b in zip(current.glyphs,expected):
            assert (a.text,a.font,a.size,a.color,a.opacity)==(b.text,b.font,b.size,b.color,b.opacity)
            assert a.origin==pytest.approx(b.origin,abs=.0002)
        assert before.metadata==after.metadata
        assert before[1].get_texttrace()==after[1].get_texttrace()
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
    if partial:
        reopened=selection_payload(output,0,[g.id for g in current.glyphs[:len(request.ids)+7]])
        assert reopened['runs']
