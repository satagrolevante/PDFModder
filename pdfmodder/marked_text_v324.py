"""Native text edits retain inline semantics and registered optional content.

No structure tree is invented or removed. Every original marker survives in
its original nesting; the final text must keep its proven scope membership.
"""
from collections import defaultdict
from hashlib import sha256

import pymupdf as fitz
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from .clipping import SHOW, _signature
from .draft_control_v305 import checkpoint
from .model import EditError


def _fail(message):
    raise EditError('Contenido marcado: '+message)


def _scan(reader,page,operations):
    from .tagged import obj,ref
    from .marked_content_v303 import _properties,_PLAIN_TAGS,_SPECIAL_TAGS
    root=reader.trailer['/Root']
    catalog=obj(root.get('/OCProperties',{}))
    groups=list(obj(catalog.get('/OCGs',[]))) if isinstance(catalog,dict) else []
    registered={ref(value):i for i,value in enumerate(groups) if ref(value) is not None}
    resources=obj(reader.pages[page].get('/Resources',{}))
    named=obj(resources.get('/Properties',{}))
    frames=[];events=[];contexts=[];stack=[]
    for index,(args,op) in enumerate(operations):
        if index%256==0:checkpoint()
        if op in (b'BMC',b'BDC',b'MP',b'DP'):
            with_props=op in (b'BDC',b'DP')
            if len(args)!=(2 if with_props else 1) or not isinstance(args[0],NameObject):
                _fail('hay una marca incompleta; no se modifica su ámbito.')
            tag=str(args[0]);operand=args[1] if with_props else None
            raw=named.get(operand) if isinstance(operand,NameObject) else operand
            props=obj(raw) if raw is not None else (None if with_props else {})
            safe=False;binding=None
            if tag=='/OC' and with_props and isinstance(props,dict):
                if props.get('/Type')=='/OCG' and ref(raw) in registered:
                    safe=True;binding=('OCG',registered[ref(raw)])
                elif props.get('/Type')=='/OCMD' and '/VE' not in props:
                    members=obj(props.get('/OCGs',[]))
                    members=members if isinstance(members,(list,tuple)) else [members]
                    if (members and all(ref(x) in registered for x in members)
                            and props.get('/P','/AnyOn') in ('/AnyOn','/AllOn','/AnyOff','/AllOff')):
                        safe=True;binding=('OCMD',tuple(registered[ref(x)] for x in members))
            elif tag not in _SPECIAL_TAGS:
                try:
                    if with_props:
                        if not isinstance(props,dict):raise ValueError()
                        plain=DictionaryObject({k:v for k,v in props.items() if k not in ('/ActualText','/Lang')})
                        _properties(tag,plain,resources)
                        if '/ActualText' in props and not isinstance(obj(props['/ActualText']),str):raise ValueError()
                        if '/Lang' in props:
                            lang=obj(props['/Lang'])
                            if not isinstance(lang,str) or not lang or any(ord(c)<32 for c in lang):raise ValueError()
                        safe=True
                    else:safe=tag in _PLAIN_TAGS
                except (EditError,ValueError,TypeError,KeyError):pass
            identifier=len(frames)
            protective=(not safe or tag in ('/OC','/Artifact') or
                        isinstance(props,dict) and bool(set(props)&{'/ActualText','/Lang'}))
            frames.append(dict(tag=tag,op=op,properties=props,operation=index,safe=safe,
                               protective=protective,binding=binding,operand=operand))
            events.append(('open',identifier))
            if op in (b'BMC',b'BDC'):stack.append(identifier)
            if len(stack)>100:_fail('hay demasiados ámbitos anidados para conservarlos con garantías.')
        contexts.append(tuple(i for i in stack if frames[i]['protective']))
        if op==b'EMC':
            if args or not stack:_fail('hay un cierre sin apertura.')
            events.append(('close',stack.pop()))
    if stack:_fail('hay un ámbito sin cerrar.')
    return frames,events,contexts,_signature(root.get('/OCProperties',{}))


def native_marked_plan(data,page,model,selected,planned,operations,mapping,*,reader=None,replacement_text=None):
    from io import BytesIO
    from pypdf import PdfReader
    reader=reader or PdfReader(BytesIO(data),strict=True)
    if reader.trailer['/Root'].get('/StructTreeRoot'):return None
    if not any(op in (b'BMC',b'BDC',b'MP',b'DP') for _,op in operations):return None
    return NativeMarkedTextPlan(data,page,model,selected,planned,operations,mapping,reader,replacement_text)


def compatible_page_markers(reader,page,operations):
    """Recognized page scopes can be advertised without treating them as tags."""
    from .tagged import obj
    try:
        frames,_,_,_=_scan(reader,page,operations)
        if not all(frame['safe'] for frame in frames):return False
        resources=obj(reader.pages[page].get('/Resources',{}))
        objects=obj(resources.get('/XObject',{}))
        # Forms keep the recursive source check and selection-isolation path;
        # a page-only classification must not certify their private namespaces.
        return not any(op==b'Do' and args and args[0] in objects
                       and obj(objects[args[0]]).get('/Subtype')=='/Form' for args,op in operations)
    except (EditError,ValueError,TypeError,KeyError,IndexError):return False


