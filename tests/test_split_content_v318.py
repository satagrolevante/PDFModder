"""Content-array fragments and deletion must retain unrelated source paint."""
from io import BytesIO
from pathlib import Path
import hashlib

import pymupdf as fitz
import pytest
from PIL import Image

from pdfmodder.analysis_reuse_v315 import grouped_stream_operations_v318
from pdfmodder.clipboard_ops_v170 import apply_clipboard_v170
from pdfmodder.media import add_image_pdf, image_items, transform_image_pdf, delete_image_pdf
from pdfmodder.worker import Session
from pdfmodder.model import EditError
from pdfmodder.validation import assert_pixels,trace_chars
from dataclasses import replace


def test_dictionary_and_operand_continuation_have_exact_operation_order():
    groups=list(grouped_stream_operations_v318([b'q /Artifact <</Type ',b'/Pagination>> BDC',
        b'1 0 0 1 12 ',b'24 cm EMC Q']))
    operations=[operation for _,ops in groups for operation in ops]
    assert [op for _,op in operations]==[b'q',b'BDC',b'cm',b'EMC',b'Q']
    assert operations[2][0]==[1,0,0,1,12,24]
    assert groups[0][0]==(0,1)
    assert groups[1][0]==(2,3)
    with pytest.raises(EditError,match='incompleto'):
        list(grouped_stream_operations_v318([b'q /Artifact <</Type ']))


def fragmented_pdf():
    with fitz.open() as doc:
        page=doc.new_page(width=350,height=400)
        page.insert_text((30,40),'Original visible')
        source=page.get_contents()
        refs=[]
        for raw in (b'q /Artifact <</Type ',b'/Pagination>> BDC'):
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,raw);refs.append(xref)
        xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,b'EMC Q')
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{v} 0 R' for v in [*refs,*source,xref])+']')
        return doc.tobytes()


def test_add_then_move_and_delete_image_after_fragmented_content():
    source=fragmented_pdf()
    stream=BytesIO();Image.new('RGBA',(30,20),(0,0,0,255)).save(stream,'PNG')
    added,report=add_image_pdf(source,0,stream.getvalue(),(40,100,100,140))
    assert report['verified']
    with fitz.open(stream=added,filetype='pdf') as doc:
        item=image_items(doc,0)[0]
        assert item['editable'],item['reason']
        assert doc[0].get_text().strip()=='Original visible'
    moved,report=transform_image_pdf(added,0,item['id'],(100,170,160,210))
    assert report['verified']
    removed,report=delete_image_pdf(moved,0,item['id'])
    assert report['verified']
    with fitz.open(stream=removed,filetype='pdf') as doc,fitz.open(stream=source,filetype='pdf') as old:
        assert not doc[0].get_image_info()
        assert trace_chars(doc[0])==trace_chars(old[0])
        assert_pixels(old[0],doc[0],[])


def test_mixed_style_delete_keeps_other_words_and_history(tmp_path):
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((30,60),'Normal ',fontname='helv',fontsize=12)
        page.insert_text((75,60),'negrita',fontname='hebo',fontsize=12,color=(1,0,0))
        page.insert_text((30,110),'Conservar',fontname='helv',fontsize=11)
        source=doc.tobytes()
    path=tmp_path/'mixed.pdf';path.write_bytes(source)
    session=Session(path,history_dir=tmp_path/'history')
    try:
        model=session.page(0)['model']
        ids=[g.id for g in model.glyphs if g.origin[1]<80]
        result=apply_clipboard_v170(session,'delete',0,ids=ids,revision=hashlib.sha256(source).hexdigest())
        assert result['report']['verified']
        with fitz.open(stream=session.history.current,filetype='pdf') as doc:
            assert doc[0].get_text().strip()=='Conservar'
        session.navigate_history(False)
        assert session.history.current==source
    finally:session.close()


@pytest.mark.parametrize('rotation',[0,90])
def test_auto_adaptation_preserves_verified_footer_metric_origin(rotation):
    from test_footer_native_v303 import footer_pdf,draft,assert_preserved
    from pdfmodder.richtext import edit_rich_pdf
    source=footer_pdf(rotation=rotation)
    request=draft(source,text='FEDCBA',auto_width=True,auto_height=True,auto_adapt=True)
    output,report=edit_rich_pdf(source,request)
    assert report['verified'] and report['auto_adapt']
    assert report.get('clip_paint_verified') or report.get('clip_expanded_for_replacement')
    assert report['clip_metric_overhang_verified']
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
    clipped=footer_pdf(clip_top=176,rotation=rotation)
    output,report=edit_rich_pdf(clipped,draft(clipped,text='FEDCBA',auto_width=True,auto_height=True,auto_adapt=True))
    assert report['verified'] and report.get('clip_expanded_for_replacement')
