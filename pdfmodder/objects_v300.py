"""Occurrence graph and lossless affine edits of native PDF objects.

An occurrence is an operator range, not a bounding-box guess. Nested edits
copy only the chain of Form invocations leading to that range. Original
streams, resource dictionaries, transparency groups, optional-content entries
and unknown keys remain intact. No Form is flattened and no artwork is
rasterised. The engine runs exclusively in the PDF worker process.
"""
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import copy
import math

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import (ContentStream, DictionaryObject, FloatObject,
                           IndirectObject, NameObject)

from .clipping import _serialize
from .model import EditError, intersects, union
from .validation import _canonical, assert_pixels


IDENTITY = (1., 0., 0., 1., 0., 0.)
PATH = {b'm', b'l', b'c', b'v', b'y', b'h', b're'}
PAINT = {b'S', b's', b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'n'}
SHOW = {b'Tj', b'TJ', b"'", b'"'}
STATE = {b'w', b'J', b'j', b'M', b'd', b'ri', b'i', b'gs', b'Tf', b'Tc',
         b'Tw', b'Tz', b'TL', b'Tr', b'Ts', b'CS', b'cs', b'SC', b'SCN',
         b'sc', b'scn', b'G', b'g', b'RG', b'rg', b'K', b'k'}
GRAPHICS_STATE = STATE - {b'Tf', b'Tc', b'Tw', b'Tz', b'TL', b'Tr', b'Ts'}
TEXT = SHOW | STATE | {b'BT', b'ET', b'Tm', b'Td', b'TD', b'T*', b'q', b'Q',
                       b'cm', b'BMC', b'BDC', b'EMC', b'MP', b'DP'}
MAX_OPS = 250_000
MAX_DEPTH = 32


def _dict(value):
    value = value.get_object() if hasattr(value, 'get_object') else value
    return value if isinstance(value, dict) else {}


def _copy_dictionary(value):
    value = _dict(value)
    return DictionaryObject({key: value.raw_get(key) if hasattr(value, 'raw_get') else item
                             for key, item in value.items()})


def _pdf(value):
    stream = BytesIO()
    value.write_to_stream(stream)
    return stream.getvalue().decode('latin1')


def _floats(values):
    return [FloatObject(v) for v in values]


def _matrix(values):
    values = tuple(float(v) for v in values)
    if len(values) != 6 or not all(math.isfinite(v) for v in values):
        raise EditError('El objeto contiene una matriz PDF no verificable.')
    return fitz.Matrix(*values)


def _invert(matrix):
    if abs(matrix.a*matrix.d-matrix.b*matrix.c) < 1e-10:
        raise EditError('El objeto tiene una transformación degenerada; no puede editarse.')
    return ~matrix


def _points_box(points):
    if not points:
        return None
    if not all(math.isfinite(v) for p in points for v in p):
        raise EditError('El objeto contiene geometría no finita.')
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _box(matrix, rect):
    x0, y0, x1, y1 = [float(v) for v in rect]
    return _points_box([fitz.Point(x,y)*matrix for x,y in
                        ((x0,y0),(x0,y1),(x1,y0),(x1,y1))])


def _reference(raw):
    return getattr(raw, 'idnum', None)


def _identifier(owner, start, kind):
    return ':'.join((kind, '/'.join(str(v) for v in (*owner,start))))


@dataclass
class _Node:
    kind: str
    owner: tuple
    start: int
    end: int
    matrix: tuple
    rect: tuple | None = None
    resource: str | None = None
    xref: int | None = None
    parent: str | None = None
    label: str = ''
    children: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    clips: list = field(default_factory=list)
    properties: dict = field(default_factory=dict)
    reason: str = ''
    marked: bool = False

    @property
    def id(self):
        return _identifier(self.owner,self.start,self.kind)


