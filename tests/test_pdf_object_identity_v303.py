"""Object identity accepts storage conversion without accepting resource changes."""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
from PIL import Image
import pytest

from pdfmodder.model import EditError
from pdfmodder.objects_v300 import _validate, edit_object_pdf
from pdfmodder.pdf_object_identity_v303 import assert_pdf_object_identity
from test_objects_v300 import document, native_item, form_document
from test_typography_v300 import make_shaping_font


def compressed_document():
    with fitz.open(stream=document(), filetype='pdf') as doc:
        doc.xref_set_key(doc[1].xref, 'PMUnknown', '<< /Flag true /Kind /Sample /Label (Sample) >>')
        return doc.tobytes(use_objstms=1, no_new_id=True)


def save(doc):
    return doc.tobytes(garbage=0, deflate=False, no_new_id=True)


def owned_page(source):
    page=PdfReader(BytesIO(source), strict=True).pages[0].indirect_reference
    return {(page.idnum, page.generation): {'/Contents', '/Resources'}}


def test_compressed_objects_flatten_without_losing_original_identity():
    source=compressed_document()
    assert PdfReader(BytesIO(source), strict=True).xref_objStm
    with fitz.open(stream=source, filetype='pdf') as doc:
        output=save(doc)
    proof=assert_pdf_object_identity(source, output)
    assert proof.report['verified'] and proof.report['reference_preserving']
    assert proof.report['unreachable_storage_containers']
    assert not proof.candidate_reader.xref_objStm


@pytest.mark.parametrize('kind,operation,values', [
    ('image','move',{'dx':1}),
    ('vector','properties',{'properties':{'fill_color':(.1,.3,.7)}}),
    ('text','scale',{'scale_x':.99,'scale_y':.99}),
])
def test_actual_native_edits_of_compressed_pdf_keep_shared_resources(kind,operation,values):
    source=compressed_document();_,item=native_item(source,kind)
    output,report=edit_object_pdf(source,0,item['id'],operation,**values)
    assert report['verified']
    assert report['validation']['object_identity']['native_page_fonts_preserved']
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples


@pytest.mark.parametrize('key,value', [('Flag','1'),('Kind','(Sample)'),('Label','/Sample')])
def test_typed_pdf_values_cannot_be_replaced_by_python_equal_values(key,value):
    source=compressed_document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc.xref_set_key(doc[1].xref,'PMUnknown/'+key,value)
        output=save(doc)
    with pytest.raises(EditError,match='recurso original'):
        assert_pdf_object_identity(source,output)


def test_other_page_and_root_tag_properties_are_not_owned_by_target_edit():
    source=document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc.xref_set_key(doc.pdf_catalog(),'MarkInfo','<< /Marked true >>')
        doc.xref_set_key(doc.pdf_catalog(),'StructTreeRoot','<< /Type /StructTreeRoot /K [] >>')
        source=save(doc)
    for target,key,value in [('page','Rotate','90'),('catalog','MarkInfo/Marked','false'),
                             ('catalog','StructTreeRoot/K','[1]')]:
        with fitz.open(stream=source,filetype='pdf') as doc:
            xref=doc[1].xref if target=='page' else doc.pdf_catalog()
            doc.xref_set_key(xref,key,value);output=save(doc)
        with pytest.raises(EditError,match='recurso original'):
            assert_pdf_object_identity(source,output,allowed_dictionary_keys=owned_page(source))


def test_replacing_font_resource_reference_by_identical_clone_is_rejected():
    source=document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        page=doc[0];font=page.get_fonts()[0]
        clone=doc.get_new_xref();doc.update_object(clone,doc.xref_object(font[0]))
        resource=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
        copy=doc.get_new_xref();doc.update_object(copy,doc.xref_object(resource))
        doc.xref_set_key(copy,'Font/'+font[4],f'{clone} 0 R')
        doc.xref_set_key(page.xref,'Resources',f'{copy} 0 R');output=save(doc)
    with pytest.raises(EditError,match='fuentes originales'):
        assert_pdf_object_identity(source,output,allowed_dictionary_keys=owned_page(source),require_page_fonts=0)


def test_changed_original_font_dictionary_rejected_even_inside_owned_pixel_area():
    source=document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        font=doc[0].get_fonts()[0][0]
        doc.xref_set_key(font,'BaseFont','/Courier');output=save(doc)
    with pytest.raises(EditError,match='recurso original'):
        _validate(source,output,0,[(0,0,400,400)])


def test_changed_original_embedded_font_program_is_rejected(tmp_path):
    font=make_shaping_font(tmp_path/'identity.ttf')
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=200)
        page.insert_font(fontname='Original',fontfile=str(font))
        page.insert_text((30,60),'office',fontname='Original');source=save(doc)
    with fitz.open(stream=source,filetype='pdf') as doc:
        programs=[xref for xref in range(1,doc.xref_length()) if doc.xref_is_stream(xref) and
                  doc.xref_get_key(xref,'Length1')[0]!='null']
        assert programs
        xref=programs[0];buffer=bytearray(doc.xref_stream(xref));buffer[-1]^=1
        doc.update_stream(xref,bytes(buffer));output=save(doc)
    with pytest.raises(EditError,match='flujo original'):
        assert_pdf_object_identity(source,output)


