"""Joint edits of one proven original underline and its logical text owner.

The original rectangle stays in its own marked-content scope. It is never
adopted as a per-character decoration in the editor's private metadata.
"""
from collections import Counter
from io import BytesIO
import copy
import hashlib
import math

import pymupdf as fitz
from pypdf.generic import ArrayObject, FloatObject, NameObject

from .model import EditError, intersects, union

_TOKEN = object()
_CONTAINERS = {'/P', '/LBody', '/TD', '/TH', '/Caption'}
_ARTIFACT_OPERATORS = {b'BDC', b'EMC', b'q', b'Q', b'cm', b'cs', b'sc',
                       b'scn', b'rg', b'g', b'k', b're', b'h', b'f', b'F', b'f*'}
_SEMANTIC = {'/ActualText', '/Alt', '/E', '/OC'}


def _key(glyph):
    return (glyph.id, glyph.text, tuple(glyph.origin), tuple(glyph.bbox),
            glyph.font, glyph.size, tuple(glyph.color), glyph.opacity,
            tuple(glyph.direction), glyph.mode, glyph.font_resource, glyph.font_xref)


def _same_rect(left, right, tolerance=.015):
    return len(left) == len(right) == 4 and all(abs(a-b) <= tolerance for a,b in zip(left,right))


def _number(value):
    return FloatObject(float(value))


def _attribute_number(value):
    # Attribute dictionaries use pypdf's normal serializer. Snapshot precisely
    # the decimal that serializer will write, rather than an unrounded float.
    return FloatObject(round(float(value),4))


def _role(structure, node):
    from .tagged import obj
    role = str(node.get('/S', ''))
    roles = obj(structure.tree.get('/RoleMap', {})); seen = set()
    while isinstance(roles, dict) and role in roles:
        if role in seen:return ''
        seen.add(role); role = str(obj(roles[role]))
    return role


def _ancestors(structure, path):
    return [(prefix, structure.nodes[prefix]) for length in range(len(path), -1, -1)
            if (prefix := path[:length]) in structure.nodes]


def _container(structure, path):
    # Some generators map their graphical /Artifact elements to /P. Such a
    # leaf is still the decoration itself, rather than its text container.
    return next((p for p,n in _ancestors(structure,path)
                 if str(n.get('/S',''))!='/Artifact' and _role(structure,n) in _CONTAINERS), None)


def _effective_decoration(structure, node):
    from .tagged import obj, _attribute_items
    inherited=[]
    if '/C' in node:
        classes,_=_attribute_items(node['/C'],NameObject)
        classmap=obj(structure.tree.get('/ClassMap'))
        if not isinstance(classmap,dict):return None
        for name in classes:
            if name not in classmap:return None
            items,_=_attribute_items(classmap[name],dict,revisions=False);inherited.extend(items)
    direct,_=_attribute_items(node['/A'],dict) if '/A' in node else ([],[])
    effective={}
    for group in (inherited,direct):
        local={}
        for attributes in group:
            if obj(attributes).get('/O')!='/Layout':continue
            for key,value in attributes.items():
                if key in local and local[key]!=value:return None
                local[key]=value
        effective.update(local)
    return effective.get('/TextDecorationType')


def _bound_paths(structure, page, mcid, owner):
    paths=[]
    for path,node in _ancestors(structure,owner):
        if _SEMANTIC & set(node):return []
        if _effective_decoration(structure,node)!='/Underline':continue
        contents=[key for key,value in structure.owners.items() if value[:len(path)]==path]
        if set(contents)!={(page,mcid)}:return []
        paths.append(path)
    return paths


def _artifact_attributes(structure, path, old_pdf_rect):
    from .tagged import obj
    node=structure.nodes[path]
    if _SEMANTIC & set(node) or '/C' in node:return False,None
    if '/A' not in node:return True,None
    attributes=obj(node['/A'])
    if (not isinstance(attributes,dict) or attributes.get('/O')!='/Layout'
            or set(attributes)-{'/O','/BBox'}):return False,None
    if '/BBox' not in attributes:return True,None
    box=obj(attributes['/BBox'])
    if (not isinstance(box,(list,tuple)) or len(box)!=4
            or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in box)):
        return False,None
    if not _same_rect(tuple(map(float,box)),old_pdf_rect):return False,None
    return True,copy.deepcopy(attributes)