class _Graph:
    def __init__(self,data,page):
        self.data,self.number=data,page
        self.reader=PdfReader(BytesIO(data),strict=True)
        if isinstance(page,bool) or not isinstance(page,int) or not 0<=page<len(self.reader.pages):
            raise EditError('La página seleccionada no existe.')
        self.page=self.reader.pages[page]
        self.resources=_dict(self.page.get('/Resources',{}))
        self.nodes=[];self.by_id={};self.text_owners={};self.glyph_owners={};self.op_count=0
        self.typography_context=None;self.has_typography=False
        self.tagged=bool(self.reader.trailer['/Root'].get('/StructTreeRoot'))
        with fitz.open(stream=data,filetype='pdf') as doc:
            p=doc[page];rotation=p.rotation;p.set_rotation(0)
            self.root_matrix=tuple(p.transformation_matrix)
            self.page_bounds=(0.,0.,float(p.cropbox.width),float(p.cropbox.height))
            self.has_typography=doc.xref_get_key(p.xref,'PDFModderTypography')[0]=='string'
            self.related_regions=_related_regions(p)
            p.set_rotation(rotation)
        operations=ContentStream(self.page.get_contents(),self.reader).operations
        self.walk(operations,self.resources,(),_matrix(self.root_matrix),None,(),(),())
        self._text_bounds()
        # Groups include all descendant paint bounds, including nested Forms.
        for node in reversed(self.nodes):
            if node.kind=='group':
                rects=[self.by_id[c].rect for c in node.children if self.by_id[c].rect]
                node.rect=union(rects) if rects else None
        counts=Counter(n.xref for n in self.nodes if n.xref is not None)
        for node in self.nodes:
            node.properties['occurrences_on_page']=counts[node.xref] if node.xref else 1

    def add(self,node):
        self.nodes.append(node);self.by_id[node.id]=node
        if node.parent in self.by_id:
            self.by_id[node.parent].children.append(node.id)
        return node

    def walk(self,ops,resources,owner,ctm,parent,ancestors,clips,layers,graphics=(1.,10.,0)):
        if len(owner)>MAX_DEPTH:
            raise EditError('El PDF supera 32 niveles de objetos anidados.')
        stack=[];scopes=[];marks=[];points=[];path_start=None;path_matrix=None
        path_clean=True;path_clip=False;text_start=None;text_matrix=None;text_reason=''
        linewidth,miter,render_mode=graphics
        clip_list=list(clips);layer_list=list(layers)
        for i,(args,op) in enumerate(ops):
            self.op_count+=1
            if self.op_count>MAX_OPS:
                raise EditError('La página supera 250.000 operadores; divide el trabajo por páginas.')
            effective_parent=scopes[-1][0].id if scopes else parent
            if text_start is not None and op not in TEXT:
                text_reason='El bloque mezcla texto con operadores que requieren otra ruta de edición.'
            if op==b'q':
                stack.append((fitz.Matrix(ctm),linewidth,miter,render_mode,list(clip_list)))
                if text_start is None:
                    node=self.add(_Node('group',owner,i,i,tuple(ctm),parent=effective_parent,
                        label='Grupo gráfico',layers=list(layer_list),clips=list(clip_list),marked=bool(marks)))
                    scopes.append((node,bool(points)))
            elif op==b'Q':
                if not stack:
                    raise EditError('La página contiene un estado gráfico Q sin apertura q.')
                ctm,linewidth,miter,render_mode,clip_list=stack.pop()
                if text_start is None:
                    if not scopes:
                        raise EditError('El grupo gráfico cruza un bloque de texto.')
                    node,was_path=scopes.pop();node.end=i
                    if was_path or points:
                        node.reason='El trazado atraviesa el límite del grupo; conserva su ruta original.'
            elif op==b'cm':
                ctm=_matrix(args)*ctm
                if path_start is not None:path_clean=False
            elif op==b'w':linewidth=float(args[0])
            elif op==b'M':miter=float(args[0])
            elif op==b'Tr':render_mode=int(args[0])
            elif op==b'gs':
                state=_dict(_dict(resources.get('/ExtGState',{})).get(args[0]))
                if '/LW' in state:linewidth=float(state['/LW'])
                if '/ML' in state:miter=float(state['/ML'])
            elif op in (b'BMC',b'BDC'):
                marks.append(len(layer_list))
                if args and str(args[0])=='/OC':
                    value=args[1] if len(args)>1 else None
                    if isinstance(value,NameObject):value=_dict(resources.get('/Properties',{})).get(value)
                    value=_dict(value)
                    layer_list.append(str(value.get('/Name',args[-1] if args else 'Capa')))
            elif op==b'EMC':
                if not marks:raise EditError('El PDF contiene contenido marcado sin apertura.')
                layer_list=layer_list[:marks.pop()]
            elif op==b'BT':
                if text_start is not None:raise EditError('El PDF contiene bloques BT anidados.')
                text_start=i;text_matrix=tuple(ctm);text_reason=''
            elif op==b'ET':
                if text_start is None:raise EditError('El PDF contiene ET sin apertura BT.')
                node=self.add(_Node('text',owner,text_start,i,text_matrix,parent=effective_parent,
                    label='Bloque de texto',layers=list(layer_list),clips=list(clip_list),
                    reason=text_reason,marked=bool(marks)))
                for index in range(text_start,i+1):
                    if ops[index][1] in SHOW:self.text_owners[(owner,index)]=node.id
                text_start=None
            elif op in SHOW and render_mode>=4:
                text_reason='El texto define un recorte para contenido posterior; edita el grupo gráfico que lo contiene.'
            elif op in PATH:
                if path_start is None:path_start=i;path_matrix=tuple(ctm);path_clean=True
                if op==b're':
                    x,y,w,h=[float(v) for v in args]
                    points.extend(fitz.Point(a,b)*ctm for a,b in ((x,y),(x+w,y),(x,y+h),(x+w,y+h)))
                elif op!=b'h':
                    points.extend(fitz.Point(float(args[j]),float(args[j+1]))*ctm for j in range(0,len(args),2))
            elif op in (b'W',b'W*'):
                path_clip=True
            elif op in PAINT:
                bounds=_points_box(points)
                if path_clip:
                    if bounds:clip_list.append(bounds)
                if path_start is not None and op!=b'n':
                    stroke=op in (b'S',b's',b'B',b'B*',b'b',b'b*')
                    if bounds and stroke:
                        # A conservative miter envelope also covers square caps.
                        scale=max(math.hypot(ctm.a,ctm.b),math.hypot(ctm.c,ctm.d))
                        margin=abs(linewidth)*scale*max(1.,abs(miter))*.5+.25
                        bounds=(bounds[0]-margin,bounds[1]-margin,bounds[2]+margin,bounds[3]+margin)
                    reason=('El trazado establece un recorte para contenido posterior.' if path_clip else
                            'El trazado mezcla estados o transformaciones durante su construcción.' if not path_clean else '')
                    self.add(_Node('vector',owner,path_start,i,path_matrix,rect=bounds,
                        parent=effective_parent,label='Trazado vectorial',layers=list(layer_list),
                        clips=list(clip_list),reason=reason,marked=bool(marks),
                        properties={'stroke':stroke,'fill':op not in (b'S',b's'),
                                    'line_width':linewidth,'miter_limit':miter}))
                points=[];path_start=None;path_clip=False;path_clean=True
            elif op==b'Do':
                raw=_dict(resources.get('/XObject',{})).get(args[0])
                raw_ref=_dict(resources.get('/XObject',{}))
                raw_ref=raw_ref.raw_get(args[0]) if hasattr(raw_ref,'raw_get') and args[0] in raw_ref else raw
                obj=_dict(raw);subtype=str(obj.get('/Subtype',''))
                kind='form' if subtype=='/Form' else 'image' if subtype=='/Image' else 'unknown'
                local=_matrix(obj.get('/Matrix',IDENTITY))*ctm if kind=='form' else ctm
                bounds=obj.get('/BBox') if kind=='form' else (0.,0.,1.,1.) if kind=='image' else None
                rect=_box(local,bounds) if bounds and len(bounds)==4 else None
                layers_for_node=list(layer_list)
                if obj.get('/OC'):
                    layers_for_node.append(str(_dict(obj.get('/OC')).get('/Name','Capa del objeto')))
                node=self.add(_Node(kind,owner,i,i,tuple(ctm),rect=rect,resource=str(args[0]),
                    xref=_reference(raw_ref),parent=effective_parent,label=('Instancia Form' if kind=='form' else 'Imagen' if kind=='image' else 'Objeto PDF'),
                    layers=layers_for_node,clips=list(clip_list),marked=bool(marks),
                    properties={'transparency_group':bool(obj.get('/Group')),
                                'optional_content':bool(obj.get('/OC')),
                                'form_matrix':list(obj.get('/Matrix',IDENTITY)) if kind=='form' else None,
                                'bbox':list(bounds) if bounds else None,
                                'unknown_keys':[str(k) for k in obj if str(k) not in
                                    ('/Type','/Subtype','/BBox','/Matrix','/Resources','/Length','/Filter','/DecodeParms','/Group','/OC','/Width','/Height','/BitsPerComponent','/ColorSpace','/SMask','/Mask')]}))
                if kind=='form':
                    identity=_reference(raw_ref) or id(obj)
                    if identity in ancestors:
                        node.reason='El Form contiene una referencia recursiva.'
                        continue
                    if not bounds or len(bounds)!=4:
                        node.reason='El Form no declara un límite verificable.';continue
                    form_clips=tuple(clip_list)+(rect,)
                    self.walk(ContentStream(obj,self.reader).operations,_dict(obj.get('/Resources',resources)),
                              owner+(i,),local,node.id,ancestors+(identity,),form_clips,tuple(layers_for_node),
                              (linewidth,miter,render_mode))
            elif op==b'sh':
                self.add(_Node('shading',owner,i,i,tuple(ctm),rect=self.page_bounds,
                    parent=effective_parent,label='Sombreado PDF',resource=str(args[0]),
                    clips=list(clip_list),layers=list(layer_list),marked=bool(marks)))
            elif op==b'INLINE IMAGE':
                self.add(_Node('inline_image',owner,i,i,tuple(ctm),rect=_box(ctm,(0,0,1,1)),
                    parent=effective_parent,label='Imagen en línea',layers=list(layer_list),clips=list(clip_list),marked=bool(marks)))
            # Stroke/colour operators can legally occur after a path was
            # constructed. They do not change its points and must be retained
            # (and replayed after an isolated edit) for subsequent artwork.
            if path_start is not None and op not in PATH|PAINT|GRAPHICS_STATE|{b'W',b'W*'}:
                path_clean=False
        if stack or scopes or text_start is not None or marks:
            raise EditError('El contenido PDF contiene grupos, texto o marcas sin cerrar.')
        # An unpainted final path has no artwork to expose in the inventory;
        # leave its operators intact instead of blocking unrelated occurrences.

    def _text_bounds(self):
        if not self.text_owners:return
        markers={key:i+1 for i,key in enumerate(self.text_owners)}
        if len(markers)>=0xffffff:raise EditError('Demasiadas operaciones de texto para identificar sus objetos.')
        def colour(ops,resources,owner):
            result=[]
            for i,(args,op) in enumerate(ops):
                marker=markers.get((owner,i))
                if marker:
                    rgb=_floats(((marker>>16&255)/255,(marker>>8&255)/255,(marker&255)/255))
                    result.extend([(rgb,b'rg'),(rgb,b'RG')])
                result.append((copy.copy(args),op))
            return result,resources
        probe=_rewrite_tree(self.data,self.number,colour)
        with fitz.open(stream=self.data,filetype='pdf') as before,fitz.open(stream=probe,filetype='pdf') as after:
            original=[(c[0],tuple(c[2])) for span in before[self.number].get_texttrace() for c in span['chars']]
            spans=after[self.number].get_texttrace()
            actual=[(c[0],tuple(c[2])) for span in spans for c in span['chars']]
            if len(original)!=len(actual) or any(a[0]!=b[0] or max(abs(x-y) for x,y in zip(a[1],b[1]))>.025 for a,b in zip(original,actual)):
                for node in self.nodes:
                    if node.kind=='text':node.reason='No se pudo vincular el texto a sus operadores conservando la geometría.'
                return
            inverse={marker:self.text_owners[key] for key,marker in markers.items()}
            bounds={};texts={}
            for span in spans:
                colour=span.get('color',())
                if len(colour)!=3:continue
                values=[round(float(v)*255) for v in colour]
                marker=(values[0]<<16)|(values[1]<<8)|values[2]
                node_id=inverse.get(marker)
                if not node_id:continue
                bounds.setdefault(node_id,[]).extend(tuple(c[3]) for c in span['chars'])
                texts.setdefault(node_id,[]).extend(chr(c[0]) for c in span['chars'])
            index=0
            for span in spans:
                colour=span.get('color',())
                values=[round(float(v)*255) for v in colour] if len(colour)==3 else []
                marker=((values[0]<<16)|(values[1]<<8)|values[2]) if values else None
                node_id=inverse.get(marker)
                for character in span['chars']:
                    if node_id:self.glyph_owners[index]=node_id
                    index+=1
            for node in self.nodes:
                if node.kind!='text':continue
                node.rect=union(bounds[node.id]) if bounds.get(node.id) else None
                text=''.join(texts.get(node.id,[]))
                node.label=('Texto · '+text[:100]) if text else 'Bloque de texto sin geometría visible'
                node.properties['text']=text
                if node.rect is None:node.reason=node.reason or 'El texto no ofrece geometría verificable para esta operación.'

    def owned_glyph_ids(self,node):
        """Paint IDs come from the verified operator probe, never box overlap."""
        descendants={node.id};pending=list(node.children)
        while pending:
            identity=pending.pop();descendants.add(identity)
            pending.extend(self.by_id[identity].children)
        return [index for index,identity in self.glyph_owners.items() if identity in descendants]


