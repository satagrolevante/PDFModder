"""Native occurrences preserve shared artwork and interactive PDF structure."""
from io import BytesIO

import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader
import pytest

from pdfmodder.model import EditError
from pdfmodder.objects_v300 import object_graph, edit_object_pdf


def document():
    image=BytesIO();Image.new('RGB',(20,10),'blue').save(image,format='PNG')
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.draw_rect((20,30,90,100),color=(0,0,1),fill=(1,0,0))
        page.insert_text((120,110),'Texto girado',fontsize=13,rotate=90)
        page.insert_text((170,170),'Vecino intacto',fontsize=11)
        page.insert_image((220,220,300,260),stream=image.getvalue())
        doc.set_metadata({'title':'Documento general','author':'PDFModder'})
        doc.new_page(width=400,height=400).insert_text((20,30),'Otra página')
        return doc.tobytes()


def native_item(data,kind,predicate=lambda row:True):
    info=object_graph(data,0)
    return info,next(row for row in info['items'] if row['kind']==kind and predicate(row))


@pytest.mark.parametrize('operation,options',[
    ('move',{'dx':12,'dy':9}),
    ('scale',{'scale_x':1.2,'scale_y':.8}),
    ('rotate',{'angle':27}),
    ('duplicate',{'dx':100,'dy':0}),
])
def test_vectors_are_native_affine_occurrences(operation,options):
    data=document();info,item=native_item(data,'vector')
    output,report=edit_object_pdf(data,0,item['id'],operation,revision=info['revision'],**options)
    assert report['verified'] and report['validation']['original_objects_unchanged']
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert after[1].get_pixmap().samples==before[1].get_pixmap().samples
        assert before[0].get_text()==after[0].get_text()
        assert after.metadata==before.metadata
        assert len(after[0].get_drawings())==len(before[0].get_drawings())+(operation=='duplicate')
        assert len(after[0].get_image_info())==1


def test_vector_colour_overrides_internal_operators_and_retains_neighbors():
    data=document();_,item=native_item(data,'vector')
    output,report=edit_object_pdf(data,0,item['id'],'properties',
        properties={'fill_color':[0,1,0],'stroke_color':[1,0,1],'line_width':3,'opacity':.5})
    assert report['properties']['line_width']==3
    with fitz.open(stream=output,filetype='pdf') as doc:
        drawing=doc[0].get_drawings()[0]
        assert drawing['fill']==(0,1,0) and drawing['color']==(1,0,1)
        assert drawing['width']==pytest.approx(3)
        assert drawing['fill_opacity']==pytest.approx(.5)
        assert 'Vecino intacto' in doc[0].get_text()


def test_rotated_text_moves_without_recomposition_or_font_substitution():
    data=document();info,item=native_item(data,'text',lambda row:'girado' in row['label'])
    output,_=edit_object_pdf(data,0,item['id'],'move',revision=info['revision'],dx=8,dy=4)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        first=before[0].get_texttrace()[0];second=after[0].get_texttrace()[0]
        assert first['font']==second['font'] and first['size']==second['size']
        assert first['dir']==second['dir']
        for a,b in zip(first['chars'],second['chars']):
            assert a[0]==b[0]
            assert b[2]==pytest.approx((a[2][0]+8,a[2][1]+4),abs=.025)
        assert after[0].get_text().count('Texto girado')==1
    assert 'Texto girado' in PdfReader(BytesIO(output)).pages[0].extract_text()


def form_document():
    with fitz.open() as artwork,fitz.open() as doc:
        source=artwork.new_page(width=220,height=100)
        source.draw_rect((10,10,110,70),color=(.2,.5,.2),fill=(.9,.95,.8))
        source.insert_text((20,45),'Fecha 2025',fontsize=11)
        page=doc.new_page(width=500,height=350)
        page.show_pdf_page(fitz.Rect(20,20,240,120),artwork,0)
        page.show_pdf_page(fitz.Rect(250,180,470,280),artwork,0)
        doc.new_page(width=500,height=350).show_pdf_page(fitz.Rect(20,20,240,120),artwork,0)
        fullpage=next(x[0] for x in doc[0].get_xobjects() if x[1]=='fullpage')
        layer=doc.add_ocg('Capa original')
        doc.xref_set_key(fullpage,'Group','<< /S /Transparency /I true /K false >>')
        doc.xref_set_key(fullpage,'OC',f'{layer} 0 R')
        doc.xref_set_key(fullpage,'PMCustom','<< /Flag true /Data (Conservar) >>')
        return doc.tobytes(),fullpage


def test_edit_one_nested_occurrence_preserves_group_layer_and_unknown_dictionary():
    data,shared=form_document();info,item=native_item(data,'text',lambda row:row['rect'][0]<100)
    assert len(item['path'])==2
    output,report=edit_object_pdf(data,0,item['id'],'move',revision=info['revision'],dx=7,dy=4)
    assert len(report['isolated_form_chain'])==2
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before.xref_object(shared)==after.xref_object(shared)
        assert before.xref_stream(shared)==after.xref_stream(shared)
        clone=next(value['copy'] for value in report['isolated_form_chain'] if value['source']==shared)
        for key in ('Group','OC','PMCustom','Matrix','BBox'):
            assert before.xref_get_key(shared,key)==after.xref_get_key(clone,key)
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        region=fitz.Rect(250,180,470,280)
        assert before[0].get_pixmap(clip=region).samples==after[0].get_pixmap(clip=region).samples
        assert after[0].get_text().count('Fecha 2025')==2
        assert len(before[0].get_drawings())==len(after[0].get_drawings())
        assert before.get_ocgs()==after.get_ocgs()


