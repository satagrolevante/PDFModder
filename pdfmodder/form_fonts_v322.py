"""Explicit AcroForm fonts and verified local normal-appearance generation."""
from __future__ import annotations

import hashlib
import unicodedata
import pymupdf as fitz
from pypdf.generic import ContentStream, DecodedStreamObject

from .fonts import FontError, FontResolver
from .font_choice_v321 import FontChoiceRequired
from .model import EditError


def owned_widget_font(doc, widget):
    name=widget.text_font or ''
    if not name.startswith('PMForm'):
        return None
    kind,value=doc.xref_get_key(doc.pdf_catalog(),'AcroForm/DR/Font/'+name)
    if kind!='xref':
        raise EditError('La fuente elegida del campo ya no está en sus recursos; vuelve a elegirla.')
    xref=int(value.split()[0]);buffer=doc.extract_font(xref)[3]
    if not buffer:
        raise EditError('No se puede recuperar el programa de la fuente elegida del campo.')
    return {'resource':name,'xref':xref,'buffer':buffer}


def replace_widget_font(doc, page, widget, choice, *, existing=None):
    """Generate chosen glyphs without PyMuPDF's custom-font Helvetica fallback."""
    value=str(widget.field_value or '')
    from fontTools.unicodedata import script
    if any(unicodedata.combining(c) or unicodedata.bidirectional(c) in ('R','AL','AN')
           or script(c) not in ('Latn','Grek','Cyrl','Hani','Hira','Kana','Hang','Zyyy','Zinh','Zzzz') for c in value):
        raise EditError('Este campo necesita composición tipográfica avanzada para conservar sus letras; conserva su fuente original o edita su valor con una herramienta compatible.')
    listbox=widget.field_type==fitz.PDF_WIDGET_TYPE_LISTBOX
    choices=widget.choice_values or []
    coverage=value+('\n'+'\n'.join(str(v[-1] if isinstance(v,(list,tuple)) else v) for v in choices) if listbox else '')
    old_name=widget.text_font or 'original'
    if existing is None:
        if not isinstance(choice,dict) or set(choice)-{'name','path','font_file','font_axes'} or not isinstance(choice.get('name'),str):
            raise EditError('Elige expresamente una fuente del catálogo o un archivo TTF/OTF para el campo.')
        try:
            face=FontResolver().resolve_explicit(choice['name'],coverage,
                font_file=choice.get('path') or choice.get('font_file'),font_axes=choice.get('font_axes'))
        except FontError as error:
            raise FontChoiceRequired(str(error),{'font_name':choice['name']},value) from error
        buffer=bytes(face.buffer or face.font.buffer)
        resource='PMForm'+hashlib.sha256(buffer).hexdigest()[:12]
        candidate=resource;serial=1
        while doc.xref_get_key(doc.pdf_catalog(),'AcroForm/DR/Font/'+candidate)[0]!='null':
            candidate=resource+str(serial);serial+=1
        resource=candidate
    else:
        buffer=existing['buffer'];resource=existing['resource']
    widget_xref=widget.xref
    kind,ap=doc.xref_get_key(widget_xref,'AP/N')
    if kind!='xref':raise EditError('La apariencia normal del campo no es un recurso verificable.')
    ap_xref=int(ap.split()[0])
    kind,rotation=doc.xref_get_key(widget_xref,'MK/R')
    if kind!='null' and float(rotation)%360:
        raise EditError('La fuente alternativa de un campo girado requiere conservar su matriz; conserva la fuente original.')
    width,height=widget.rect.width,widget.rect.height
    size=float(widget.text_fontsize or 0);color=tuple(widget.text_color or (0.,0.,0.))
    flags=widget.field_flags
    max_length=widget.text_maxlen
    q=0;node=widget_xref;seen=set()
    while node not in seen:
        seen.add(node);kind,number=doc.xref_get_key(node,'Q')
        if kind in ('int','real'):q=int(number);break
        kind,parent=doc.xref_get_key(node,'Parent')
        if kind!='xref':break
        node=int(parent.split()[0])
    if q not in (0,1,2):raise EditError('La alineación del campo no es verificable.')
    raw=DecodedStreamObject();raw.set_data(doc.xref_stream(ap_xref))
    retained=[];inside=False
    for args,op in ContentStream(raw,None).operations:
        if op==b'BT':
            if inside:raise EditError('La apariencia del campo contiene bloques de texto anidados.')
            inside=True
        elif op==b'ET':
            if not inside:raise EditError('La apariencia del campo contiene un cierre de texto sin apertura.')
            inside=False
        elif not inside:retained.append((args,op))
    if inside:raise EditError('La apariencia del campo deja un bloque de texto abierto.')
    scratch=doc.new_page(width=width,height=height);scratch_number=scratch.number
    try:
        list_rows=[]
        if listbox:
            kind,resources=doc.xref_get_key(ap_xref,'Resources')
            if kind not in ('xref','dict'):raise EditError('No se pueden conservar los recursos visuales de la lista.')
            doc.xref_set_key(scratch.xref,'Resources',resources)
            scratch.set_contents(ap_xref)
            for block in scratch.get_text('dict')['blocks']:
                if block['type']==0:
                    for line in block['lines']:
                        for span in line['spans']:
                            if span['text']:list_rows.append((span['text'],span['origin'],span['size']))
            empty=doc.get_new_xref();doc.update_object(empty,'<<>>');doc.update_stream(empty,b'')
            scratch.set_contents(empty)
            doc.xref_set_key(scratch.xref,'Resources','<<>>')
        generated=scratch.insert_font(fontname=resource,fontbuffer=buffer)
        padding=2.
        if width<=padding*2 or height<=padding*2:
            raise EditError('El campo es demasiado pequeño para mostrar el texto con la fuente elegida.')
        font=fitz.Font(fontbuffer=buffer)
        actual_size=size or min(12.,(height-padding*2)/max(.1,font.ascender-font.descender))
        if listbox:
            for label,origin,row_size in list_rows:
                scratch.insert_text(origin,label,fontname=resource,fontsize=row_size,color=color)
            appearance_text='\n'.join(label for label,_,_ in list_rows)
        elif flags & fitz.PDF_TX_FIELD_IS_MULTILINE:
            result=scratch.insert_textbox((padding,padding,width-padding,height-padding),value,
                fontname=resource,fontsize=actual_size,color=color,align=q)
            if result<0:raise EditError('El texto no cabe en el campo con la fuente elegida; amplía el campo o elige otra fuente.')
            appearance_text=value
        else:
            if '\n' in value or '\r' in value:
                raise EditError('El campo no es multilínea; conserva una sola línea o cambia su definición en el formulario.')
            text_width=font.text_length(value,fontsize=actual_size)
            if not size and text_width>width-padding*2:
                actual_size*=max(.05,(width-padding*2)/max(.1,text_width))
                text_width=font.text_length(value,fontsize=actual_size)
            x=padding if q==0 else (width-text_width)/2 if q==1 else width-padding-text_width
            baseline=(height-(font.ascender-font.descender)*actual_size)/2+font.ascender*actual_size
            if flags & fitz.PDF_TX_FIELD_IS_COMB:
                if max_length<=0 or len(value)>max_length:
                    raise EditError('El campo de casillas de texto necesita una longitud máxima válida.')
                step=width/max_length
                for index,char in enumerate(value):
                    char_width=font.text_length(char,fontsize=actual_size)
                    scratch.insert_text((step*(index+.5)-char_width/2,baseline),char,
                        fontname=resource,fontsize=actual_size,color=color)
            else:
                scratch.insert_text((x,baseline),value,fontname=resource,fontsize=actual_size,color=color)
            appearance_text=value
        text=b'\n'.join(doc.xref_stream(xref) for xref in scratch.get_contents())
        from .clipping import _serialize
        clip=f'q {padding} {padding} {width-padding*2} {height-padding*2} re W n\n'.encode()
        doc.update_stream(ap_xref,_serialize(retained)+b'\n'+clip+text+b'\nQ')
        if existing is None:
            font_xref=generated
            doc.xref_set_key(doc.pdf_catalog(),'AcroForm/DR/Font/'+resource,f'{font_xref} 0 R')
        else:font_xref=existing['xref']
        doc.xref_set_key(ap_xref,'Resources/Font/'+resource,f'{font_xref} 0 R')
        components=' '.join(f'{float(v):g}' for v in color)
        operator={1:'g',3:'rg',4:'k'}.get(len(color))
        if operator is None:raise EditError('El color de texto del campo no es verificable.')
        da=f'{components} {operator} /{resource} {size:g} Tf'
        doc.xref_set_key(widget_xref,'DA',fitz.get_pdf_str(da))
        field=widget_xref;seen=set()
        while field not in seen:
            seen.add(field)
            if doc.xref_get_key(field,'T')[0]!='null':break
            kind,parent=doc.xref_get_key(field,'Parent')
            if kind!='xref':break
            field=int(parent.split()[0])
        if field!=widget_xref:doc.xref_set_key(field,'DA',fitz.get_pdf_str(da))
    finally:doc.delete_page(scratch_number)
    if hashlib.sha256(doc.extract_font(font_xref)[3]).digest()!=hashlib.sha256(buffer).digest():
        raise EditError('La apariencia no conserva el programa de fuente elegido.')
    return {'explicit':existing is None,'resource':resource,'font_sha256':hashlib.sha256(buffer).hexdigest(),
            'default_appearance':da,'effective_size':actual_size,'face':choice.get('name') if choice else old_name,
            'appearance_rebuilt':True,'appearance_text':appearance_text,'comb':bool(flags & fitz.PDF_TX_FIELD_IS_COMB)}