def _save_document(doc):
    # Retain original objects, including vendor extensions. This operation does
    # not remove information: it transforms or copies existing native artwork.
    return doc.tobytes(garbage=0,deflate=False,incremental=False,no_new_id=True)


class _Writer:
    def __init__(self,data,page):
        self.reader=PdfReader(BytesIO(data),strict=True)
        self.doc=fitz.open(stream=data,filetype='pdf');self.page=page;self.counter=0
        self.cloned=[]

    def close(self):self.doc.close()

    def resource(self,resources,category,reference,prefix='/PMO300'):
        resources=_copy_dictionary(resources)
        category_dict=_copy_dictionary(resources.get(category,{}))
        while True:
            self.counter+=1;name=NameObject(prefix+str(self.counter))
            if name not in category_dict:break
        category_dict[name]=IndirectObject(reference,0,self.reader)
        resources[NameObject(category)]=category_dict
        return resources,name

    def put_resources(self,resources):
        ref=self.doc.get_new_xref();self.doc.update_object(ref,_pdf(_copy_dictionary(resources)))
        return ref

    def clone_form(self,form,ops,resources):
        source=getattr(getattr(form,'indirect_reference',None),'idnum',None)
        reference=self.doc.get_new_xref()
        value=_copy_dictionary(form)
        # update_stream installs a correct Length and preserves all other keys.
        for key in ('/Length','/Filter','/DecodeParms'):
            value.pop(NameObject(key),None)
        self.doc.update_object(reference,_pdf(value))
        resource=self.put_resources(resources)
        self.doc.xref_set_key(reference,'Resources',f'{resource} 0 R')
        self.doc.update_stream(reference,_serialize(ops),compress=False)
        self.cloned.append({'source':source,'copy':reference})
        return reference

    def finish(self,ops,resources):
        stream=self.doc.get_new_xref();self.doc.update_object(stream,'<< >>')
        self.doc.update_stream(stream,_serialize(ops),compress=False)
        page=self.doc[self.page]
        self.doc.xref_set_key(page.xref,'Contents',f'{stream} 0 R')
        self.doc.xref_set_key(page.xref,'Resources',f'{self.put_resources(resources)} 0 R')
        return _save_document(self.doc)