def _frame_side(rect, other_drawings):
    """A line completing a closed frame has an additional geometric owner."""
    from .selection_v300 import boundaries_from_drawings, edge_covers
    edges=boundaries_from_drawings(other_drawings)
    horizontal=[(min(x0,x1),y0,max(x0,x1)) for x0,y0,x1,y1 in edges if abs(y1-y0)<.5]
    vertical=[(min(y0,y1),x0,max(y0,y1)) for x0,y0,x1,y1 in edges if abs(x1-x0)<.5]
    x0,y0,x1,y1=rect;middle=(y0+y1)/2
    # A separately painted coincident horizontal edge is ambiguous even when
    # the rest of its frame is stored as a compound or nonrectangular path.
    if any(abs(y-middle)<=max(.75,(y1-y0)/2) and min(end,x1)-max(start,x0)>1.
           for start,y,end in horizontal):return True
    for _,other_y,_ in horizontal:
        if abs(other_y-middle)<3.:continue
        if (edge_covers(horizontal,other_y,x0,x1)
                and edge_covers(vertical,x0,min(middle,other_y),max(middle,other_y))
                and edge_covers(vertical,x1,min(middle,other_y),max(middle,other_y))):return True
    return False


class SourceDecorationPolicy:
    """An immutable-source binding plus a checked single-line rectangle plan."""
    def __init__(self, token, **values):
        if token is not _TOKEN:raise TypeError('Las decoraciones originales requieren una vinculación verificada.')
        self.__dict__.update(values)
        self._planned=None; self._new_owner=None; self._new_rect=None; self._new_args=None
        self._new_attributes=None

    def _supported_styles(self, planned):
        styles={(g.font,round(g.size,5),tuple(round(v,5) for v in g.color),round(g.opacity,5),g.mode,tuple(g.direction)) for g in self.original}
        baselines={round(g.origin[1],4) for g in self.original}
        return all((g.font,round(g.size,5),tuple(round(v,5) for v in g.color),round(g.opacity,5),g.mode,tuple(g.direction)) in styles
                   and round(g.origin[1],4) in baselines for g in planned)

    def _owner_after(self, planned):
        positions=[i for i,g in enumerate(self.original) if g.id in self.selected_ids]
        return self.original[:min(positions)]+list(planned)+self.original[max(positions)+1:]

    def needs_update(self, planned):
        """Use this joint route only for reproducible changed owner extents.

        Other style choices retain the ordinary text guard and original line;
        preparing an optional decoration must not prohibit a previously valid
        color or font edit whose bounds stay inside that line's text scope.
        """
        planned=list(planned)
        if not self._supported_styles(planned):return False
        owner=self._owner_after(planned)
        if not owner:return True
        before=union(g.bbox for g in self.original);after=union(g.bbox for g in owner)
        return any(abs(before[i]-after[i])>.0002 for i in (0,2))

    def plan(self, planned, *, allow_overlap=False):
        planned=list(planned)
        if not self._supported_styles(planned):
            raise EditError('El subrayado original requiere conservar la fuente, color, tamaño y línea base del texto.')
        owner=self._owner_after(planned)
        if any(not all(math.isfinite(v) for v in (*g.origin,*g.bbox)) for g in owner):
            raise EditError('La geometría del texto subrayado no es finita.')
        old_bounds=union(g.bbox for g in self.original)
        if owner:
            new_bounds=union(g.bbox for g in owner)
            left=self.old_rect[0]+new_bounds[0]-old_bounds[0]
            right=self.old_rect[2]+new_bounds[2]-old_bounds[2]
            if right<=left:
                raise EditError('La nueva disposición no conserva una anchura válida para el subrayado.')
        else:left=right=self.old_rect[0]
        new_rect=(left,self.old_rect[1],right,self.old_rect[3])
        if not (self.clip+(-.001,-.001,.001,.001)).contains(fitz.Rect(new_rect)):
            raise EditError('El nuevo subrayado queda fuera de la página o de su recorte original.')
        if not allow_overlap:
            for g in self.model.glyphs:
                if g.id in self.owner_ids:continue
                if intersects(new_rect,g.bbox,.12) and not intersects(self.old_rect,g.bbox,.12):
                    raise EditError('El nuevo subrayado se solapa con texto vecino; permite el solapamiento o redistribuye el texto.')
        # Avoid a float32 round trip through Rect/Matrix. Original path
        # coordinates plus the measured horizontal delta preserve y/height
        # exactly and preserve width for an unchanged or interior-only edit.
        pdf_left=float(self.original_args[0])+(left-self.old_rect[0])/self.linear.a
        pdf_width=float(self.original_args[2])+((right-left)-(self.old_rect[2]-self.old_rect[0]))/self.linear.a
        if not owner:pdf_width=0.
        if pdf_width<0 or not math.isfinite(pdf_left+pdf_width):
            raise EditError('No se puede reproducir la geometría del subrayado original.')
        pdf_rect=(pdf_left*self.ctm.a+self.ctm.e,
                  float(self.original_args[1])*self.ctm.d+self.ctm.f,
                  (pdf_left+pdf_width)*self.ctm.a+self.ctm.e,
                  (float(self.original_args[1])+float(self.original_args[3]))*self.ctm.d+self.ctm.f)
        self._planned=tuple(_key(g) for g in planned);self._new_owner=tuple(_key(g) for g in owner)
        self._new_rect=new_rect
        # Preserve original PDF y/height exactly. Only x and width change.
        self._new_args=(_number(pdf_left),self.original_args[1],
                        _number(pdf_width),self.original_args[3])
        if self.artifact_attributes is not None:
            attributes=copy.deepcopy(self.artifact_attributes)
            attributes[NameObject('/BBox')]=ArrayObject([_attribute_number(v) for v in pdf_rect])
            self._new_attributes=attributes
        return self

    def matches_source(self, structure, page, model, selected, planned):
        return (structure is self.structure and page==self.page and model.number==self.page
                and hashlib.sha256(structure.data).hexdigest()==self.source_hash
                and model.revision==self.source_hash
                and tuple(_key(g) for g in model.glyphs)==self.model_snapshot
                and tuple(_key(g) for g in selected)==self.selected_snapshot
                and self._planned is not None
                and tuple(_key(g) for g in planned)==self._planned)

    def allows_decoration(self, path, original, planned):
        return (self._new_owner is not None and tuple(path) in self.paths
                and Counter(_key(g) for g in original)==Counter(_key(g) for g in self.original)
                and Counter(_key(g) for g in planned)==Counter(self._new_owner))

    @property
    def old_shapes(self):return [{'rect':self.old_rect,'color':self.color}]

    @property
    def new_shapes(self):
        if self._new_rect is None:raise EditError('El subrayado todavía no tiene una disposición validada.')
        return [{'rect':self._new_rect,'color':self.color}]

    def apply_operations(self, operations, index_map):
        from .clipping import _signature
        if self._new_args is None:raise EditError('No hay un plan validado para el subrayado.')
        mapped=[]
        for index in range(self.mark_start,self.mark_end+1):
            if index not in index_map:raise EditError('Se perdió un operador del subrayado original.')
            target=index_map[index];mapped.append(target)
            if target<0 or target>=len(operations) or _signature(operations[target])!=_signature(self.operations[index]):
                raise EditError('Los operadores del subrayado original cambiaron antes de aplicar el plan.')
        if mapped!=list(range(mapped[0],mapped[0]+len(mapped))):
            raise EditError('La marca del subrayado original dejó de ser contigua.')
        operations[index_map[self.rect_operation]]=(list(self._new_args),b're')

    def expected_structure(self, expected):
        from .tagged import _attribute_snapshot
        if self._new_attributes is not None:
            expected['nodes'][self.artifact_path]['/A']=_attribute_snapshot(self._new_attributes)
        return expected

    def apply_structure(self, document):
        from .tagged import ref
        if self._new_attributes is not None:
            buffer=BytesIO();self._new_attributes.write_to_stream(buffer)
            document.xref_set_key(ref(self.structure.nodes[self.artifact_path])[0],'A',buffer.getvalue().decode('latin1'))

    def validate(self, output):
        from .tagged import analyze_readonly, _attribute_snapshot
        from .clipping import _signature
        if self._new_args is None:raise EditError('No hay un plan validado para el subrayado.')
        result=analyze_readonly(output)
        if result is None or result.owners.get((self.page,self.artifact_mcid))!=self.artifact_path or result.owners.get((self.page,self.text_mcid))!=self.text_path:
            raise EditError('Se perdió la relación lógica entre el texto y su subrayado original.')
        mark=result.marks[self.page].get(self.artifact_mcid)
        if mark is None or str(mark.tag)!='/Artifact':raise EditError('Se perdió la marca del subrayado original.')
        actual=result.operations[self.page][mark.start:mark.end+1]
        expected=copy.deepcopy(self.operations[self.mark_start:self.mark_end+1])
        offset=self.rect_operation-self.mark_start;expected[offset]=(list(self._new_args),b're')
        if len(actual)!=len(expected):raise EditError('Cambió el contenido del artefacto del subrayado.')
        for i,(left,right) in enumerate(zip(actual,expected)):
            if i==offset:
                if left[1]!=b're' or len(left[0])!=4 or any(abs(float(a)-float(b))>1e-6 for a,b in zip(left[0],right[0])):
                    raise EditError('La geometría final del subrayado no coincide con el plan.')
            elif _signature(left)!=_signature(right):raise EditError('Cambió un operador ajeno del subrayado original.')
        if self._new_attributes is not None and _attribute_snapshot(result.nodes[self.artifact_path].get('/A'))!=_attribute_snapshot(self._new_attributes):
            raise EditError('La caja accesible del subrayado no coincide con su nueva geometría.')
        with fitz.open(stream=output,filetype='pdf') as document:
            matches=[d for d in document[self.page].get_drawings() if d.get('type')=='f'
                     and _same_rect(d['rect'],self._new_rect) and d.get('fill') is not None
                     and all(abs(a-b)<.001 for a,b in zip(d['fill'],self.color))
                     and d.get('fill_opacity')==1.]
            if len(matches)!=1:raise EditError('No se pudo comprobar el subrayado original dibujado.')
        return dict(verified=True,text_mcid=self.text_mcid,artifact_mcid=self.artifact_mcid,
                    original_artifact_preserved=True,geometry_updated=True,
                    attribute_box_updated=self._new_attributes is not None)

    def report(self):
        return dict(text_mcid=self.text_mcid,artifact_mcid=self.artifact_mcid,
                    original_rect=self.old_rect,new_rect=self._new_rect,
                    original_artifact_preserved=True,attribute_box_updated=self._new_attributes is not None)