def test_changed_image_bytes_rejected_even_inside_owned_pixel_area():
    source=document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        image=doc[0].get_images()[0][0]
        buffer=bytearray(doc.xref_stream(image));buffer[0]^=1
        doc.update_stream(image,bytes(buffer));output=save(doc)
    with pytest.raises(EditError,match='flujo original'):
        _validate(source,output,0,[(0,0,400,400)])


@pytest.mark.parametrize('alteration',['remove_filter','color_transform'])
def test_opaque_jpeg_codec_properties_are_not_just_compression(alteration):
    image=BytesIO();Image.new('RGB',(8,8),'red').save(image,format='JPEG')
    with fitz.open() as doc:
        page=doc.new_page(width=200,height=200)
        xref=page.insert_image((20,20,100,100),stream=image.getvalue());source=save(doc)
    with fitz.open(stream=source,filetype='pdf') as doc:
        assert doc.xref_get_key(xref,'Filter')==('name','/DCTDecode')
        if alteration=='remove_filter':
            doc.update_stream(xref,doc.xref_stream_raw(xref),compress=False)
        else:
            doc.xref_set_key(xref,'DecodeParms','<< /ColorTransform 0 >>')
        output=save(doc)
    # Pypdf returns the same JPEG payload for either declaration. A bytes-only
    # check would accept a changed pixel interpretation or an unfiltered JPEG.
    a=PdfReader(BytesIO(source),strict=True).get_object(xref)
    b=PdfReader(BytesIO(output),strict=True).get_object(xref)
    assert a.get_data()==b.get_data()
    with pytest.raises(EditError,match='recurso original'):
        assert_pdf_object_identity(source,output,allowed_dictionary_keys=owned_page(source))


def test_storage_container_cannot_be_reused_as_a_reachable_image_resource():
    source=compressed_document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        storage=next(xref for xref in range(1,doc.xref_length()) if
                     doc.xref_get_key(xref,'Type')==('name','/ObjStm'))
        doc.update_object(storage,'<< /Type /XObject /Subtype /Image /Width 1 /Height 1 '
                          '/ColorSpace /DeviceRGB /BitsPerComponent 8 >>')
        doc.update_stream(storage,b'\xff\x00\x00')
        doc.xref_set_key(doc[0].xref,'Resources',f'<< /XObject << /Injected {storage} 0 R >> >>')
        output=save(doc)
    with pytest.raises(EditError,match='recurso original'):
        assert_pdf_object_identity(source,output,allowed_dictionary_keys=owned_page(source))


def test_unreachable_ordinary_object_is_not_disregarded_as_storage():
    source=document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        orphan=doc.get_new_xref();doc.update_object(orphan,'<< /Type /Font /BaseFont /Helvetica >>')
        source=save(doc)
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc.xref_set_key(orphan,'BaseFont','/Courier');output=save(doc)
    with pytest.raises(EditError,match='recurso original'):
        assert_pdf_object_identity(source,output)


@pytest.mark.parametrize('font_replacement',['identical_clone','other_original_font'])
def test_owned_form_fonts_keep_exact_source_aliases_and_references(monkeypatch,font_replacement):
    from pdfmodder import objects_v300 as native
    source,_=form_document()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc[1].insert_text((300,320),'Control',fontname='cour');source=save(doc)
    _,item=native_item(source,'text',lambda row:row['rect'][0]<100)
    captured={};validate=native._validate
    def record(*args,**kwargs):
        captured['fonts']=kwargs['form_font_context']
        return validate(*args,**kwargs)
    monkeypatch.setattr(native,'_validate',record)
    output,report=edit_object_pdf(source,0,item['id'],'move',dx=7,dy=4)
    assert report['validation']['object_identity']['owned_form_font_bindings_checked']==2
    with fitz.open(stream=output,filetype='pdf') as doc:
        clone=report['isolated_form_chain'][0]['copy']
        resources=int(doc.xref_get_key(clone,'Resources')[1].split()[0])
        font=doc[0].get_fonts(full=True)[0]
        if font_replacement=='identical_clone':
            replacement=doc.get_new_xref();doc.update_object(replacement,doc.xref_object(font[0]))
        else:
            replacement=next(row[0] for row in doc[1].get_fonts() if row[3]=='Courier')
        doc.xref_set_key(resources,'Font/'+font[4],f'{replacement} 0 R');damaged=save(doc)
    with pytest.raises(EditError,match='fuentes originales del Form'):
        validate(source,damaged,0,report['source_regions']+report['destination_regions'],
                 form_font_context=captured['fonts'])
    with pytest.raises(EditError,match='Form nuevo'):
        validate(source,damaged,0,report['source_regions']+report['destination_regions'])