class NativeMarkedTextPlan:
    def __init__(self,data,page,model,selected,planned,operations,mapping,reader,replacement_text=None):
        if model.number!=page or model.revision!=sha256(data).hexdigest():
            _fail('la selección pertenece a otra revisión.')
        self.data=data;self.page=page;self.revision=model.revision
        self.expected=None;self.marker_updates={};self.actual_updates={};self.layout_updates={}
        self.frames,self.events,contexts,self.catalog=_scan(reader,page,operations)
        self.added_frames=[];self.added_events=[]
        if any(g.id not in mapping for g in selected):_fail('no se pudo aislar el operador seleccionado.')
        self.source_ids={g.id for g in selected}
        glyph_contexts={g.id:contexts[mapping[g.id]['operation']] for g in model.glyphs if g.id in mapping}
        owned_glyphs=defaultdict(list)
        for g in model.glyphs:
            for scope in glyph_contexts.get(g.id,()):owned_glyphs[scope].append(g)
        selected_contexts={contexts[mapping[g.id]['operation']] for g in selected}
        self.affected=set().union(*selected_contexts)
        if len(selected_contexts)!=1:
            common=set.intersection(*(set(c) for c in selected_contexts))
            differing=self.affected-common
            compatible=all(self.frames[i]['tag'] in ('/P','/Span')
                and isinstance(self.frames[i]['properties'],dict)
                and '/ActualText' in self.frames[i]['properties']
                and not set(self.frames[i]['properties'])-{'/MCID','/ActualText','/Lang'}
                and all(g.id in self.source_ids for g in owned_glyphs[i]) for i in differing)
            languages={str(self.frames[i]['properties'].get('/Lang','')) for i in differing
                       if isinstance(self.frames[i]['properties'],dict)}
            if not compatible or len(languages)>1:
                _fail('la selección cruza idiomas, capas o descripciones independientes; edita cada bloque por separado.')
        self.target_context=contexts[mapping[selected[0].id]['operation']]
        if any(not self.frames[i]['safe'] for i in self.affected):
            _fail('el bloque tiene propiedades semánticas especiales que necesitan una edición conjunta.')
        self.layers={g.layer for g in selected if g.layer}
        self.expected_glyphs=defaultdict(list)
        for g in model.glyphs:
            if g.id in glyph_contexts and g.id not in self.source_ids:
                self.expected_glyphs[glyph_contexts[g.id]].append(g)
        self.expected_glyphs[self.target_context].extend(planned)
        self.updates={}
        for i in self.affected:
            frame=self.frames[i];props=frame['properties']
            if not isinstance(props,dict) or '/ActualText' not in props:continue
            owned=owned_glyphs[i]
            before=''.join(g.text for g in owned)
            chosen=[j for j,g in enumerate(owned) if g.id in self.source_ids]
            if not chosen:continue
            replacement=(replacement_text if replacement_text is not None else ''.join(g.text for g in planned)) if i in self.target_context else ''
            new=(''.join(g.text for g in owned[:min(chosen)])+replacement
                 +''.join(g.text for g in owned[min(chosen):] if g.id not in self.source_ids))
            if new==before:continue
            if str(props['/ActualText'])!=before and any(g.id not in self.source_ids for g in owned):
                _fail('ActualText describe más que la selección; selecciona el bloque completo para sustituirlo.')
            if chosen!=list(range(min(chosen),max(chosen)+1)):
                _fail('la sustitución divide una descripción ActualText en fragmentos separados.')
            updated=DictionaryObject(dict(props));updated[NameObject('/ActualText')]=TextStringObject(new)
            self.updates[i]=updated

    def allows_layer(self,page,model,glyph):
        return (page.number==self.page and model.number==self.page and model.revision==self.revision
                and glyph.layer in self.layers and (glyph.id in self.source_ids or glyph.id==-1)
                and any(self.frames[i]['binding'] is not None for i in self.target_context))

    def apply_operations(self,operations):
        for i,props in self.updates.items():
            frame=self.frames[i]
            operations[frame['operation']]=([NameObject(frame['tag']),props],frame['op'])

    def apply_updates(self,document):
        pass

    def wrap_graphics(self,operations):
        """New underline paths inherit the text's exact optional-content scope."""
        layers=[self.frames[i] for i in self.target_context if self.frames[i]['binding'] is not None]
        if not layers:return operations
        prefix=[];ids=[]
        for frame in layers:
            identifier=len(self.frames)+len(self.added_frames)
            self.added_frames.append(frame)
            self.added_events.append(('open',identifier));ids.append(identifier)
            prefix.append(([NameObject('/OC'),frame['operand']],b'BDC'))
        for identifier in reversed(ids):self.added_events.append(('close',identifier))
        return prefix+operations+[([],b'EMC') for _ in layers]

    def validate(self,output):
        from .engine import extract_page
        from .clipping import operator_glyph_map
        from .tagged_unmarked_v323 import _assert_membership
        with fitz.open(stream=output,filetype='pdf') as doc:model=extract_page(doc,self.page,output)
        reader,operations,_,mapping=operator_glyph_map(output,self.page,model)
        frames,events,contexts,catalog=_scan(reader,self.page,operations)
        def snapshot(values,updates=None):
            return [(f['tag'],f['op'],_signature((updates or {}).get(i,f['properties'])),f['binding'])
                    for i,f in enumerate(values)]
        if (catalog!=self.catalog or events!=self.events+self.added_events
                or snapshot(frames)!=snapshot(self.frames+self.added_frames,self.updates)):
            _fail('el resultado cambió marcas, propiedades u otras capas ajenas a la edición.')
        actual=defaultdict(list)
        for g in model.glyphs:
            if g.id in mapping:actual[contexts[mapping[g.id]['operation']]].append(g)
        for context in set(self.expected_glyphs)|set(actual):
            _assert_membership(self.expected_glyphs[context],actual[context])
        return {'verified':True,'marked_content_preserved':True,'layer_membership_preserved':True,
                'actual_text_updates':len(self.updates),'structure_tree_removed':False}