def test_image_affine_edit_preserves_original_pixel_resource():
    data=document();_,item=native_item(data,'image')
    output,_=edit_object_pdf(data,0,item['id'],'rotate',angle=30)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        first=before[0].get_image_info(hashes=True)[0]
        second=after[0].get_image_info(hashes=True)[0]
        assert first['digest']==second['digest']
        assert first['width']==second['width'] and first['height']==second['height']
        assert before[0].get_text()==after[0].get_text()


def test_object_move_checks_link_geometry_but_unrelated_forms_are_preserved():
    data=document()
    with fitz.open(stream=data,filetype='pdf') as doc:
        widget=fitz.Widget();widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name='Campo';widget.field_value='Valor';widget.rect=fitz.Rect(20,300,160,325)
        doc[0].add_widget(widget)
        doc[0].insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(220,220,300,260),'uri':'https://example.com'})
        data=doc.tobytes()
    _,item=native_item(data,'vector')
    output,_=edit_object_pdf(data,0,item['id'],'move',dx=5)
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert next(doc[0].widgets()).field_value=='Valor'
        assert doc[0].get_links()[0]['uri']=='https://example.com'
    _,image=native_item(data,'image')
    with pytest.raises(EditError,match='enlace'):
        edit_object_pdf(data,0,image['id'],'move',dx=5)


def test_stale_revision_is_rejected_before_modification():
    data=document();_,item=native_item(data,'vector')
    with pytest.raises(EditError,match='documento cambió'):
        edit_object_pdf(data,0,item['id'],'move',dx=3,revision='0'*64)


def test_signature_field_disables_inventory_operations_consistently():
    data=document()
    with fitz.open(stream=data,filetype='pdf') as doc:
        widget=fitz.Widget();widget.field_type=fitz.PDF_WIDGET_TYPE_SIGNATURE
        widget.field_name='Firma';widget.rect=fitz.Rect(20,300,160,325)
        doc[0].add_widget(widget);data=doc.tobytes()
    info,item=native_item(data,'vector')
    assert not item['capabilities']['move'] and 'firma' in item['capabilities']['reason']
    assert info['document_reason']
    with pytest.raises(EditError,match='firma'):
        edit_object_pdf(data,0,item['id'],'move',dx=1)


def test_vector_state_updates_still_apply_to_following_unselected_paint():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400);page.insert_font(fontname='helv')
        stream=doc.get_new_xref();doc.update_object(stream,'<< >>')
        doc.update_stream(stream,b'20 250 60 60 re 1 0 0 rg 0 0 1 RG 3 w B\n'
            b'150 250 60 60 re B\nBT /helv 14 Tf 1 0 0 1 150 210 Tm (Vecino) Tj ET\n')
        page.set_contents(stream);data=doc.tobytes()
    _,item=native_item(data,'vector')
    output,_=edit_object_pdf(data,0,item['id'],'move',dy=15,
        properties={'fill_color':[0,1,0],'stroke_color':[0,0,0],'line_width':1})
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        untouched=fitz.Rect(140,70,230,210)
        assert before[0].get_pixmap(clip=untouched).samples==after[0].get_pixmap(clip=untouched).samples
        assert after[0].get_drawings()[1]['fill']==(1,0,0)
        assert after[0].get_drawings()[1]['width']==3


def test_group_transform_keeps_curved_clip_and_arbitrary_affine_matrix_native():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        stream=doc.get_new_xref();doc.update_object(stream,'<< >>')
        doc.update_stream(stream,b'q 1 .2 -.15 1 120 140 cm\n'
            b'0 0 m 0 60 60 60 60 0 c 60 -60 0 -60 0 0 c W n\n'
            b'-20 -70 100 140 re .3 .5 .9 rg f Q\n'
            b'20 20 30 30 re 1 0 0 rg f\n')
        page.set_contents(stream);data=doc.tobytes()
    _,group=native_item(data,'group')
    output,report=edit_object_pdf(data,0,group['id'],'rotate',angle=18,dx=8)
    assert report['clips_preserved'] and report['vectors_retained']
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert len(doc[0].get_drawings())==2
        contents=b''.join(doc.xref_stream(ref) for ref in doc[0].get_contents())
        assert b'W' in contents and b' c\n' in contents
    before=PdfReader(BytesIO(data)).pages[0].get_contents().operations
    after=PdfReader(BytesIO(output)).pages[0].get_contents().operations
    assert sum(op==b'W' for _,op in before)==sum(op==b'W' for _,op in after)==1


def test_nonfinite_input_cannot_create_partial_candidate():
    data=document();_,item=native_item(data,'vector')
    with pytest.raises(EditError,match='finito'):
        edit_object_pdf(data,0,item['id'],'move',dx=float('nan'))
    with pytest.raises(EditError,match='escalas'):
        edit_object_pdf(data,0,item['id'],'scale',scale_x=0)
    assert object_graph(data,0)['revision']==native_item(data,'vector')[0]['revision']