def _rewrite_tree(data,page,callback):
    """Disposable probe: copy every invocation, preserving each Form dictionary."""
    writer=_Writer(data,page)
    count=0
    def walk(ops,resources,owner=(),ancestors=()):
        nonlocal count
        if len(owner)>MAX_DEPTH:raise EditError('El Form supera el límite de anidación.')
        result=[];resources=_copy_dictionary(resources)
        for i,(args,op) in enumerate(ops):
            count+=1
            if count>MAX_OPS:raise EditError('La página supera el límite de operadores.')
            args=copy.copy(args)
            if op==b'Do':
                form=_dict(_dict(resources.get('/XObject',{})).get(args[0]))
                if form.get('/Subtype')=='/Form':
                    identity=getattr(getattr(form,'indirect_reference',None),'idnum',id(form))
                    if identity not in ancestors:
                        nested=_dict(form.get('/Resources',resources))
                        child_ops=ContentStream(form,writer.reader).operations
                        child_ops,child_res=walk(child_ops,nested,owner+(i,),ancestors+(identity,))
                        reference=writer.clone_form(form,child_ops,child_res)
                        resources,name=writer.resource(resources,'/XObject',reference)
                        args[0]=name
            result.append((args,op))
        return callback(result,resources,owner)
    try:
        p=writer.reader.pages[page]
        ops,res=walk(ContentStream(p.get_contents(),writer.reader).operations,_dict(p.get('/Resources',{})))
        return writer.finish(ops,res)
    finally:writer.close()


