"""Native transforms keep shaped Unicode and verified font instances on reopen."""
from hashlib import sha256
import json

import pymupdf as fitz
import pytest

from pdfmodder.model import EditError
from pdfmodder.objects_v300 import object_graph,edit_object_pdf
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf,selection_payload
from pdfmodder.typography_objects_v300 import native_object_record_issue
from pdfmodder.typography_v300 import KEY,_records
from test_typography_v300 import make_shaping_font,make_variable_font,document,insert,shaped_model


TEXT='office q\u0308 שלום 123 עולם'


@pytest.fixture
def font(tmp_path):
    return make_shaping_font(tmp_path/'native-shaping.ttf')


def shaped_object(data):
    info=object_graph(data,0)
    return info,next(row for row in info['items'] if row['kind']=='text' and 'office' in row['label'])


@pytest.mark.parametrize('operation,values',[
    ('move',{'dx':7,'dy':9}),('rotate',{'angle':17}),
    ('scale',{'scale_x':1.15,'scale_y':.85}),
    ('properties',{'properties':{'fill_color':[0,0,1],'opacity':.6}}),
])
def test_native_transform_reopens_ligatures_marks_and_bidi_in_logical_order(font,tmp_path,operation,values):
    data,_=insert(document(form=True),font,TEXT)
    info,item=shaped_object(data)
    output,report=edit_object_pdf(data,0,item['id'],operation,revision=info['revision'],**values)
    assert report['typography']['verified'] and report['typography']['updated_records']==1
    model,ids=shaped_model(output)
    assert model.text(ids)==TEXT and len(model.logical_text_runs)==1
    assert selection_payload(output,0,ids)['text']==TEXT
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert after[0].get_text().count('VECINO INTACTO')==1
        assert [(w.field_name,w.field_value) for w in after[0].widgets()]==[('Nombre','Valor conservado')]
        before_font={sha256(before.extract_font(ref[0])[3]).hexdigest() for ref in before[0].get_fonts()}
        after_font={sha256(after.extract_font(ref[0])[3]).hexdigest() for ref in after[0].get_fonts()}
        assert before_font==after_font
    path=tmp_path/'transformed.pdf';path.write_bytes(output)
    from pdfmodder.worker import Session
    session=Session(path,reading=True,history_dir=tmp_path/'history')
    try:
        assert session.copy_reading_selection(0,ids=ids)['text']==TEXT
        session.prepare_editing(0)
        from pdfmodder.clipboard_ops_v170 import copy_selection_v170
        assert copy_selection_v170(session,0,ids=ids)['text']==TEXT
    finally:session.close()


def test_duplicate_is_a_separate_verified_logical_paragraph(font):
    data,_=insert(document(),font,TEXT)
    _,item=shaped_object(data)
    assert item['capabilities']['duplicate']
    output,report=edit_object_pdf(data,0,item['id'],'duplicate',dy=65)
    assert report['typography']['cloned_records']==1
    model,ids=shaped_model(output)
    assert len(model.logical_text_runs)==2
    assert len({run['paragraph_id'] for run in model.logical_text_runs})==2
    for run in model.logical_text_runs:
        chosen=[i for c in run['clusters'] for i in c['ids']]
        assert model.text(chosen)==TEXT
        assert selection_payload(output,0,chosen)['text']==TEXT
    assert not model.issues


def test_static_instances_keep_axes_and_font_hashes_after_native_scale(tmp_path):
    font=make_variable_font(tmp_path)
    runs=[dict(text='office ',font_file=str(font),font_name='PDFModderShapingTest',
               font_axes={'wght':100},font_features={'liga':1},size=12),
          dict(text='q\u0308 שלום',font_file=str(font),font_name='PDFModderShapingTest',
               font_axes={'wght':900},font_features={'liga':1},size=12)]
    data,_=edit_rich_pdf(document(),RichTextRequest(0,[],runs,rect=(35,75,390,170)))
    _,item=shaped_object(data)
    output,report=edit_object_pdf(data,0,item['id'],'scale',scale_x=1.2,scale_y=.9)
    model,ids=shaped_model(output)
    payload=selection_payload(output,0,ids)
    assert payload['text']=='office q\u0308 שלום'
    assert {run['font_axes']['wght'] for run in payload['runs']}=={100,900}
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        original=_records(before,0)[0];changed=_records(after,0)[0]
        assert [g['font_sha256'] for g in original['glyphs']]==[g['font_sha256'] for g in changed['glyphs']]
        assert [g['gid'] for g in original['glyphs']]==[g['gid'] for g in changed['glyphs']]
    assert report['typography']['updated_records']==1


def test_same_content_on_other_page_keeps_its_original_record_and_pixels(font):
    data,_=insert(document(),font,TEXT)
    with fitz.open(stream=data,filetype='pdf') as doc:
        page=doc[0];contents=page.get_contents();resources=doc.xref_get_key(page.xref,'Resources')[1]
        typography=doc.xref_get_key(page.xref,KEY)[1]
        second=doc.new_page(width=420,height=300)
        doc.xref_set_key(second.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        doc.xref_set_key(second.xref,'Resources',resources)
        doc.xref_set_key(second.xref,KEY,fitz.get_pdf_str(typography))
        data=doc.tobytes(garbage=0)
    _,item=shaped_object(data)
    output,_=edit_object_pdf(data,0,item['id'],'move',dx=5,dy=8)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert before.xref_get_key(before[1].xref,KEY)==after.xref_get_key(after[1].xref,KEY)


def test_invalid_metadata_and_split_cluster_fail_before_transform(font):
    data,_=insert(document(),font,'office')
    model,ids=shaped_model(data)
    ligature=next(c for c in model.logical_text_runs[0]['clusters'] if c['text']=='ffi')
    assert 'clúster' in native_object_record_issue(data,0,ligature['ids'][:1])
    with fitz.open(stream=data,filetype='pdf') as doc:
        records=_records(doc,0);records[0]['glyphs'][0]['origin'][0]+=100
        doc.xref_set_key(doc[0].xref,KEY,fitz.get_pdf_str(json.dumps(dict(schema=1,records=records))))
        damaged=doc.tobytes(garbage=0)
    _,item=shaped_object(damaged)
    assert not item['capabilities']['move']
    assert 'propietario' in item['capabilities']['transform_reason']
    with pytest.raises(EditError,match='propietario'):
        edit_object_pdf(damaged,0,item['id'],'move',dx=5)
