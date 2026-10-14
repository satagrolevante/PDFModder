"""Native Delete removes tagged clipped text using the rich operator transaction."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, FloatObject, NameObject

from pdfmodder.clipping import CLIP_ISSUE
from pdfmodder.engine import extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.textlayout import edit_with_layout
from pdfmodder.untag_v180 import remove_tags
from tagged_corpus import make_tagged_pdf


def tagged_clipped_pdf():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page=writer.pages[0];stream=ContentStream(page.get_contents(),writer)
    stream.operations=[([],b'q'),([FloatObject(v) for v in (0,0,400,420)],b're'),([],b'W'),([],b'n'),*stream.operations,([],b'Q')]
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);return out.getvalue()


@pytest.mark.parametrize('target',['10/09/2026','Fecha: 10/09/2026'])
@pytest.mark.parametrize('auto_width',[False,True])
@pytest.mark.parametrize('tagged',[False,True])
def test_empty_panel_request_matches_rich_deletion_and_preserves_neighbors(target,auto_width,tagged):
    source=tagged_clipped_pdf()
    if not tagged:source=remove_tags(source)[0]
    with fitz.open(stream=source,filetype='pdf') as doc:
        model=extract_page(doc,0,source)
    full=''.join(g.text for g in model.glyphs);start=full.index(target)
    ids=[g.id for g in model.glyphs[start:start+len(target)]]
    assert CLIP_ISSUE in model.issues
    output,report=edit_with_layout(source,EditRequest(0,ids,text='',revision=model.revision,
                                                    auto_width=auto_width,line_reflow=True))
    assert report['verified'] and report['native_deletion'] and report['rich_text']
    if tagged:assert report['accessibility']['structure_preserved']
    with fitz.open(stream=source,filetype='pdf') as old,fitz.open(stream=output,filetype='pdf') as new:
        after=extract_page(new,0,output)
        expected=[g for g in model.glyphs if g.id not in set(ids)]
        assert [(g.text,g.origin,g.font,g.size,g.color) for g in after.glyphs]==[(g.text,g.origin,g.font,g.size,g.color) for g in expected]
        assert target not in new[0].get_text()
        assert old[1].get_texttrace()==new[1].get_texttrace()
        assert old[1].get_pixmap().samples==new[1].get_pixmap().samples
    assert target not in PdfReader(BytesIO(output)).pages[0].extract_text()


def test_empty_request_does_not_bypass_revision_validation():
    source=tagged_clipped_pdf()
    with fitz.open(stream=source,filetype='pdf') as doc:model=extract_page(doc,0,source)
    with pytest.raises(EditError,match='cambió'):
        edit_with_layout(source,EditRequest(0,[model.glyphs[0].id],text='',revision='stale',auto_width=True))