def _mutate(data,page,node,callback):
    writer=_Writer(data,page)
    def walk(ops,resources,depth=0):
        resources=_copy_dictionary(resources)
        if depth==len(node.owner):return callback(ops,resources,writer)
        index=node.owner[depth]
        args,op=ops[index]
        if op!=b'Do':raise EditError('La ruta del objeto cambió. Abre de nuevo el panel.')
        form=_dict(_dict(resources.get('/XObject',{})).get(args[0]))
        if form.get('/Subtype')!='/Form':raise EditError('La instancia PDF ya no existe.')
        if form.get('/StructParent') is not None or form.get('/StructParents') is not None:
            raise EditError('Esta instancia tiene relaciones de accesibilidad que requieren remapear etiquetas antes de editar su interior.')
        child_ops=ContentStream(form,writer.reader).operations
        child_ops,child_res=walk(child_ops,_dict(form.get('/Resources',resources)),depth+1)
        reference=writer.clone_form(form,child_ops,child_res)
        resources,name=writer.resource(resources,'/XObject',reference)
        ops=list(ops);args=copy.copy(args);args[0]=name;ops[index]=(args,op)
        return ops,resources
    try:
        p=writer.reader.pages[page]
        ops,res=walk(ContentStream(p.get_contents(),writer.reader).operations,_dict(p.get('/Resources',{})))
        output=writer.finish(ops,res)
        return output,writer.cloned
    finally:writer.close()


def _guard(data,page,revision=None):
    if revision and sha256(data).hexdigest()!=revision:
        raise EditError('El documento cambió. Abre de nuevo el panel de objetos.')
    with fitz.open(stream=data,filetype='pdf') as doc:
        if doc.is_encrypted or doc.needs_pass:
            raise EditError('El documento cifrado requiere una ruta de edición autorizada.')
        if not doc.permissions&fitz.PDF_PERM_MODIFY:
            raise EditError('El documento no permite modificar su contenido.')
        if doc.get_sigflags()>0:
            raise EditError('El documento declara firmas digitales; esta operación afectaría a su validación.')
        if isinstance(page,bool) or not isinstance(page,int) or not 0<=page<len(doc):
            raise EditError('La página seleccionada no existe.')
        if any(a.type[0]==fitz.PDF_ANNOT_REDACT for a in doc[page].annots() or []):
            raise EditError('La página contiene redacciones pendientes.')
    reader=PdfReader(BytesIO(data),strict=True);root=reader.trailer['/Root']
    if root.get('/Perms'):
        raise EditError('El documento está firmado o certificado.')
    form=_dict(root.get('/AcroForm'))
    if form.get('/XFA'):
        raise EditError('El formulario XFA necesita un editor que preserve sus datos y apariencias.')
    if any(f.get('/FT')=='/Sig' for f in (reader.get_fields() or {}).values()):
        raise EditError('El documento contiene campos de firma digital.')


