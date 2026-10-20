"""Repeated drafts reuse checked source data and commit the exact final bytes."""
from copy import deepcopy
from hashlib import sha256

import pymupdf as fitz
import pytest

from pdfmodder import tagged
from pdfmodder.engine import extract_page
from pdfmodder.native_panel import _replace_runs
from pdfmodder.worker import Session
from tagged_corpus import make_tagged_pdf


@pytest.fixture
def session(tmp_path):
    tagged.clear_readonly_cache()
    data=make_tagged_pdf()
    path=tmp_path/'source.pdf'
    path.write_bytes(data)
    value=Session(path,config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    yield value,data,path
    value.close()
    tagged.clear_readonly_cache()


def draft(session,data,text):
    with fitz.open(stream=data,filetype='pdf') as document:
        model=extract_page(document,0,data)
    chars=''.join(g.text for g in model.glyphs)
    at=chars.index('10/09/2026')
    ids=[g.id for g in model.glyphs[at:at+10]]
    payload=session.rich_selection(0,ids)
    return dict(page=0,ids=ids,revision=payload['revision'],rect=payload['rect'],
                runs=_replace_runs(deepcopy(payload['runs']),text))


def test_two_different_drafts_keep_source_analysis_and_save_exact_validated_bytes(session,tmp_path,monkeypatch):
    value,data,path=session
    first=draft(value,data,'11/09/2026')
    source=tagged.analyze_readonly(data)
    calls=[]
    original=tagged.analyze
    def counted(raw):
        calls.append(sha256(raw).hexdigest())
        return original(raw)
    monkeypatch.setattr(tagged,'analyze',counted)
    value.rich_preview(first,prepare=True)
    second=deepcopy(first)
    second['runs']=_replace_runs(second['runs'],'12/09/2026')
    prepared=value.rich_preview(second,prepare=True)
    assert prepared['report']['verified']
    assert value.history.index==0 and value.pending is None
    assert sha256(data).hexdigest() not in calls
    assert tagged._pinned_source_cache[1] is source
    candidate=value._prepared_rich[2]
    value.rich_commit(prepared['token'])
    assert value.history.current==candidate
    destination=tmp_path/'saved.pdf'
    value.save(destination)
    assert destination.read_bytes()==candidate
    assert path.read_bytes()==data
    with fitz.open(stream=candidate,filetype='pdf') as after,fitz.open(stream=data,filetype='pdf') as before:
        assert '12/09/2026' in after[0].get_text()
        assert len(after)==len(before)
        assert after.metadata==before.metadata and after.get_toc()==before.get_toc()
        assert after[1].get_texttrace()==before[1].get_texttrace()
        assert after[1].get_pixmap().samples==before[1].get_pixmap().samples
    value.navigate_history()
    assert value.history.current==data


@pytest.mark.parametrize('release',['close','suspend'])
def test_release_frees_old_source_pin_after_commit_changed_head(session,release):
    value,data,_=session
    prepared=value.rich_preview(draft(value,data,'11/09/2026'),prepare=True)
    assert tagged._pinned_source_cache[0][0]==sha256(data).digest()
    value.rich_commit(prepared['token'])
    assert value.history.revision!=sha256(data).hexdigest()
    getattr(value,release)()
    assert tagged._pinned_source_cache is None
    assert tagged._readonly_cache is None
    if release=='suspend':
        value.resume()
        assert value.state()['history_index']==1
