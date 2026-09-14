"""Edición nativa de campos recortados con compensación del cursor PDF.

Preserva Tf/Tc/Tw/Tz, la fuente y los recortes. Cambia un único Tj/TJ usando
códigos verificados del mismo recurso. No reconstruye texto con otra fuente
ni mueve los vecinos. Sólo admite matrices horizontales y recortes conocidos.
"""
from dataclasses import replace
from io import BytesIO
import copy
import hashlib
import math
import time
import unicodedata

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject,ByteStringObject,ContentStream,FloatObject
from .clipping import CLIP_ISSUE,operator_glyph_map,_advance,_raw,_serialize,_signature,_strings
from .model import EditError,intersects,union
from .validation import document_issues,validate_transition

def _state_at(operations,index):
    state={'size':None,'tc':0.,'tw':0.,'tz':1.,'tr':0,'ctm':fitz.Matrix(1,0,0,1,0,0),
           'clip':None,'unknown':False}
    stack=[]
    text_matrix=fitz.Matrix(1,0,0,1,0,0)
    path,pending=None,False
    text_clips=False
    for args,op in operations[:index]:
        if op==b'q':stack.append(dict(state))
        elif op==b'Q':state=stack.pop()
        elif op==b'cm':state['ctm']=fitz.Matrix(*[float(v) for v in args])*state['ctm']
        elif op==b'BT':
            text_matrix=fitz.Matrix(1,0,0,1,0,0)
            text_clips=False
        elif op in (b'Tj',b'TJ',b"'",b'"') and state['tr']>=4:text_clips=True
        elif op==b'ET' and text_clips:state['unknown']=True
        elif op==b'Tm':text_matrix=fitz.Matrix(*[float(v) for v in args])
        elif op==b'Tf':state['size']=float(args[1])
        elif op==b'Tc':state['tc']=float(args[0])
        elif op==b'Tw':state['tw']=float(args[0])
        elif op==b'Tz':state['tz']=float(args[0])/100
        elif op==b'Tr':state['tr']=int(args[0])
        elif op==b're':
            x,y,w,h=map(float,args)
            path=fitz.Rect(min(x,x+w),min(y,y+h),max(x,x+w),max(y,y+h))*state['ctm'] if path is None and state['ctm'].is_rectilinear else False
        elif op in (b'm',b'l',b'c',b'v',b'y',b'h'):path=False
        elif op in (b'W',b'W*'):pending=True
        elif op in (b'n',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'):
            if pending:
                if path is None or path is False:state['unknown']=True
                else:state['clip']=path if state['clip'] is None else state['clip']&path
            path,pending=None,False
        elif op==b'gs':
            # A gs /Font can change Tf. Require an explicit Tf after any gs,
            # so the inherited font size can never be guessed.
            state['size']=None
    state['matrix']=text_matrix*state['ctm']
    return state


def edit_clipped_layout(data,request,model):
    from .engine import _safe_selection,full_write
    started=time.perf_counter()
    if request.page!=model.number or (request.revision and request.revision!=hashlib.sha256(data).hexdigest()):
        raise EditError('La selección está desactualizada. Selecciona el texto de nuevo.')
    selected=model.selected(request.ids)
    if not selected or len(selected)!=len(set(request.ids)):
        raise EditError('Selecciona un fragmento contiguo del documento actual.')
    if request.text is None or request.reflow or '\n' in request.text or '\r' in request.text:
        raise EditError('Texto recortado: la redistribución entre líneas no está habilitada. Edita un campo de una sola línea.')
    if request.dx or request.dy or request.font_name or request.font_file or request.color is not None:
        raise EditError('Texto recortado: mover o cambiar la fuente o el color necesita otro tratamiento; conserva el formato original.')
    if request.size is not None and any(abs(request.size-g.size)>.001 for g in selected):
        raise EditError('Texto recortado: conserva el tamaño original; no se comprime ni reduce el texto automáticamente.')
    if request.anchor not in ('left','right','center'):
        raise EditError('Texto recortado: utiliza anclaje izquierdo, centrado o derecho para este cambio.')
    text=''.join(g.text for g in selected)
    new_text=request.text
    if any(unicodedata.category(c).startswith('C') or unicodedata.combining(c) for c in new_text):
        raise EditError('No se admiten controles ni marcas combinantes; usa acentos precompuestos.')
    bounds=union(g.bbox for g in selected)
    width=request.width if request.width is not None else bounds[2]-bounds[0]
    height=request.height if request.height is not None else bounds[3]-bounds[1]
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (width,height)):
        raise EditError('El área de edición debe tener dimensiones positivas y finitas.')
    if request.anchor=='right':area_left=bounds[2]-width
    elif request.anchor=='center':area_left=(bounds[0]+bounds[2]-width)/2
    else:area_left=bounds[0]
    area=(area_left,bounds[1],area_left+width,bounds[1]+height)
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:raise EditError('\n'.join(issues))
        _safe_selection(doc[request.page],replace(model,issues=[i for i in model.issues if i!=CLIP_ISSUE]),selected)
        rotation=doc[request.page].rotation
        doc[request.page].set_rotation(0)
        page_matrix=doc[request.page].transformation_matrix
        page_bounds=fitz.Rect(0,0,doc[request.page].cropbox.width,doc[request.page].cropbox.height)
        doc[request.page].set_rotation(rotation)
    if any(g.mode!=0 or not g.reliable for g in selected):raise EditError('Texto no visible o codificación ambigua.')
    if any(g.mode==3 and any(intersects(g.bbox,s.bbox) for s in selected) for g in model.glyphs):
        raise EditError('Capa OCR superpuesta: operación bloqueada.')
    reader,operations,shows,mapping=operator_glyph_map(data,request.page,model)
    if reader.trailer['/Root'].get('/StructTreeRoot'):raise EditError('Texto recortado: esta combinación con etiquetas accesibles necesita actualizar su semántica conjuntamente.')
    operation_ids={mapping[g.id]['operation'] for g in selected}
    if len(operation_ids)!=1:raise EditError('El campo está dividido en varias operaciones de texto. Selecciona un fragmento que pueda aislarse.')
    operation=operation_ids.pop()
    show=next(s for s in shows if s['operation']==operation)
    args,op=operations[operation]
    if op not in (b'Tj',b'TJ') or show['render_mode']!=0:raise EditError('El texto usa un modo de pintura, recorte o salto no compatible; esta operación requiere texto visible normal.')
    font=show['font']
    if font.get('/Subtype') not in ('/TrueType','/Type1'):raise EditError('La fuente no usa códigos simples verificables en esta ruta de edición.')
    state=_state_at(operations,operation)
    matrix=state['matrix']
    if (state['size'] is None or not all(math.isfinite(v) for v in (state['size'],state['tc'],state['tw'],state['tz'],*matrix)) or
            state['size']<=0 or state['tz']<=0 or
            abs(matrix.b)+abs(matrix.c)>1e-7 or matrix.a<=0 or matrix.d<=0 or state['unknown']):
        raise EditError('El campo hereda un recorte de texto, un recorte complejo o una transformación no compatible; no se modificará su contenido.')
    catalog={}
    for candidate in shows:
        if (candidate['resource'],candidate['xref'])!=(show['resource'],show['xref']):continue
        a,o=operations[candidate['operation']]
        raw=b''.join(_raw(v) for _,v in _strings(a,o))
        if len(raw)!=len(candidate['glyphs']):continue
        for code,glyph in zip(raw,candidate['glyphs']):catalog.setdefault(glyph.text,set()).add(code)
    if any(len(catalog.get(c,set()))!=1 for c in new_text):raise EditError('Faltan códigos únicos en la fuente original.')
    new_codes=bytes(next(iter(catalog[c])) for c in new_text)
    original_codes=b''.join(_raw(v) for _,v in _strings(args,op))
    if len(original_codes)!=len(show['glyphs']):raise EditError('No es correspondencia uno a uno código/glifo.')
    ids=[g.id for g in show['glyphs']]
    first,last=ids.index(selected[0].id),ids.index(selected[-1].id)+1
    if ids[first:last]!=[g.id for g in selected] or len({g.line for g in selected})!=1:raise EditError('Selecciona un fragmento contiguo de una sola línea.')
    whole=first==0 and last==len(show['glyphs'])
    if request.line_reflow and not whole:
        raise EditError('Para ajustar un campo recortado selecciona su texto completo. Para editar sólo este fragmento desactiva Ajustar el resto de la línea; los vecinos conservarán su posición.')
    array=args[0] if op==b'TJ' else [args[0]]
    position=0
    internal=0.
    for value in array:
        if isinstance(value,(str,bytes)):position+=len(_raw(value))
        elif first<position<last:internal+=float(value)
    tf,tc,tw,tz=state['size'],state['tc'],state['tw'],state['tz']
    def advance(codes,chars):
        return sum(_advance(font,code,char)+1000*tc/tf+(1000*tw/tf if code==32 else 0) for code,char in zip(codes,chars))
    old_advance=advance(original_codes[first:last],text)-internal
    new_advance=advance(new_codes,new_text)
    ink_width=0.
    if new_codes:
        ink_width=(new_advance-1000*tc/tf-(1000*tw/tf if new_codes[-1]==32 else 0))*tf*tz/1000*matrix.a
    if request.anchor=='right':shift=bounds[2]-selected[0].origin[0]-ink_width
    elif request.anchor=='center':shift=(bounds[0]+bounds[2]-ink_width)/2-selected[0].origin[0]
    else:shift=0.
    pre_adjust=-shift/(tf*tz*matrix.a)*1000
    compensation=new_advance-old_advance-pre_adjust
    changed_array=ArrayObject()
    position=0
    inserted=False
    def emit_bytes(value):
        if value:changed_array.append(ByteStringObject(value))
    for value in array:
        if isinstance(value,(str,bytes)):
            for code in _raw(value):
                if position==first and not inserted:
                    if abs(pre_adjust)>1e-10:changed_array.append(FloatObject(pre_adjust))
                    emit_bytes(new_codes)
                    changed_array.append(FloatObject(compensation))
                    inserted=True
                if not first<=position<last:emit_bytes(bytes([code]))
                position+=1
        elif not first<position<last:changed_array.append(value)
    linear=fitz.Matrix(matrix)*page_matrix
    xvector=fitz.Point(1,0)*linear-fitz.Point(0,0)*linear
    cursor=0.
    template=selected[0]
    planned=[]
    for char,code in zip(new_text,new_codes):
        x,y0=template.origin[0]+shift+cursor*xvector.x,template.origin[1]+cursor*xvector.y
        width=_advance(font,code,char)/1000*tf*tz*xvector.x
        top,bottom=template.bbox[1]-template.origin[1],template.bbox[3]-template.origin[1]
        planned.append(replace(template,id=-1,text=char,origin=(x,y0),bbox=(x,y0+top,x+width,y0+bottom)))
        cursor+=(_advance(font,code,char)/1000*tf+tc+(tw if code==32 else 0))*tz
    if request.auto_width:
        actual=union(g.bbox for g in planned) if planned else (bounds[0],bounds[1],bounds[0]+.1,bounds[3])
        area=(actual[0],bounds[1],actual[2]+.025,bounds[1]+height)
    requested_area=fitz.Rect(area)
    clip=state['clip']*page_matrix if state['clip'] is not None else page_bounds
    selected_ids={g.id for g in selected}
    others=[g for g in model.glyphs if g.id not in selected_ids]
    for old in selected:
        if not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(old.bbox)):
            raise EditError('El texto original está parcialmente recortado; no se puede reconstruir su campo con garantías.')
    for g in planned:
        if not (requested_area+(-.035,-.035,.035,.035)).contains(fitz.Rect(g.bbox)) or not page_bounds.contains(fitz.Rect(g.bbox)) or not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(g.bbox)):
            raise EditError('El texto supera el espacio disponible o su recorte. Amplía la anchura del campo dentro de su columna.')
        if any(intersects(g.bbox,n.bbox,.12) for n in others):raise EditError('El texto nuevo se solapa con un vecino.')
    changed_ops=copy.deepcopy(operations)
    changed_ops[operation]=([changed_array],b'TJ')
    with fitz.open(stream=data,filetype='pdf') as doc:
        if planned:
            _safe_selection(doc[request.page],replace(model,issues=[i for i in model.issues if i!=CLIP_ISSUE]),planned)
        xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,_serialize(changed_ops));doc[request.page].set_contents(xref)
        output=full_write(doc)
    after=PdfReader(BytesIO(output),strict=True)
    new_ops=ContentStream(after.pages[request.page].get_contents(),after).operations
    if len(new_ops)!=len(operations):raise EditError('Cambió el número de operadores.')
    for i,((a,o),(b,p)) in enumerate(zip(operations,new_ops)):
        if i!=operation and (o!=p or _signature(a)!=_signature(b)):raise EditError('Cambió un operador ajeno al SHOW.')
    if _signature(reader.pages[request.page]['/Resources']['/Font'][show['resource']])!=_signature(after.pages[request.page]['/Resources']['/Font'][show['resource']]):
        raise EditError('Cambió la fuente.')
    expected=[(g.text,g.origin,g.font,g.size) for g in others+planned]
    report=validate_transition(data,output,request.page,expected,[g.bbox for g in selected+planned])
    report.update(original=text,replacement=new_text,selected_characters=len(selected),new_characters=len(planned),
                  untouched_characters=len(others),operator=operation,resource=show['resource'],xref=show['xref'],
                  tf=tf,tc=tc,tw=tw,tz=tz,compensation_tj=compensation,internal_tj_removed=internal,
                  matrix=list(matrix),clip_pdf=list(state['clip']) if state['clip'] is not None else None,
                  old_bounds=union(g.bbox for g in selected),new_bounds=union(g.bbox for g in planned),
                  cursor_residual=(new_advance-compensation-pre_adjust-old_advance)*tf*tz/1000,
                  source_sha256=hashlib.sha256(data).hexdigest(),font_unchanged=True)
    _assert_typography(output,request.page,others+planned)
    report.update(page=request.page,elapsed_seconds=round(time.perf_counter()-started,3),
                  source_regions=[g.bbox for g in selected],destination_regions=[g.bbox for g in planned],
                  font_resources=[{'resource':show['resource'],'xref':show['xref'],'base_font':str(font.get('/BaseFont',''))}],
                  fonts={str(font.get('/BaseFont','')):'Recurso PDF original '+show['resource']+' sin reincrustar'},
                  font_resources_unchanged=True,operators_preserved=True,
                  clipped_text_mode='Campo de longitud variable; fuente, recorte y cursor posterior conservados.',
                  line_reflow=False,line_reflow_requested=request.line_reflow,
                  layout_scope='Campo completo' if whole else 'Fragmento; vecinos fijos',
                  manual_format={'font':None,'size':None,'color':None})
    return output,report


def _assert_typography(data,page,glyphs):
    """Además de texto y píxeles, exige propiedades idénticas de cada glifo."""
    with fitz.open(stream=data,filetype='pdf') as doc:
        actual=[(chr(c[0]),c[2],s) for s in doc[page].get_texttrace() for c in s['chars']]
    groups={}
    for item in actual:groups.setdefault(item[0],[]).append(item)
    for glyph in glyphs:
        matches=groups.get(glyph.text,[])
        index=next((i for i,(_,origin,s) in enumerate(matches)
                    if all(abs(a-b)<.035 for a,b in zip(origin,glyph.origin)) and
                    s['font']==glyph.font and abs(s['size']-glyph.size)<.001 and
                    s['type']==glyph.mode and tuple(s['color'])==glyph.color and
                    abs(s['opacity']-glyph.opacity)<.001 and
                    all(abs(a-b)<1e-5 for a,b in zip(s['dir'],glyph.direction))),None)
        if index is None:raise EditError('La validación detectó cambios en tipografía, posición o modo de pintura.')
        matches.pop(index)
    if any(groups.values()):raise EditError('La validación detectó glifos añadidos inesperadamente.')