def prepare_source_decorations(data,page,model,selected,structure,operations,mapping):
    """Bind one unique original rectangle, or retain the ordinary strict guards."""
    from .tagged import obj
    from .clipping import _signature, _strings, _raw
    from .clipped_layout import _state_at
    if structure is None or not selected:return None
    if (page!=model.number or model.revision!=hashlib.sha256(data).hexdigest()
            or structure.data!=data):return None
    if len(operations)!=len(structure.operations[page]) or any(_signature(a)!=_signature(b) for a,b in zip(operations,structure.operations[page])):
        return None
    contexts=structure.glyph_contexts(page,model)
    owners={contexts.get(g.id) for g in selected}
    if len(owners)!=1 or None in owners:return None
    mcid=owners.pop();owner=structure.owners[(page,mcid)]
    paths=_bound_paths(structure,page,mcid,owner)
    if not paths:return None
    container=_container(structure,owner)
    if container is None:return None
    original=[g for g in model.glyphs if contexts.get(g.id)==mcid]
    selected_ids={g.id for g in selected};positions=[i for i,g in enumerate(original) if g.id in selected_ids]
    if not positions or positions!=list(range(min(positions),max(positions)+1)):return None
    if (any(g.mode!=0 or g.opacity!=1. or g.direction!=(1.,0.) or not g.reliable for g in original)
            or len({round(g.origin[1],4) for g in original})!=1
            or len({round(g.size,5) for g in original})!=1
            or len({g.font for g in original})!=1
            or len({tuple(round(v,5) for v in g.color) for g in original})!=1):return None
    text_mark=structure.marks[page][mcid]
    if text_mark.nested_actual or set(text_mark.resolved)-{'/MCID','/Lang'}:return None
    bounds=union(g.bbox for g in original);size=original[0].size;baseline=original[0].origin[1]
    resources=obj(structure.reader.pages[page].get('/Resources',{}));candidates=[]
    with fitz.open(stream=data,filetype='pdf') as document:
        pdfpage=document[page];rotation=pdfpage.rotation;pdfpage.set_rotation(0)
        page_matrix=pdfpage.transformation_matrix;page_bounds=fitz.Rect(0,0,pdfpage.cropbox.width,pdfpage.cropbox.height)
        pdfpage.set_rotation(rotation);drawings=pdfpage.get_drawings()
    if any(g.id not in mapping for g in original):return None
    shows={mapping[g.id]['operation'] for g in original}
    for artifact_mcid,mark in structure.marks[page].items():
        if str(mark.tag)!='/Artifact' or mark.nested_actual or set(mark.resolved)-{'/MCID','/Lang'}:continue
        artifact_path=structure.owners.get((page,artifact_mcid))
        if artifact_path is None or artifact_path not in structure.nodes or _container(structure,artifact_path)!=container:continue
        if any(contexts.get(g.id)==artifact_mcid for g in model.glyphs):continue
        section=operations[mark.start:mark.end+1]
        if any(operator not in _ARTIFACT_OPERATORS for _,operator in section):continue
        rectangles=[mark.start+i for i,(_,operator) in enumerate(section) if operator==b're']
        fills=[mark.start+i for i,(_,operator) in enumerate(section) if operator in (b'f',b'F',b'f*')]
        if len(rectangles)!=1 or len(fills)!=1 or rectangles[0]>=fills[0]:continue
        rect_operation=rectangles[0];args,op=operations[rect_operation]
        if len(args)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in args):continue
        if float(args[2])<=0 or float(args[3])<=0:continue
        state=_state_at(operations,rect_operation,resources);ctm=state['ctm']
        if state['unknown'] or not all(math.isfinite(v) for v in ctm) or abs(ctm.b)+abs(ctm.c)>1e-7 or ctm.a<=0 or ctm.d<=0:continue
        linear=ctm*page_matrix;x,y,w,h=map(float,args);physical=fitz.Rect(x,y,x+w,y+h)*linear
        if (not 0<physical.height<=min(2.,size*.2) or physical.width<=max(3.,physical.height*3)
                or not -.02<=physical.y0-baseline<=size*.4
                or abs(physical.x0-bounds[0])>size*.12
                or abs(physical.x1-bounds[2])>size*.12):continue
        matches=[d for d in drawings if d.get('type')=='f' and _same_rect(d['rect'],physical)
                 and d.get('fill_opacity')==1. and d.get('fill') is not None
                 and all(abs(a-b)<.001 for a,b in zip(d['fill'],original[0].color))
                 and len(d.get('items',[]))==1 and d['items'][0][0]=='re']
        if len(matches)!=1:continue
        if _frame_side(physical,[drawing for drawing in drawings if drawing is not matches[0]]):continue
        if mark.start>max(shows):between=range(max(shows)+1,mark.start)
        elif mark.end<min(shows):between=range(mark.end+1,min(shows))
        else:continue
        intervening={i for i in between if operations[i][1] in (b'Tj',b'TJ',b"'",b'"')}
        if any(not g.text.isspace() for g in model.glyphs if mapping.get(g.id,{}).get('operation') in intervening):continue
        # The native compositor leaves numeric TJ cursor compensation after
        # removing a source string. It paints no characters and must not make
        # the surviving original line impossible to bind after reopening.
        unidentified=[i for i in intervening if not any(mapping.get(g.id,{}).get('operation')==i for g in model.glyphs)]
        if any(operations[i][1] not in (b'Tj',b'TJ') or any(_raw(value) for _,value in _strings(*operations[i])) for i in unidentified):continue
        if any(operations[i][1] in (b'Do',b'sh',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*') for i in between):continue
        clip=state['clip']*page_matrix if state['clip'] is not None else page_bounds
        clip &= page_bounds
        if not (clip+(-.001,-.001,.001,.001)).contains(physical):continue
        default_rect=(x*ctm.a+ctm.e,y*ctm.d+ctm.f,
                      (x+w)*ctm.a+ctm.e,(y+h)*ctm.d+ctm.f)
        ok,attributes=_artifact_attributes(structure,artifact_path,default_rect)
        if not ok:continue
        candidates.append(dict(structure=structure,page=page,model=model,original=original,
            selected_ids=selected_ids,selected_snapshot=tuple(_key(g) for g in selected),owner_ids={g.id for g in original},
            source_hash=hashlib.sha256(data).hexdigest(),model_snapshot=tuple(_key(g) for g in model.glyphs),
            paths=tuple(paths),text_mcid=mcid,text_path=owner,artifact_mcid=artifact_mcid,
            artifact_path=artifact_path,mark_start=mark.start,mark_end=mark.end,rect_operation=rect_operation,
            original_args=tuple(args),old_rect=tuple(physical),color=tuple(matches[0]['fill']),
            operations=copy.deepcopy(operations),linear=linear,ctm=fitz.Matrix(ctm),clip=clip,artifact_attributes=attributes))
    return SourceDecorationPolicy(_TOKEN,**candidates[0]) if len(candidates)==1 else None
