"""Accept the exact validated preview once; changed drafts never reuse it."""
from copy import deepcopy
from dataclasses import replace

import pymupdf as fitz
import pytest

from pdfmodder.model import EditError
from pdfmodder.worker import Session
from test_richtext_v09 import document, request


@pytest.fixture
def editing_session(tmp_path):
    source=tmp_path/'document.pdf';source.write_bytes(document())
    session=Session(source,history_dir=tmp_path/'history',config_path=tmp_path/'fonts.json')
    yield session
    session.close()


def count_validations(monkeypatch):
    import pdfmodder.richtext as richtext
    calls=[];original=richtext.edit_rich_pdf
    def edit(data,req,resolver):
        calls.append(deepcopy(req))
        return original(data,req,resolver)
    monkeypatch.setattr(richtext,'edit_rich_pdf',edit)
    return calls


def changed_request(session):
    req=request(session.history.current)
    return replace(req,runs=[dict(req.runs[0],text='Hola nuevo')])


def test_accept_reuses_exact_validated_bytes_and_private_report(editing_session,monkeypatch):
    session=editing_session;calls=count_validations(monkeypatch)
    req=changed_request(session)
    preview=session.rich_preview(req)
    assert session.history.index==0 and session.pending is None
    preview['report']['verified']=False
    preview['report']['pages'].clear()
    prepared=session.rich_preview(deepcopy(req),prepare=True)
    assert len(calls)==1 and prepared['report']['verified'] and prepared['report']['pages']
    expected=session._prepared_rich[2]
    result=session.rich_commit(prepared['token'])
    assert result['state']['history_index']==1 and session.history.current==expected
    with fitz.open(stream=expected,filetype='pdf') as doc:
        assert 'Hola nuevo' in doc[0].get_text()
        assert 'VECINO INTACTO' in doc[0].get_text()
    with pytest.raises(EditError,match='preparada'):
        session.rich_commit(prepared['token'])


@pytest.mark.parametrize('change',['text','format','area','cancel'])
def test_changed_draft_or_cancel_requires_fresh_validation(editing_session,monkeypatch,change):
    session=editing_session;calls=count_validations(monkeypatch)
    req=changed_request(session);session.rich_preview(req)
    if change=='text':req.runs[0]['text']='Hola otro'
    elif change=='format':req.runs[0]['color']=(.8,0.,0.)
    elif change=='area':req=replace(req,rect=(req.rect[0]+1,*req.rect[1:]))
    else:session.cancel()
    prepared=session.rich_preview(req,prepare=True)
    assert len(calls)==2 and prepared['report']['verified']
    assert session.history.index==0


def test_failed_new_draft_does_not_reuse_previous_preview(editing_session,monkeypatch):
    session=editing_session;calls=count_validations(monkeypatch)
    req=changed_request(session);session.rich_preview(req)
    bad=replace(req,rect=(35.,30.,36.,31.),auto_width=False,auto_height=False)
    with pytest.raises(EditError):session.rich_preview(bad,prepare=True)
    assert session._prepared_rich is None and session._validated_rich is None
    assert session.history.index==0 and session.pending is None
    session.rich_preview(req,prepare=True)
    assert len(calls)==3


def test_history_change_invalidates_reusable_draft(editing_session,monkeypatch):
    session=editing_session;calls=count_validations(monkeypatch)
    prepared=session.rich_preview(changed_request(session),prepare=True)
    session.rich_commit(prepared['token'])
    session.navigate_history()
    session.rich_preview(changed_request(session),prepare=True)
    assert len(calls)==2 and session.history.index==0


def test_cancel_invalidates_prepared_acceptance(editing_session):
    session=editing_session
    prepared=session.rich_preview(changed_request(session),prepare=True)
    session.cancel()
    with pytest.raises(EditError,match='preparada'):
        session.rich_commit(prepared['token'])
    assert session.history.index==0 and session.pending is None