def _capabilities(graph,node):
    reason=node.reason
    if node.rect is None:reason=reason or 'No existe un límite geométrico verificable.'
    if node.kind=='unknown':reason=reason or 'El subtipo PDF no admite todavía una edición verificable.'
    try:_invert(_matrix(node.matrix))
    except EditError as exc:reason=reason or str(exc)
    if graph.tagged and node.owner:
        reason=reason or 'La edición del interior de un Form etiquetado necesita remapear sus relaciones de accesibilidad.'
    usable=not bool(reason)
    obstacles=[label for rect,label in graph.related_regions if node.rect and intersects(node.rect,rect)]
    transform_reason=('El objeto toca '+obstacles[0]+'; sus áreas activas necesitan una edición conjunta explícita.' if obstacles else '')
    typography_reason='';duplicate_typography_reason=''
    glyph_ids=graph.owned_glyph_ids(node)
    if graph.has_typography and glyph_ids:
        from .typography_objects_v300 import prepare_typography_object_context,native_object_record_issue
        if graph.typography_context is None:
            graph.typography_context=prepare_typography_object_context(graph.data,graph.number)
        typography_reason=native_object_record_issue(graph.data,graph.number,glyph_ids,context=graph.typography_context)
        duplicate_typography_reason=native_object_record_issue(graph.data,graph.number,glyph_ids,True,context=graph.typography_context)
        transform_reason=transform_reason or typography_reason
    transforms=usable and not transform_reason
    return {'move':transforms,'scale':transforms,'rotate':transforms,
            'duplicate':transforms and not(graph.tagged or node.marked or duplicate_typography_reason),
            'opacity':usable and (node.kind in ('vector','image','inline_image','text') or
                         node.kind=='form' and node.properties.get('transparency_group')),
            'fill_color':usable and node.kind in ('vector','text'),
            'stroke_color':usable and node.kind=='vector',
            'line_width':usable and node.kind=='vector',
            'reason':reason,'transform_reason':transform_reason,
            'duplicate_reason':(transform_reason or duplicate_typography_reason or ('El duplicado necesita asignar nuevas etiquetas.' if graph.tagged or node.marked else ''))}


def object_graph(data,page):
    """Serializable inventory of real paint occurrences, including nested paths."""
    graph=_Graph(data,page)
    rows=[];document_reason=''
    try:_guard(data,page)
    except EditError as exc:document_reason=str(exc)
    for node in graph.nodes:
        if node.kind=='group' and not node.children:continue
        capabilities=_capabilities(graph,node)
        if document_reason:
            capabilities.update({key:False for key in ('move','scale','rotate','duplicate',
                'opacity','fill_color','stroke_color','line_width')})
            capabilities['reason']=document_reason
        rows.append({'id':node.id,'kind':node.kind,'label':node.label,'parent':node.parent,
            'children':node.children,'rect':list(node.rect) if node.rect else None,
            'matrix':list(node.matrix),'path':list(node.owner),'range':[node.start,node.end],
            'resource':node.resource,'xref':node.xref,'layers':node.layers,'clips':node.clips,
            'properties':node.properties,'capabilities':capabilities})
    return {'page':page,'revision':sha256(data).hexdigest(),'items':rows,
            'page_bounds':list(graph.page_bounds),'tagged':graph.tagged,
            'native_objects':True,'form_semantics_preserved':True,'document_reason':document_reason}


