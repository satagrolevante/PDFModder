"""AcroForm editing and destructive redaction, isolated from ordinary text editing.

Widgets stay interactive. JavaScript calculations are preserved, never executed
or silently replaced. Redactions remove text (including OCR) and image pixels;
tag semantics and unsupported overlapping objects require an explicit decision.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import math
import os
import tempfile

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream

from .engine import full_write
from .model import EditError
from .validation import _canonical, assert_characters, assert_pixels, related, trace_chars


def _pdf_value(value, seen=None):
    seen=set() if seen is None else seen
    if hasattr(value,'get_object'):
        resolved=value.get_object()
        if resolved is not value:
            marker=(getattr(value,'idnum',None),getattr(value,'generation',None))
            if marker in seen:return '<cycle>'
            return _pdf_value(resolved,seen|{marker})
    if hasattr(value,'get_data'):
        return {'decoded_stream_sha256':hashlib.sha256(value.get_data()).hexdigest(),
                'dictionary':{str(k):_pdf_value(v,seen) for k,v in value.items() if str(k) not in ('/Length','/Filter','/DecodeParms')}}
    if isinstance(value,dict):return {str(k):_pdf_value(v,seen) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return tuple(_pdf_value(v,seen) for v in value)
    return str(value) if not isinstance(value,(str,int,float,bool,type(None))) else value


def _form_snapshot(data):
    reader=PdfReader(BytesIO(data),strict=True)
    form=reader.trailer['/Root'].get('/AcroForm')
    form=form.get_object() if form else {}
    fields=reader.get_fields() or {}
    protected={name:{str(k):_pdf_value(v) for k,v in field.items()
                     if str(k) not in ('/V','/AP','/AS','/Rect','/Kids','/Parent')}
               for name,field in fields.items()}
    widgets=[]
    for number,page in enumerate(reader.pages):
        for ref in page.get('/Annots',[]):
            item=ref.get_object()
            if item.get('/Subtype')=='/Widget':
                widgets.append((number,item.get('/T'),str(item.get('/FT')),item.get('/Rect'),
                                _pdf_value(item.get('/AA')),int(item.get('/Ff',0))))
    def field_name(ref):
        node=ref.get_object();names=[];seen=set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            if node.get('/T'):names.append(str(node['/T']))
            parent=node.get('/Parent');node=parent.get_object() if parent else None
        return '.'.join(reversed(names))
    return reader,protected,(tuple(field_name(ref) for ref in form.get('/CO',[])),bool(form.get('/XFA'))),widgets


def _guard(data,*,forms=False):
    reader=PdfReader(BytesIO(data),strict=True)
    if reader.is_encrypted:raise EditError('Abre una copia descifrada con credenciales autorizadas para esta operación.')
    root=reader.trailer['/Root']
    form=root.get('/AcroForm');form=form.get_object() if form else {}
    if form.get('/XFA'):raise EditError('Formulario XFA: no se modifica su estructura XML ni sus cálculos.')
    if root.get('/Perms') or any(f.get('/FT')=='/Sig' and f.get('/V') for f in (reader.get_fields() or {}).values()):
        raise EditError('El documento ya está firmado o certificado; esta operación invalidaría su firma.')
    with fitz.open(stream=data,filetype='pdf') as doc:
        if not doc.permissions & fitz.PDF_PERM_MODIFY:raise EditError('El documento no concede permiso para modificar su contenido.')
    if not forms and form.get('/Fields'):raise EditError('Censura: hay campos de formulario. Exporta antes una copia estática revisada; los valores también pueden existir fuera de la página.')
    return reader


def form_fields_pdf(data):
    reason=''
    try:_guard(data,forms=True)
    except EditError as error:reason=str(error)
    rows=[]
    with fitz.open(stream=data,filetype='pdf') as doc:
        for number in range(doc.page_count):
            page=doc[number]
            for widget in page.widgets() or []:
                scripts={key:getattr(widget,key,None) for key in ('script','script_calc','script_format','script_stroke','script_change','script_blur','script_focus')}
                supported=widget.field_type in (fitz.PDF_WIDGET_TYPE_TEXT,fitz.PDF_WIDGET_TYPE_CHECKBOX,fitz.PDF_WIDGET_TYPE_COMBOBOX,fitz.PDF_WIDGET_TYPE_LISTBOX)
                why=reason or ('Los campos de firma, botones y grupos de radio requieren su herramienta específica.' if not supported else '')
                rows.append({'page':number,'xref':widget.xref,'name':widget.field_name,'value':widget.field_value,
                             'type':widget.field_type_string,'field_type':widget.field_type,'rect':tuple(widget.rect),
                             'font':widget.text_font,'size':widget.text_fontsize,'max_length':widget.text_maxlen,
                             'choices':widget.choice_values or [],'checked':widget.field_value==widget.on_state() if widget.field_type==fitz.PDF_WIDGET_TYPE_CHECKBOX else False,
                             'editable':not why,'reason':why,'read_only':bool(widget.field_flags & 1),
                             'scripts':bool(any(scripts.values())),'calculation':bool(scripts['script_calc'])})
    reader=PdfReader(BytesIO(data));root=reader.trailer['/Root'];form=root.get('/AcroForm');form=form.get_object() if form else {}
    names=root.get('/Names');names=names.get_object() if names else {}
    opening=root.get('/OpenAction');opening=opening.get_object() if opening else None
    document_scripts=bool(names.get('/JavaScript') or root.get('/AA') or isinstance(opening,dict) and opening.get('/S')=='/JavaScript')
    return {'fields':rows,'revision':hashlib.sha256(data).hexdigest(),'reason':reason,
            'has_calculations':bool(form.get('/CO')) or any(row['calculation'] for row in rows),
            'has_document_scripts':document_scripts}


def _verify_field_linkage(reader,page,xref,name,affected):
    root=reader.trailer['/Root'];form=root.get('/AcroForm');form=form.get_object() if form else {}
    tree_refs=set();seen=set()
    def visit(ref):
        marker=getattr(ref,'idnum',None)
        if marker in seen:return
        seen.add(marker)
        if marker is not None:tree_refs.add(marker)
        node=ref.get_object()
        for child in node.get('/Kids',[]):visit(child)
    for ref in form.get('/Fields',[]):visit(ref)
    owners=set()
    for row in affected:
        ref=next((r for r in reader.pages[row['page']].get('/Annots',[]) if getattr(r,'idnum',None)==row['xref']),None)
        if ref is None or row['xref'] not in tree_refs:
            raise EditError('El widget está huérfano o fuera del árbol AcroForm; no se añaden campos duplicados.')
        node=ref.get_object();owner=getattr(ref,'idnum',None);visited=set()
        while not node.get('/T') and node.get('/Parent'):
            parent=node['/Parent'];marker=getattr(parent,'idnum',None)
            if marker in visited:raise EditError('El formulario tiene una relación Parent circular.')
            visited.add(marker);owner=marker;node=parent.get_object()
        owners.add(owner)
    if len(owners)>1:raise EditError('Hay campos independientes con el mismo nombre; no se puede decidir qué valor canónico modificar.')


def _check_widget_characters(doc,widget,text):
    base={'helv':'Helvetica','hebo':'Helvetica-Bold','heit':'Helvetica-Oblique','hebi':'Helvetica-BoldOblique',
          'cour':'Courier','cobo':'Courier-Bold','coit':'Courier-Oblique','cobi':'Courier-BoldOblique',
          'tiro':'Times-Roman','tibo':'Times-Bold','tiit':'Times-Italic','tibi':'Times-BoldItalic',
          'symb':'Symbol','zadb':'ZapfDingbats'}
    name=widget.text_font
    kind,value=doc.xref_get_key(doc.pdf_catalog(),'AcroForm/DR/Font/'+name)
    font=None
    if kind=='xref':
        resource=int(value.split()[0]);content=doc.extract_font(resource)[3]
        if content:font=fitz.Font(fontbuffer=content)
    if font is None and name.lower() in base:font=fitz.Font(fontname=base[name.lower()])
    if font is None:raise EditError('No se puede verificar la cobertura de la fuente del formulario. Importa o recupera su recurso original antes de cambiar el valor.')
    missing=sorted({char for char in text if char not in '\n\r\t' and not font.has_glyph(ord(char),fallback=False)})
    if missing:raise EditError('La fuente del formulario no contiene estos caracteres: '+''.join(missing))


def edit_form_field_pdf(data,page,xref,changes,revision=None):
    _guard(data,forms=True)
    if revision and revision!=hashlib.sha256(data).hexdigest():raise EditError('El formulario cambió; vuelve a seleccionar el campo.')
    if not isinstance(changes,dict) or set(changes)-{'value','rect'}:raise EditError('Sólo se admiten valor, posición y dimensiones del campo.')
    listing=form_fields_pdf(data)
    selected=next((f for f in listing['fields'] if f['page']==page and f['xref']==xref),None)
    if not selected or not selected['editable']:raise EditError(selected['reason'] if selected else 'El campo seleccionado ya no existe.')
    value_change='value' in changes and changes['value']!=selected['value']
    if value_change and selected['read_only']:raise EditError('El campo es de sólo lectura; no se cambia su valor.')
    if value_change and (listing['has_calculations'] or listing['has_document_scripts'] or selected['scripts']):
        raise EditError('Este formulario usa cálculos o validaciones JavaScript. Se conservan sus scripts; sólo puedes mover o redimensionar campos hasta disponer de un evaluador compatible.')
    reader,protected,form_state,_=_form_snapshot(data)
    if selected['name'] not in (reader.get_fields() or {}):raise EditError('El widget no está enlazado al árbol AcroForm; no se crea un campo duplicado.')
    affected=[f for f in listing['fields'] if f['name']==selected['name']] if value_change else [selected]
    _verify_field_linkage(reader,page,xref,selected['name'],affected)
    new_rect=fitz.Rect(changes.get('rect',selected['rect']))
    with fitz.open(stream=data,filetype='pdf') as doc:
        target=doc[page]
        bounds=fitz.Rect(0,0,target.cropbox.width,target.cropbox.height)
        if new_rect.is_empty or not all(math.isfinite(v) for v in new_rect) or not bounds.contains(new_rect):
            raise EditError('El campo debe tener dimensiones positivas y quedar dentro de la página.')
        for row in affected:
            owner=doc[row['page']]
            widget=owner.load_widget(row['xref'])
            if value_change:
                value=changes['value']
                if widget.field_type==fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    if not isinstance(value,bool):raise EditError('El valor de una casilla debe ser marcado o desmarcado.')
                    widget.field_value=widget.on_state() if value else 'Off'
                else:
                    value=str(value)
                    if widget.text_maxlen and len(value)>widget.text_maxlen:raise EditError(f'El campo admite como máximo {widget.text_maxlen} caracteres.')
                    if widget.field_type in (fitz.PDF_WIDGET_TYPE_COMBOBOX,fitz.PDF_WIDGET_TYPE_LISTBOX) and value not in widget.choice_values:
                        raise EditError('El valor debe pertenecer a las opciones del campo.')
                    if widget.text_font not in doc.FormFonts and widget.text_font.lower() not in ('helv','hebo','heit','hebi','cour','cobo','coit','cobi','tiro','tibo','tiit','tibi','symb','zadb'):
                        raise EditError('Falta el recurso de fuente del formulario; se evita una sustitución silenciosa.')
                    _check_widget_characters(doc,widget,value)
                    widget.field_value=value
            if row['xref']==xref and row['page']==page:widget.rect=new_rect
            # Position-only changes update Rect directly: preserve the exact
            # appearance and all JavaScript instead of regenerating either.
            if not value_change:
                rotation=owner.rotation
                try:
                    owner.set_rotation(0)
                    pdf_rect=new_rect*~owner.transformation_matrix
                finally:owner.set_rotation(rotation)
                doc.xref_set_key(widget.xref,'Rect','['+' '.join(f'{v:.9f}' for v in pdf_rect)+']')
            else:widget.update()
        output=full_write(doc)
    after,after_protected,after_state,_=_form_snapshot(output)
    if protected!=after_protected or form_state!=after_state:
        raise EditError('La operación alteró propiedades, opciones, scripts o el orden de cálculo del formulario.')
    output_listing=form_fields_pdf(output)
    if len(listing['fields'])!=len(output_listing['fields']):raise EditError('Cambió el número de widgets del formulario.')
    for old,new in zip(listing['fields'],output_listing['fields']):
        if any(old[key]!=new[key] for key in ('page','name','field_type','font','size','max_length','choices','read_only','scripts','calculation')):
            raise EditError('Se alteraron propiedades de un campo ajeno a la operación.')
        if (old['page'],old['xref'])!=(page,xref) and max(abs(a-b) for a,b in zip(old['rect'],new['rect']))>.035:
            raise EditError('Se movió otro campo de formulario.')
        if old['name']!=selected['name'] and old['value']!=new['value']:raise EditError('Se alteró otro valor de formulario.')
        if old['name']==selected['name'] and value_change:
            if selected['field_type']==fitz.PDF_WIDGET_TYPE_CHECKBOX:
                if new['checked'] is not changes['value']:raise EditError('La casilla no conserva el estado solicitado.')
            elif str(new['value'])!=str(changes['value']):raise EditError('La apariencia del widget no coincide con el valor canónico.')
    expected_values={name:_pdf_value(field.get('/V')) for name,field in (reader.get_fields() or {}).items()}
    if value_change:
        expected_values[selected['name']]=str(changes['value']) if selected['field_type']!=fitz.PDF_WIDGET_TYPE_CHECKBOX else None
    for name,field in (after.get_fields() or {}).items():
        if name!=selected['name'] or not value_change:
            if _pdf_value(field.get('/V'))!=expected_values[name]:raise EditError('Se alteró el valor de otro campo.')
        elif selected['field_type']!=fitz.PDF_WIDGET_TYPE_CHECKBOX and str(field.get('/V',''))!=str(changes['value']):
            raise EditError('El valor canónico AcroForm no coincide con el valor solicitado.')
    reports=[]
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after_doc:
        if before.page_count!=after_doc.page_count or before.metadata!=after_doc.metadata or before.get_xml_metadata()!=after_doc.get_xml_metadata() or _canonical(before.get_toc(False))!=_canonical(after_doc.get_toc(False)):
            raise EditError('El formulario alteró la estructura del documento.')
        for number in range(before.page_count):
            a,b=before[number],after_doc[number]
            if (tuple(a.cropbox),tuple(a.mediabox),a.rotation)!=(tuple(b.cropbox),tuple(b.mediabox),b.rotation):raise EditError('El formulario alteró dimensiones de página.')
            excluded=[row['rect'] for row in affected if row['page']==number]
            if number==page:excluded.append(tuple(new_rect))
            first,second=related(a),related(b)
            first.pop('widgets');second.pop('widgets')
            if first!=second:raise EditError('Se alteró contenido ajeno a los campos editados.')
            # Page text streams are byte-for-byte unchanged. get_texttrace()
            # also includes widget appearances, whose selected values may
            # legitimately change independently from ordinary page text.
            if b''.join(before.xref_stream(x) for x in a.get_contents())!=b''.join(after_doc.xref_stream(x) for x in b.get_contents()):
                raise EditError('Se alteraron los operadores de texto de la página al editar el formulario.')
            reports.append(assert_pixels(a,b,excluded))
        # Widget appearance and logical value must both survive a reopen.
        for row in affected:
            widget=next((w for w in after_doc[row['page']].widgets() or [] if w.field_name==row['name']),None)
            if widget is None or after_doc.xref_get_key(widget.xref,'AP/N')[0]=='null':raise EditError('El campo no tiene apariencia normal después del guardado.')
            if row['page']==page and row['xref']==xref and max(abs(a-b) for a,b in zip(widget.rect,new_rect))>.035:
                raise EditError('El campo no conserva la posición y dimensiones solicitadas.')
    return output,{'verified':True,'operation':'form_widget','page':page,'field_name':selected['name'],
                   'source_regions':[selected['rect']],'destination_regions':[tuple(new_rect)],
                   'pages':reports,'interactive':True,'javascript_preserved':True,'independent_parser':'pypdf'}


def atomic_save_form_pdf(data,path,source=None):
    _guard(data,forms=True)
    target=Path(path).resolve()
    if source and (target==Path(source).resolve() or target.exists() and os.path.samefile(target,source)):
        raise EditError('Guardar como no puede sobrescribir el original.')
    with fitz.open(stream=data,filetype='pdf') as doc:output=full_write(doc)
    before,bp,bs,_=_form_snapshot(data);after,ap,ass,_=_form_snapshot(output)
    if bp!=ap or bs!=ass or _pdf_value(before.get_fields())!=_pdf_value(after.get_fields()):
        raise EditError('El guardado no conserva los datos del formulario.')
    with fitz.open(stream=data,filetype='pdf') as a,fitz.open(stream=output,filetype='pdf') as b:
        if a.page_count!=b.page_count:raise EditError('El guardado cambió el número de páginas.')
        for number in range(a.page_count):
            if related(a[number])!=related(b[number]):raise EditError('El guardado alteró elementos del PDF.')
            assert_characters(trace_chars(a[number]),b[number]);assert_pixels(a[number],b[number])
    fd,name=tempfile.mkstemp(prefix='.pdfmodder-form-',suffix='.pdf',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(output);stream.flush();os.fsync(stream.fileno())
        os.replace(name,target)
    finally:
        if os.path.exists(name):os.unlink(name)
    return str(target)


def redact_regions_pdf(data,regions):
    reader=_guard(data)
    root=reader.trailer['/Root']
    if root.get('/StructTreeRoot'):raise EditError('Censura en PDF etiquetado: elimina las etiquetas de una copia antes; ActualText o etiquetas podrían conservar los datos.')
    if root.get('/OCProperties'):raise EditError('Censura: hay capas opcionales. Se necesita analizar sus contenidos ocultos antes de garantizar la eliminación.')
    if not regions or len(regions)>200:raise EditError('Selecciona entre 1 y 200 zonas para censurar.')
    grouped={}
    for region in regions:
        number=int(region['page']);rect=fitz.Rect(region['rect'])
        if not 0<=number<len(reader.pages) or rect.is_empty or not all(math.isfinite(v) for v in rect):raise EditError('Una zona de censura no es válida.')
        grouped.setdefault(number,[]).append(rect)
    expected={};removed=0;forbidden_images=set()
    with fitz.open(stream=data,filetype='pdf') as doc:
        # A single shared resource can legitimately occur outside the selected
        # zones. Only resources whose every visible occurrence is affected
        # must disappear completely from the rewritten object graph.
        occurrences={}
        for number in range(doc.page_count):
            for info in doc[number].get_image_info(xrefs=True):
                if info.get('xref'):
                    occurrences.setdefault(info['xref'],[]).append((number,fitz.Rect(info['bbox'])))
        from .media import _asset_fingerprint
        for xref,placements in occurrences.items():
            if all(any(r.intersects(box) for r in grouped.get(number,[])) for number,box in placements):
                forbidden_images.add(_asset_fingerprint(doc,xref))
        for number,rectangles in grouped.items():
            page=doc[number];bounds=fitz.Rect(0,0,page.cropbox.width,page.cropbox.height)
            if any(not bounds.contains(r) for r in rectangles):raise EditError('La zona de censura supera los límites de la página.')
            operations=ContentStream(reader.pages[number].get_contents(),reader).operations
            if any(op==b'BDC' and any(isinstance(value,dict) and ('/ActualText' in value or '/Alt' in value) for value in values) for values,op in operations):
                raise EditError('La zona contiene texto alternativo: se necesita analizarlo para no conservar datos ocultos.')
            if any(a.type[0]==fitz.PDF_ANNOT_REDACT for a in page.annots() or []):raise EditError('Hay marcas de censura anteriores sin aplicar; revísalas antes de esta operación.')
            if any(any(r.intersects(a.rect) for r in rectangles) for a in page.annots() or []):
                raise EditError('La zona toca una anotación que puede conservar datos; elimínala explícitamente antes de censurar.')
            # Removing a whole crossing vector would change content outside
            # the chosen rectangle; retaining it could expose outlined text.
            for drawing in page.get_drawings():
                box=fitz.Rect(drawing['rect'])
                if any(r.intersects(box) and not r.contains(box) for r in rectangles):
                    raise EditError('La zona corta un vector que se extiende fuera del recuadro. Amplía el recuadro para incluirlo completamente.')
            raw=[]
            for span in page.get_texttrace():
                for char in span['chars']:
                    hit=any(r.intersects(fitz.Rect(char[3])) for r in rectangles)
                    if hit:removed+=1
                    else:raw.append((chr(char[0]),tuple(char[2]),span['font'],float(span['size'])))
            expected[number]=raw
            from .media import _private_image_resources
            _private_image_resources(doc,page)
            for rect in rectangles:page.add_redact_annot(rect,fill=(0,0,0),cross_out=False)
            if not page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                                         graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                         text=fitz.PDF_REDACT_TEXT_REMOVE):raise EditError('No se pudo aplicar la censura.')
            page.clean_contents(sanitize=True)
        output=full_write(doc)
    check=PdfReader(BytesIO(output),strict=True)
    if '/Prev' in check.trailer:raise EditError('La salida conserva una revisión anterior; se cancela la exportación.')
    reports=[]
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        if before.page_count!=after.page_count or before.metadata!=after.metadata or before.get_xml_metadata()!=after.get_xml_metadata() or _canonical(before.get_toc(False))!=_canonical(after.get_toc(False)):
            raise EditError('La censura alteró páginas o metadatos ajenos a la operación.')
        for xref in range(1,after.xref_length()):
            if after.xref_get_key(xref,'Subtype')==('name','/Image') and after.xref_get_key(xref,'ColorSpace')[0]!='null':
                if _asset_fingerprint(after,xref) in forbidden_images:
                    raise EditError('Todavía existe el recurso original de una imagen censurada; se cancela la operación.')
        for number in range(before.page_count):
            a,b=before[number],after[number]
            if (tuple(a.cropbox),tuple(a.mediabox),a.rotation)!=(tuple(b.cropbox),tuple(b.mediabox),b.rotation):raise EditError('La censura alteró las dimensiones de página.')
            assert_characters(expected.get(number,trace_chars(a)),b)
            if number in grouped:
                expected_links=[link for link in a.get_links() if not any(r.intersects(fitz.Rect(link['from'])) for r in grouped[number])]
                if _canonical(expected_links)!=_canonical(b.get_links()):raise EditError('La censura alteró enlaces fuera de las zonas seleccionadas.')
                for span in b.get_texttrace():
                    if any(any(r.intersects(fitz.Rect(char[3])) for r in grouped[number]) for char in span['chars']):raise EditError('Aún quedan caracteres u OCR dentro de una zona censurada.')
                if _canonical([(x.type,tuple(x.rect),x.info) for x in a.annots() or []])!=_canonical([(x.type,tuple(x.rect),x.info) for x in b.annots() or []]):raise EditError('Se alteraron anotaciones ajenas a la censura.')
            elif related(a)!=related(b):raise EditError('Se alteraron elementos de una página no censurada.')
            reports.append(assert_pixels(a,b,[tuple(r) for r in grouped.get(number,[])]))
    return output,{'verified':True,'operation':'redaction','pages':reports,'characters_removed':removed,
                   'regions':[{'page':n,'rect':tuple(r)} for n,rows in grouped.items() for r in rows],
                   'full_write':True,'previous_revision_removed':True,'image_pixels_removed':True,
                   'notice':'Se censuran sólo las zonas elegidas. Revisa otras apariciones, adjuntos y metadatos antes de compartir la copia.'}


def install_session_tools_v200(cls):
    """Register methods without creating or sharing any live PDF across threads."""
    def form_fields_v200(self):
        self._require_editing()
        return form_fields_pdf(self.history.current)
    def form_only_save_v200(self):
        reports=[r for r in self.history.base_reports+self.history.reports[:self.history.index+1] if r]
        if not (bool(reports) and all(r.get('operation') in ('form_widget','document_metadata') for r in reports)
                and all(any(text in reason.lower() for text in ('campos de formulario','campo de firma digital','declara firmas digitales')) for reason in self.issues)):
            return False
        try:_guard(self.history.current,forms=True)
        except EditError:return False
        return True
    def preview_form_v200(self,page,xref,changes,revision=None):
        self._require_editing()
        if self.pending is not None:raise EditError('Aplica o cancela la previsualización anterior.')
        candidate,report=edit_form_field_pdf(self.history.current,page,xref,changes,revision)
        self._mark_page_edit(report,page)
        return self._put_preview(candidate,report)
    def save_form_v200(self,path):
        self._require_editing()
        if self.pending is not None:raise EditError('Aplica o cancela la previsualización antes de guardar.')
        self._safe_destination(path)
        output=atomic_save_form_pdf(self.history.current,path,self.path)
        self.saved_digest=hashlib.sha256(self.history.current).hexdigest()
        return {'path':output,'state':self.state()}
    def redaction_page_v200(self,page):
        self._require_editing()
        data=self.history.current
        with self._open(data) as doc:
            target=doc[page]
            zoom=min(1.5,1600/max(target.rect.width,target.rect.height))
            return {'page':page,'page_count':doc.page_count,'png':target.get_pixmap(matrix=fitz.Matrix(zoom,zoom),alpha=False).tobytes('png'),
                    'width':target.cropbox.width,'height':target.cropbox.height,'rotation':target.rotation,
                    'revision':hashlib.sha256(data).hexdigest()}
    def preview_redaction_v200(self,regions):
        self._writable()
        candidate,report=redact_regions_pdf(self.history.current,regions)
        return self._put_preview(candidate,report)
    for function in (form_fields_v200,form_only_save_v200,preview_form_v200,save_form_v200,redaction_page_v200,preview_redaction_v200):
        setattr(cls,function.__name__,function)
