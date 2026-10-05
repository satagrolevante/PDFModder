from io import BytesIO
import hashlib
import pytest
import pymupdf as fitz
from PIL import Image,ImageDraw
from pypdf import PdfReader

from pdfmodder.forms_redaction_v200 import (atomic_save_form_pdf,edit_form_field_pdf,
    form_fields_pdf,redact_regions_pdf)
from pdfmodder.media import add_image_pdf,edit_image_pdf,image_items,_asset_fingerprint
from pdfmodder.image_transform_v160 import transform_image_instance_pdf
from pdfmodder.model import EditError


def form_pdf(calculated=False):
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((25,40),'Contenido original intacto')
        field=fitz.Widget();field.field_name='nombre';field.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        field.rect=fitz.Rect(40,70,240,105);field.field_value='Ana';field.text_font='Helv';field.text_fontsize=11
        page.add_widget(field)
        check=fitz.Widget();check.field_name='aceptado';check.field_type=fitz.PDF_WIDGET_TYPE_CHECKBOX
        check.rect=fitz.Rect(40,130,60,150);check.field_value=False;page.add_widget(check)
        if calculated:
            owner=doc[0];widget=owner.load_widget(next(w.xref for w in owner.widgets() if w.field_name=='nombre'))
            widget.script_calc='event.value = 1 + 2;';widget.update()
        doc.new_page(width=400,height=400).insert_text((30,40),'Pagina sin cambios')
        return doc.tobytes()


def test_form_value_geometry_reopen_and_atomic_save(tmp_path):
    source=form_pdf();listing=form_fields_pdf(source);field=listing['fields'][0]
    edited,report=edit_form_field_pdf(source,0,field['xref'],{'value':'María','rect':(45,75,245,110)},listing['revision'])
    assert report['verified'] and report['interactive']
    result=form_fields_pdf(edited)['fields'][0]
    assert result['value']=='María' and result['rect']==pytest.approx((45,75,245,110))
    assert PdfReader(BytesIO(edited)).get_fields()['nombre']['/V']=='María'
    original=tmp_path/'original.pdf';original.write_bytes(source)
    target=tmp_path/'formulario.pdf';atomic_save_form_pdf(edited,target,original)
    assert original.read_bytes()==source
    assert form_fields_pdf(target.read_bytes())['fields'][0]['value']=='María'
    with pytest.raises(EditError,match='original'):atomic_save_form_pdf(edited,original,original)


def test_checkbox_logical_value_and_appearance():
    source=form_pdf();field=next(f for f in form_fields_pdf(source)['fields'] if f['name']=='aceptado')
    output,_=edit_form_field_pdf(source,0,field['xref'],{'value':True})
    assert next(f for f in form_fields_pdf(output)['fields'] if f['name']=='aceptado')['checked']
    assert str(PdfReader(BytesIO(output)).get_fields()['aceptado']['/V'])!='/Off'


def test_calculations_are_preserved_for_geometry_and_value_is_blocked():
    source=form_pdf(True);field=form_fields_pdf(source)['fields'][0]
    with pytest.raises(EditError,match='JavaScript'):edit_form_field_pdf(source,0,field['xref'],{'value':'50'})
    output,_=edit_form_field_pdf(source,0,field['xref'],{'rect':(50,80,250,115)})
    assert form_fields_pdf(output)['fields'][0]['calculation']
    assert form_fields_pdf(output)['fields'][0]['value']=='Ana'


def picture():
    image=Image.new('RGBA',(100,60),(0,0,0,0));ImageDraw.Draw(image).rectangle((5,5,75,45),fill=(220,40,50,128))
    output=BytesIO();image.save(output,format='PNG');return output.getvalue()


def test_crop_after_free_rotation_preserves_alpha_and_shared_instance():
    with fitz.open() as doc:
        p=doc.new_page(width=400,height=400);p.insert_text((20,35),'Vecino intacto')
        original=doc.tobytes()
    first,_=add_image_pdf(original,0,picture(),(80,120,240,216))
    shared,_=add_image_pdf(first,0,picture(),(30,290,130,350))
    rotated,_=transform_image_instance_pdf(shared,0,'0',rotation=27)
    with fitz.open(stream=rotated,filetype='pdf') as doc:
        item=image_items(doc,0)[0];fingerprint=_asset_fingerprint(doc,item['xref'])
        assert item['editable'] and item['effective_dpi'][0]>0
        angle=item['image_operation']['rotation']
    output,report=edit_image_pdf(rotated,0,'0',crop=(.1,.1,.8,.9),rotation=angle,fit_mode='fit')
    assert report['pixels_preserved'] and report['instance_only']
    with fitz.open(stream=output,filetype='pdf') as doc:
        rows=image_items(doc,0);assert len(rows)==2 and rows[0]['editable']
        assert _asset_fingerprint(doc,rows[0]['xref'])==fingerprint
        assert rows[0]['image_operation']['crop']==pytest.approx((.1,.1,.8,.9),abs=.0001)
        assert _asset_fingerprint(doc,rows[1]['xref'])==fingerprint
        assert rows[1]['rect']==pytest.approx((30,290,130,350))
    again,_=edit_image_pdf(output,0,'0',crop=(0,0,1,1),rotation=angle,fit_mode='fit')
    with fitz.open(stream=again,filetype='pdf') as doc:assert image_items(doc,0)[0]['image_operation']['crop']==pytest.approx((0,0,1,1))


def test_redaction_removes_visible_ocr_and_original_image_resource():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((45,70),'SECRETO',fontsize=12)
        page.insert_text((45,70),'SECRETO',fontsize=12,render_mode=3)
        page.insert_text((250,70),'Vecino',fontsize=12)
        page.insert_image((40,120,200,216),stream=picture())
        doc.new_page(width=400,height=400).insert_text((20,50),'Pagina intacta')
        source=doc.tobytes()
    zones=[{'page':0,'rect':(40,54,110,75)},{'page':0,'rect':(70,140,100,170)}]
    output,report=redact_regions_pdf(source,zones)
    assert report['verified'] and report['characters_removed']==14
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert 'SECRETO' not in doc[0].get_text() and 'Vecino' in doc[0].get_text()
        assert 'Pagina intacta' in doc[1].get_text()
        assert doc[0].get_pixmap().pixel(80,150)==(0,0,0)
        assert b'SECRETO' not in b''.join(doc.xref_stream(xref) or b'' for xref in range(1,doc.xref_length()) if doc.xref_is_stream(xref))
    reader=PdfReader(BytesIO(output));assert '/Prev' not in reader.trailer


def test_redaction_block_overlapping_annotation_and_preserve_source():
    with fitz.open() as doc:
        p=doc.new_page(width=300,height=300);p.insert_text((30,60),'Privado')
        a=p.add_text_annot((40,55),'Privado también en comentario')
        source=doc.tobytes()
    digest=hashlib.sha256(source).hexdigest()
    with pytest.raises(EditError,match='anotación'):redact_regions_pdf(source,[{'page':0,'rect':(25,40,90,85)}])
    assert hashlib.sha256(source).hexdigest()==digest
