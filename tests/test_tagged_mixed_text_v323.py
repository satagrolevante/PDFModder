"""Mixed tagged/exported page text stays editable without fabricating tags."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, ContentStream, DecodedStreamObject,
                          FloatObject, NameObject, NumberObject)

from pdfmodder.clipping import _serialize, operator_glyph_map
from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.tagged import analyze, analyze_readonly, clear_readonly_cache
from pdfmodder.tagged_unmarked_v323 import native_text_plan, verified_unmarked_selection
from pdfmodder.validation import document_issues
from tagged_corpus import dictionary, make_tagged_pdf
from test_rich_ui_v09 import window


def source_pdf():
    return make_tagged_pdf(defect='untagged_glyph', include_objr=True)


def selection(data, text):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    joined=''.join(g.text for g in model.glyphs)
    at=joined.index(text)
    return model,[g.id for g in model.glyphs[at:at+len(text)]]


def assert_preserved(source, output):
    assert analyze(source).semantic()==analyze(output).semantic()
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_texttrace()==after[1].get_texttrace()
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert before.metadata==after.metadata


def test_existing_unmarked_text_does_not_disable_independent_tagged_edits():
    source=source_pdf()
    structure=analyze(source)
    assert {'kind':'unmarked_text','page':0,'shows':1} in structure.source_irregularities
    with fitz.open(stream=source,filetype='pdf') as doc:
        assert document_issues(source,doc,operation='content')==[]
    model,ids=selection(source,'10/09/2026')
    output,report=edit_pdf(source,EditRequest(0,ids,text='11/09/2026',revision=model.revision))
    assert report['verified'] and report['accessibility']['verified']
    assert 'SIN ETIQUETA' in PdfReader(BytesIO(output)).pages[0].extract_text()
    assert_preserved(source,output)


@pytest.mark.parametrize('auto_adapt',[False,True])
@pytest.mark.parametrize('text,new',[('SIN ETIQUETA','TEXTO NUEVO'),('SIN','CON'),('ETIQUETA','')])
def test_unmarked_full_word_and_delete_use_native_scopes(auto_adapt,text,new):
    source=source_pdf();model,ids=selection(source,text)
    output,report=edit_pdf(source,EditRequest(0,ids,text=new,auto_adapt=auto_adapt,
        auto_width=True,auto_height=True,allow_overlap=True,revision=model.revision))
    assert report['verified'] and report['accessibility']['unmarked_text_preserved']
    expected='SIN ETIQUETA'.replace(text,new)
    assert ' '.join(expected.split()) in ' '.join(PdfReader(BytesIO(output)).pages[0].extract_text().split())
    assert_preserved(source,output)


def test_unmarked_preview_save_reopen_undo_and_redo(tmp_path):
    from pdfmodder.worker import Session
    source=source_pdf();original=tmp_path/'original.pdf';original.write_bytes(source)
    session=Session(original,reading=True,history_dir=tmp_path/'history',config_path=tmp_path/'fonts.json')
    try:
        session.prepare_editing(0)
        assert session.issues==[]
        model,ids=selection(source,'SIN ETIQUETA')
        payload=session.rich_selection(0,ids)
        req=RichTextRequest(0,ids,[dict(payload['runs'][0],text='TEXTO NUEVO')],
            rect=payload['rect'],revision=model.revision,auto_width=True,auto_height=True,auto_adapt=True)
        ready=session.rich_preview(req,prepare=True)
        assert session.history.current==source
        session.rich_commit(ready['token'])
        candidate=session.history.current
        target=tmp_path/'saved.pdf';session.save(target)
        assert target.read_bytes()==candidate
        assert_preserved(source,target.read_bytes())
        model,ids=selection(candidate,'TEXTO NUEVO')
        second,report=edit_pdf(candidate,EditRequest(0,ids,text='SEGUNDO TEXTO',auto_adapt=True,
                                                   auto_width=True,auto_height=True))
        assert report['verified'] and 'SEGUNDO TEXTO' in PdfReader(BytesIO(second)).pages[0].extract_text()
        session.navigate_history();assert session.history.current==source
        session.navigate_history(redo=True);assert session.history.current==candidate
        assert original.read_bytes()==source
    finally:session.close()


def test_unmarked_format_and_move_retain_membership():
    source=source_pdf();model,ids=selection(source,'SIN ETIQUETA')
    output,report=edit_pdf(source,EditRequest(0,ids,size=10,color=(.2,.3,.5),auto_adapt=True))
    assert report['verified'] and report['accessibility']['unmarked_text_preserved']
    model,ids=selection(output,'SIN ETIQUETA')
    moved,report=edit_pdf(output,EditRequest(0,ids,dx=12,dy=8,allow_overlap=True))
    assert report['verified']
    assert_preserved(source,moved)


def test_unmarked_proof_rejects_mixed_owners_stale_revisions_and_semantic_wrappers():
    source=source_pdf();model,ids=selection(source,'SIN ETIQUETA')
    structure=analyze(source)
    _,ops,_,mapping=operator_glyph_map(source,0,model)
    selected=model.selected(ids)
    assert verified_unmarked_selection(structure,0,model,selected,ops,mapping)
    assert not verified_unmarked_selection(structure,0,replace(model,revision='stale'),selected,ops,mapping)
    assert not verified_unmarked_selection(structure,0,model,[model.glyphs[0],*selected],ops,mapping)
    target=mapping[ids[0]]['operation']
    changed=ops[:target]+[([NameObject('/ReversedChars')],b'BMC'),ops[target],([],b'EMC')]+ops[target+1:]
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    stream=DecodedStreamObject();stream.set_data(_serialize(changed))
    writer.pages[0][NameObject('/Contents')]=writer._add_object(stream)
    saved=BytesIO();writer.write(saved)
    with pytest.raises(EditError,match='semántico'):
        analyze(saved.getvalue())


def test_final_guard_rejects_reclassifying_unmarked_replacement_as_artifact():
    source=source_pdf();model,ids=selection(source,'SIN ETIQUETA')
    _,ops,_,mapping=operator_glyph_map(source,0,model)
    selected=model.selected(ids)
    plan=native_text_plan(analyze(source),0,model,selected,selected,ops,mapping)
    # Pixels and characters are unchanged; only accessibility membership is
    # tampered with. A final guard must reject this independently of rendering.
    targets={mapping[g]['operation'] for g in ids}
    changed=[]
    for i,item in enumerate(ops):
        if i in targets:changed.extend([([NameObject('/Artifact')],b'BMC'),item,([],b'EMC')])
        else:changed.append(item)
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    stream=DecodedStreamObject();stream.set_data(_serialize(changed))
    writer.pages[0][NameObject('/Contents')]=writer._add_object(stream)
    saved=BytesIO();writer.write(saved);output=saved.getvalue()
    assert analyze(output).semantic()==plan.expected
    with fitz.open(stream=source,filetype='pdf') as a,fitz.open(stream=output,filetype='pdf') as b:
        assert a[0].get_pixmap().samples==b[0].get_pixmap().samples
    with pytest.raises(EditError,match='asociación'):
        plan.validate(output)


def test_reused_untouched_page_retains_source_irregularity_diagnostic():
    clear_readonly_cache()
    source=source_pdf()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc[1].insert_text((40,380),'BROWSER FOOTER')
        source=doc.tobytes(garbage=0)
    original=analyze_readonly(source)
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc.set_metadata({'title':'Fresh catalog, same page contents'})
        output=doc.tobytes(garbage=0)
    current=analyze_readonly(output)
    assert 1 in current.reused_semantic_pages_v318
    assert [x for x in current.source_irregularities if x.get('page')==1] == [
        x for x in original.source_irregularities if x.get('page')==1]


def test_gui_opens_edits_and_saves_unmarked_header(qtbot,window,tmp_path):
    from PySide6.QtGui import QTextCursor
    from test_rich_ui_v09 import idle,select
    source=source_pdf();path=tmp_path/'mixed.pdf';path.write_bytes(source)
    window.open_document(path);idle(qtbot,window)
    select(window,'SIN ETIQUETA');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible() or bool(window.last_error),timeout=15000)
    assert window.canvas.editor.isVisible(),window.last_error
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.select(QTextCursor.Document);cursor.insertText('TEXTO NUEVO')
    editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==1
    target=tmp_path/'gui-saved.pdf';window.save_as(target);idle(qtbot,window)
    assert 'TEXTO NUEVO' in PdfReader(target).pages[0].extract_text()
    assert_preserved(source,target.read_bytes())
    window.history('undo');idle(qtbot,window)
    assert 'SIN ETIQUETA' in ''.join(g.text for g in window.model.glyphs)
    assert path.read_bytes()==source