def _finite(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise EditError(label+' debe ser un número finito.')
    return float(value)


def _transform(node,operation,dx,dy,scale_x,scale_y,angle,anchor):
    dx=_finite(dx,'El desplazamiento X');dy=_finite(dy,'El desplazamiento Y')
    sx=_finite(scale_x,'La escala X');sy=_finite(scale_y,'La escala Y')
    angle=_finite(angle,'El giro')
    if anchor is None:
        r=node.rect;anchor=((r[0]+r[2])/2,(r[1]+r[3])/2)
    if len(anchor)!=2:raise EditError('El centro de transformación debe tener dos coordenadas.')
    x,y=[_finite(v,'El centro de transformación') for v in anchor]
    if operation=='move' or operation=='duplicate':return fitz.Matrix(1,0,0,1,dx,dy)
    if operation=='scale':
        if abs(sx)<1e-4 or abs(sy)<1e-4 or abs(sx)>1000 or abs(sy)>1000:
            raise EditError('Las escalas deben tener magnitud entre 0,0001 y 1000.')
        linear=fitz.Matrix(sx,0,0,sy,0,0)
    elif operation=='rotate':linear=fitz.Matrix(angle)
    elif operation=='properties':return fitz.Matrix(*IDENTITY)
    else:raise EditError('Operación de objeto desconocida.')
    return fitz.Matrix(1,0,0,1,-x,-y)*linear*fitz.Matrix(1,0,0,1,x+dx,y+dy)


def _properties(node,properties,capabilities):
    if not isinstance(properties,dict):raise EditError('Las propiedades del objeto deben ser un diccionario.')
    allowed={'opacity','fill_color','stroke_color','line_width'}
    if set(properties)-allowed:raise EditError('Hay propiedades PDF que todavía no admiten una modificación verificable.')
    values={}
    for key,value in properties.items():
        if not capabilities.get(key):raise EditError('Esta propiedad no es aplicable al objeto seleccionado: '+key+'.')
        if key in ('fill_color','stroke_color'):
            if not isinstance(value,(tuple,list)) or len(value)!=3:
                raise EditError('El color debe contener tres componentes RGB.')
            value=[_finite(v,'El componente RGB') for v in value]
            if any(v<0 or v>1 for v in value):raise EditError('Los componentes RGB deben estar entre 0 y 1.')
        else:
            value=_finite(value,'La propiedad')
            if key=='opacity' and not 0<=value<=1:raise EditError('La opacidad debe estar entre 0 y 1.')
            if key=='line_width' and not 0<=value<=1000:raise EditError('El grosor debe estar entre 0 y 1000 puntos.')
        values[key]=value
    return values


def _related_regions(page):
    regions=[(tuple(link['from']),'un enlace') for link in page.get_links()]
    regions.extend((tuple(a.rect),'una anotación') for a in page.annots() or [])
    regions.extend((tuple(w.rect),'un campo de formulario') for w in page.widgets() or [])
    return regions


def _relation_guard(data,page,node,transform):
    if tuple(transform)==IDENTITY:return
    r=node.rect
    with fitz.open(stream=data,filetype='pdf') as doc:
        regions=_related_regions(doc[page])
    destination=_box(transform,r)
    for rect,label in regions:
        if intersects(r,rect) or intersects(destination,rect):
            raise EditError('La transformación toca '+label+'; sus áreas activas necesitan una edición conjunta explícita.')


def _validate(data,output,page,regions,typography_updated=False):
    from .validation import assert_form_preservation
    assert_form_preservation(data,output)
    # All pre-existing indirect objects except the selected page dictionary
    # must stay byte-semantically intact. Shared Forms/resources are never changed.
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        if before.page_count!=after.page_count:raise EditError('La operación cambió el número de páginas.')
        page_count=before.page_count
        allowed=before[page].xref
        for xref in range(1,before.xref_length()):
            if xref==allowed:continue
            if before.xref_object(xref)!=after.xref_object(xref):
                raise EditError('La operación alteró un recurso original compartido; transacción cancelada.')
            if before.xref_is_stream(xref) and before.xref_stream(xref)!=after.xref_stream(xref):
                raise EditError('La operación alteró un flujo original compartido; transacción cancelada.')
        if before.metadata!=after.metadata or before.get_xml_metadata()!=after.get_xml_metadata():
            raise EditError('La operación alteró los metadatos del documento.')
        # Other pages and every referenced original resource were proved
        # identical above. Avoid extracting annotations from all 1,000 pages
        # when only one page dictionary acquired a new content stream.
        a,b=before[page],after[page]
        if (tuple(a.mediabox),tuple(a.cropbox),a.rotation)!=(tuple(b.mediabox),tuple(b.cropbox),b.rotation):
            raise EditError('La operación alteró los límites de una página.')
        rel=lambda p:_canonical({'links':p.get_links(),
            'annots':[(a.type,tuple(a.rect),a.info,a.colors,a.opacity,a.flags) for a in p.annots() or []],
            'widgets':[(w.field_name,w.field_value,w.field_type,tuple(w.rect)) for w in p.widgets() or []]})
        if rel(a)!=rel(b):raise EditError('La operación alteró enlaces, anotaciones o campos.')
        pixels=assert_pixels(before[page],after[page],regions)
    independent=PdfReader(BytesIO(output),strict=True)
    if len(independent.pages)!=page_count:
        raise EditError('El lector independiente no confirma la estructura del resultado.')
    original=PdfReader(BytesIO(data),strict=True)
    def unchanged_page_values(value):
        return {str(key):_pdf(value.raw_get(key)) for key in value
                if key not in ('/Contents','/Resources') and not(typography_updated and key=='/PDFModderTypography')}
    if unchanged_page_values(original.pages[page])!=unchanged_page_values(independent.pages[page]):
        raise EditError('La operación alteró propiedades de la página ajenas a sus objetos.')
    return {'verified':True,'independent_parser':'pypdf','pixels':pixels,
            'original_objects_unchanged':True,'relations_preserved':True}


def edit_object_pdf(data,page,object_id,operation,*,revision=None,dx=0.,dy=0.,
                    scale_x=1.,scale_y=1.,angle=0.,anchor=None,properties=None):
    """Produce an isolated, validated candidate; no partial edit is returned."""
    _guard(data,page,revision)
    graph=_Graph(data,page);node=graph.by_id.get(object_id)
    if node is None:raise EditError('El objeto ya no existe. Abre de nuevo el panel.')
    caps=_capabilities(graph,node)
    if operation not in ('move','scale','rotate','duplicate','properties'):
        raise EditError('Operación de objeto desconocida.')
    if operation!='properties' and not caps.get(operation):
        raise EditError(caps.get('reason') or caps.get('transform_reason') or caps.get('duplicate_reason') or 'Esta operación requiere otra ruta de edición.')
    if operation=='properties' and caps['reason']:raise EditError(caps['reason'])
    values=_properties(node,properties or {},caps)
    if operation=='properties' and not values:raise EditError('Elige al menos una propiedad para modificar.')
    transform=_transform(node,operation,dx,dy,scale_x,scale_y,angle,anchor)
    _relation_guard(data,page,node,transform)
    local=_matrix(node.matrix)*transform*_invert(_matrix(node.matrix))
    def modify(ops,resources,writer):
        segment=copy.deepcopy(ops[node.start:node.end+1])
        setters=[];ext_name=None
        if 'opacity' in values:
            gs=DictionaryObject({NameObject('/Type'):NameObject('/ExtGState'),
                                 NameObject('/ca'):FloatObject(values['opacity']),
                                 NameObject('/CA'):FloatObject(values['opacity'])})
            ref=writer.doc.get_new_xref();writer.doc.update_object(ref,_pdf(gs))
            resources,ext_name=writer.resource(resources,'/ExtGState',ref)
            setters.append(([ext_name],b'gs'))
        if 'fill_color' in values:setters.append((_floats(values['fill_color']),b'rg'))
        if 'stroke_color' in values:setters.append((_floats(values['stroke_color']),b'RG'))
        if 'line_width' in values:setters.append((_floats([values['line_width']]),b'w'))
        if node.kind=='text':
            # Apply paint properties at every SHOW so an internal colour/gs
            # cannot silently override the requested property. q/Q preserves
            # text parameters, but PDF text matrices intentionally advance.
            altered=[]
            for args,op in segment:
                if op in SHOW and setters:
                    altered.extend([([],b'q'),*setters,(args,op),([],b'Q')])
                    if op==b'"':altered.extend([([args[0]],b'Tw'),([args[1]],b'Tc')])
                else:altered.append((args,op))
            segment=altered
            # A complete BT/ET can update persistent graphics/text parameters.
            # Replay only those state operators after the wrapper has restored
            # CTM, ensuring following content sees its original final state.
            replay=[(copy.deepcopy(args),op) for args,op in ops[node.start:node.end+1]
                    if op in STATE or op in (b'q',b'Q',b'cm')]
            for args,op in ops[node.start:node.end+1]:
                if op==b'"':replay.extend([([args[0]],b'Tw'),([args[1]],b'Tc')])
                if op==b'TD':replay.append(([FloatObject(-float(args[1]))],b'TL'))
        elif node.kind=='vector':
            altered=[]
            for args,op in segment:
                # A path may set its own colour/line width after its first
                # point. Set requested properties at the actual paint operator.
                if op in PAINT:altered.extend(setters)
                altered.append((args,op))
            segment=altered
            replay=[(copy.deepcopy(args),op) for args,op in ops[node.start:node.end+1]
                    if op in GRAPHICS_STATE]
        else:replay=[]
        replacement=[([],b'q'),(_floats(tuple(local)),b'cm')]
        if node.kind not in ('text','vector'):replacement.extend(setters)
        replacement.extend(segment);replacement.append(([],b'Q'));replacement.extend(replay)
        if operation=='duplicate':
            # Keep the original paint item, placing the new occurrence beside
            # it in the same paint position and marked-content/layer context.
            replacement=ops[node.start:node.end+1]+replacement
        return ops[:node.start]+replacement+ops[node.end+1:],resources
    output,clones=_mutate(data,page,node,modify)
    typography={'updated_records':0,'cloned_records':0,'verified':True}
    if graph.has_typography:
        from .typography_objects_v300 import update_native_object_records_v300
        output,typography=update_native_object_records_v300(data,output,page,
            graph.owned_glyph_ids(node),tuple(transform),operation=='duplicate',graph.typography_context)
    destination=_box(transform,node.rect)
    regions=[node.rect,destination]
    if 'line_width' in values:
        matrix=_matrix(node.matrix)
        margin=values['line_width']*max(math.hypot(matrix.a,matrix.b),math.hypot(matrix.c,matrix.d))*max(1,node.properties.get('miter_limit',10))/2
        r=destination;regions.append((r[0]-margin,r[1]-margin,r[2]+margin,r[3]+margin))
    validation=_validate(data,output,page,regions,typography_updated=bool(typography['updated_records']))
    report={'operation':'native_object_v300','object_operation':operation,'page':page,
            'object_id':object_id,'kind':node.kind,'source_regions':[node.rect],
            'destination_regions':[destination],'matrix':tuple(transform),'properties':values,
            'isolated_form_chain':clones,'shared_objects_unchanged':True,
            'form_groups_preserved':True,'optional_content_preserved':True,
            'clips_preserved':True,'vectors_retained':True,'paint_order_retained':True,
            'validation':validation,'verified':True}
    report['typography']=typography
    return output,report


def install_object_tools_v300(Session):
    """Register serializable worker operations without changing existing routes."""
    def object_graph_v300(self,page):
        self._require_editing()
        return object_graph(self.history.current,page)
    def object_edit_v300(self,page,object_id,operation,**kwargs):
        self._require_editing()
        if self.pending is not None:raise EditError('Acepta o cancela la vista previa anterior.')
        candidate,report=edit_object_pdf(self.history.current,page,object_id,operation,**kwargs)
        self._mark_page_edit(report,page)
        return self._put_preview(candidate,report)
    for function in (object_graph_v300,object_edit_v300):setattr(Session,function.__name__,function)


# Short alias used by optional worker integrations.
install=install_object_tools_v300
