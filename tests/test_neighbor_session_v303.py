"""Neighbor redistribution is one validated, reversible PDF transaction."""
from dataclasses import fields

import pymupdf as fitz
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.worker import Session


def document():
    with fitz.open() as doc:
        page=doc.new_page(width=260,height=220)
        page.insert_text((20,45),'Alpha beta gamma delta\nEpsilon zeta eta theta',fontsize=12)
        doc.new_page(width=260,height=220).insert_text((20,45),'CONTROL',fontsize=12)
        return doc.tobytes()


def draft(session):
    data=session.history.current
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    glyph=next(g for g in model.glyphs if not g.text.isspace())
    payload=session.rich_selection(0,model.group(glyph,'word'))
    return dict(page=0,ids=payload['ids'],revision=payload['revision'],rect=payload['rect'],
        runs=[dict(payload['runs'][0],text='AlphaAlphaAlpha')],
        auto_width=True,auto_height=True,allow_overlap=False)


def request(payload):
    names={f.name for f in fields(RichTextRequest)}
    return RichTextRequest(**{k:v for k,v in payload.items() if k in names})


@pytest.fixture
def session(tmp_path):
    source=tmp_path/'source.pdf';source.write_bytes(document())
    result=Session(source,history_dir=tmp_path/'history',config_path=tmp_path/'fonts.json')
    yield result
    result.close()


def test_neighbor_draft_preserves_source_until_accept_and_undo_recovers_all(session):
    original=session.history.current
    value=draft(session)
    with pytest.raises(EditError,match='solapa'):
        session.rich_preview(request(value),prepare=True)
    expanded=session.rich_redistribute(value,'paragraph')
    assert expanded['neighbor_layout_info']['neighbor_count']>0
    assert session.history.current==original and session.history.index==0
    prepared=session.rich_preview(request(expanded),prepare=True)
    assert prepared['report']['verified'] and session.history.index==0
    session.rich_commit(prepared['token'])
    assert session.history.index==1
    with fitz.open(stream=original,filetype='pdf') as before,fitz.open(stream=session.history.current,filetype='pdf') as after:
        text=' '.join(after[0].get_text().split())
        assert text=='AlphaAlphaAlpha beta gamma delta Epsilon zeta eta theta'
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
    session.navigate_history()
    assert session.history.index==0 and session.history.current==original


def test_revoking_overlap_does_not_reuse_a_permitted_preview(session):
    value=draft(session);value['allow_overlap']=True
    preview=session.rich_preview(request(value))
    assert preview['report']['overlap_neighbor_count']>0
    value['allow_overlap']=False
    with pytest.raises(EditError,match='solapa'):
        session.rich_preview(request(value),prepare=True)
    assert session._prepared_rich is None and session.history.index==0
