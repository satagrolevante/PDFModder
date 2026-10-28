"""Small native text streams; original page artwork remains byte-identical.

Ownership metadata only locates a candidate stream. Actual source glyphs,
stream syntax and the complete final PDF are independently verified.
"""
from dataclasses import replace
from io import BytesIO
import copy
import hashlib
import json
import time

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream, NameObject

from .draft_control_v305 import checkpoint
from .model import EditError,Glyph,intersects,union


_OWNED='native_stream_v316'


def _digest(content):return hashlib.sha256(content).hexdigest()


def _new_stream(doc,content):
    xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
    doc.update_stream(xref,content)
    return xref


def _contents(doc,page,refs):
    doc.xref_set_key(doc[page].xref,'Contents','['+' '.join(f'{x} 0 R' for x in refs)+']')


def _neutral_entry(doc,page,target):
    """A standalone probe is valid only with the original default entry state."""
    from .analysis_reuse_v315 import stream_scope_events_v316
    reader=PdfReader(BytesIO(doc.tobytes(garbage=0,no_new_id=True)),strict=True)
    dirty=False;stack=[];pending=False;marked=0;inside=False
    for ref in doc[page].get_contents():
        if ref==target:return not dirty and not pending and marked==0 and not inside
        events=stream_scope_events_v316(doc.xref_stream(ref),reader)
        if events is None:return False
        for operator,value in events:
            if operator==b'q':stack.append(dirty)
            elif operator==b'Q':
                if not stack:return False
                dirty=stack.pop()
            elif operator in (b'cm',b'gs',b'Tr'):dirty=True
            elif operator in (b'W',b'W*'):pending=True
            elif operator in (b'n',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'):
                if pending:dirty=True
                pending=False
            elif operator in (b'BDC',b'BMC'):marked+=1
            elif operator==b'EMC':
                marked-=1
                if marked<0:return False
            elif operator==b'BT':
                if inside:return False
                inside=True
            elif operator==b'ET':
                if not inside:return False
                inside=False
    return False


def _supported(request):
    from .fonts import BASE14
    return all(run.get('font_file') or run.get('font_name') in BASE14 for run in request.runs)


def _graft_text(doc,page,layer_data):
    """Graft only used fonts/content, collecting the disposable page afterward."""
    from .native_font_extension import _attach_page_font
    from .clipping import _serialize,_signature
    reader=PdfReader(BytesIO(layer_data),strict=True)
    operations=ContentStream(reader.pages[0].get_contents(),reader).operations
    used={str(args[0]) for args,op in operations if op==b'Tf'}
    original=PdfReader(BytesIO(doc.tobytes(garbage=0,no_new_id=True)),strict=True)
    old_fonts=original.pages[page].get('/Resources',{}).get('/Font',{})
    old_fonts=old_fonts.get_object() if hasattr(old_fonts,'get_object') else old_fonts
    layer_fonts=reader.pages[0]['/Resources']['/Font']
    with fitz.open(stream=layer_data,filetype='pdf') as layer:
        doc.insert_pdf(layer,from_page=0,to_page=0,links=False,annots=False,widgets=False)
    temporary=len(doc)-1
    rename={}
    for resource in sorted(used):
        checkpoint()
        if resource in old_fonts and _signature(old_fonts[resource])==_signature(layer_fonts[resource]):
            rename[resource]=resource
            continue
        kind,value=doc.xref_get_key(doc[temporary].xref,'Resources/Font/'+resource.lstrip('/'))
        if kind!='xref':raise EditError('No se pudo aislar la fuente del texto añadido.')
        rename[resource]=_attach_page_font(doc,page,int(value.split()[0]))
    for args,op in operations:
        if op==b'Tf':args[0]=NameObject(rename[str(args[0])])
    doc.delete_page(temporary)
    return _serialize(operations),rename


def _blank_layer(source,page):
    with fitz.open() as layer:
        target=layer.new_page(width=source[page].mediabox.width,height=source[page].mediabox.height)
        target.set_mediabox(source[page].mediabox)
        target.set_cropbox(source[page].cropbox)
        target.set_rotation(source[page].rotation)
        return layer.tobytes(no_new_id=True)


def _compose_layer(blank,request,resolver):
    from .richtext import _edit_rich_pdf
    from .engine import extract_page
    rect=request.rect
    with fitz.open(stream=blank,filetype='pdf') as layer:
        layer[0].insert_text((rect[0],rect[1]+10),'|',fontsize=8,fontname='helv')
        anchored=layer.tobytes(garbage=0,no_new_id=True)
        model=extract_page(layer,0)
        ids=[g.id for g in model.glyphs]
    return _edit_rich_pdf(anchored,replace(request,page=0,ids=ids,revision=None),resolver,compose_only=True)


def try_add_owned_text_v316(data,request,resolver):
    """Return None for native/copied faces requiring the original compositor."""
    if not _supported(request):return None
    from .engine import extract_page,_safe_selection
    from .richtext import (_read_metadata,_META_KEY,_write_rich_transaction,_validate,
                           _assert_typography,_finite)
    from .validation import document_issues,assert_graphics_scopes_v316
    from .media import _isolate_existing_content
    started=time.perf_counter()
    if not request.rect or len(request.rect)!=4:
        raise EditError('Define el cuadro donde quieres añadir el texto.')
    rect=tuple(_finite(v,'Posición') for v in request.rect)
    with fitz.open(stream=data,filetype='pdf') as source:
        issues=document_issues(data,source,operation='content')
        if issues:raise EditError('\n'.join(issues))
        model=extract_page(source,request.page)
        assert_graphics_scopes_v316(data,request.page)
        blank=_blank_layer(source,request.page)
        records=_read_metadata(source,request.page)
    layer,report=_compose_layer(blank,replace(request,rect=rect),resolver)
    planned=[Glyph(**g) for g in report['glyphs']]
    overlaps={n.id for g in planned for n in model.glyphs if intersects(g.bbox,n.bbox,.12)}
    if overlaps and not request.allow_overlap:
        raise EditError('El texto se solapa con caracteres vecinos. Amplía o mueve el cuadro, o permite el solapamiento.')
    with fitz.open(stream=layer,filetype='pdf') as scratch:
        added=copy.deepcopy(_read_metadata(scratch,0)[-1])
    with fitz.open(stream=data,filetype='pdf') as doc:
        if planned:_safe_selection(doc[request.page],model,planned,preserve_paint_order=True)
        content,rename=_graft_text(doc,request.page,layer)
        _isolate_existing_content(doc,doc[request.page])
        refs=doc[request.page].get_contents()
        _contents(doc,request.page,[*refs,_new_stream(doc,content)])
        added[_OWNED]=dict(sha256=_digest(content))
        doc.xref_set_key(doc[request.page].xref,_META_KEY,
            fitz.get_pdf_str(json.dumps([*records,added],ensure_ascii=True)))
        output=_write_rich_transaction(doc)
    _assert_typography(output,request.page,model.glyphs+planned)
    checked=_validate(data,output,request.page,model.glyphs+planned,planned,
                       [],added.get('underlines',[]),None)
    report.update(checked)
    _remap_font_evidence(report,rename)
    report.update(page=request.page,source_regions=[],original='',added_text=True,
                  native_stream_v316=True,elapsed_seconds=round(time.perf_counter()-started,3),
                  overlap_neighbor_count=len(overlaps))
    if overlaps:report['warning']='Solapamiento permitido: el texto vecino conserva su contenido y posición.'
    checkpoint()
    return output,report


def _remap_font_evidence(report,rename):
    if isinstance(report.get('fonts'),dict):
        report['fonts']={rename.get(name,name):dict(value,resource=rename.get(name,name))
                         if isinstance(value,dict) else value
                         for name,value in report['fonts'].items()}


def _isolated_layer(data,page,model,ids):
    """Find one exact owned stream covering the selection, including fragments."""
    from .richtext import _read_metadata,_match,_META_KEY
    with fitz.open(stream=data,filetype='pdf') as doc:
        if (doc.is_form_pdf or any(doc[page].annots() or []) or doc[page].get_links()
                or doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0]!='null'):
            return None
        records=_read_metadata(doc,page)
        groups={}
        for index,record in enumerate(records):
            marker=record.get(_OWNED,{})
            if isinstance(marker,dict) and isinstance(marker.get('sha256'),str):
                groups.setdefault(marker['sha256'],[]).append(index)
        chosen=set(ids)
        if not chosen or len(model.selected(ids))!=len(chosen):return None
        for digest,indices in groups.items():
            refs=[ref for ref in doc[page].get_contents() if _digest(doc.xref_stream(ref))==digest]
            if len(refs)!=1:continue
            if not _neutral_entry(doc,page,refs[0]):return None
            members=[];combined=dict(glyphs=[],underlines=[]);offset=0
            valid=True
            for index in indices:
                record=records[index]
                for saved in record.get('glyphs',[]):
                    matching=[g for g in model.glyphs if _match(g,saved)]
                    if len(matching)!=1 or matching[0] in members:
                        valid=False;break
                    members.append(matching[0])
                    combined['glyphs'].append(dict(saved,index=saved['index']+offset))
                combined['underlines'].extend(dict(item,index=item['index']+offset)
                                              for item in record.get('underlines',[]))
                offset+=1+max((g['index'] for g in record.get('glyphs',[])),default=0)
            if not valid or not chosen<={g.id for g in members}:continue
            if not _verify_owned_source(doc,page,refs[0],members,combined):
                raise EditError('No se pudo verificar la independencia del texto añadido y sus subrayados.')
            scratch_records=[{key:copy.deepcopy(value) for key,value in records[index].items()
                              if key!=_OWNED} for index in indices]
            doc[page].set_contents(refs[0])
            doc.xref_set_key(doc[page].xref,_META_KEY,fitz.get_pdf_str(json.dumps(scratch_records,ensure_ascii=True)))
            doc.select([page])
            scratch=doc.tobytes(garbage=2,no_new_id=True)
            from .engine import extract_page
            local=extract_page(doc,0)
            mapping={}
            for glyph in local.glyphs:
                matches=[g for g in members if g.text==glyph.text
                         and all(abs(a-b)<.025 for a,b in zip(g.origin,glyph.origin))]
                if len(matches)!=1:return None
                mapping[glyph.id]=matches[0].id
            local_ids=[identifier for identifier,original in mapping.items() if original in chosen]
            return dict(data=scratch,model=local,ids=local_ids,mapping=mapping,
                        records=records,indices=indices,ref=refs[0],members=members)
    return None


def try_edit_owned_text_v316(data,request,resolver):
    from .typography_v300 import requires_shaping
    if requires_shaping(request.runs):return None
    from .engine import extract_page,_safe_selection
    from .validation import document_issues
    from .richtext import (_edit_rich_pdf,_read_metadata,_META_KEY,_write_rich_transaction,
                           _validate,_assert_typography)
    started=time.perf_counter()
    with fitz.open(stream=data,filetype='pdf') as doc:
        if doc.xref_get_key(doc[request.page].xref,'PDFModderRichText')[0]!='string':return None
        issues=document_issues(data,doc,operation='content')
        if issues:raise EditError('\n'.join(issues))
        model=extract_page(doc,request.page)
    context=_isolated_layer(data,request.page,model,request.ids)
    if context is None:return None
    selected=model.selected(request.ids)
    from .textlayout import _check_visibility
    _check_visibility(selected)
    local=replace(request,page=0,ids=context['ids'],revision=None)
    layer,report=_edit_rich_pdf(context['data'],local,resolver,compose_only=True)
    with fitz.open(stream=layer,filetype='pdf') as scratch:
        updated=_read_metadata(scratch,0)
    planned=[Glyph(**g) for g in report['glyphs']]
    others=[g for g in model.glyphs if g.id not in set(request.ids)]
    overlaps={n.id for g in planned for n in others if intersects(g.bbox,n.bbox,.12)}
    if overlaps and not request.allow_overlap:
        # Keep existing metric intersections only; the ordinary planner knows
        # which of those were already present before the requested edit.
        from .richtext import _new_neighbor_overlap
        if any(_new_neighbor_overlap(g,n,selected) for g in planned for n in others):
            raise EditError('El texto se solapa con caracteres vecinos. Amplía o mueve el cuadro, o permite el solapamiento.')
    records=context['records']
    old_underlines=[item for index in context['indices'] for item in records[index].get('underlines',[])]
    new_underlines=[item for record in updated for item in record.get('underlines',[])]
    with fitz.open(stream=data,filetype='pdf') as doc:
        if selected:_safe_selection(doc[request.page],model,selected,preserve_paint_order=True)
        if planned:_safe_selection(doc[request.page],model,planned,preserve_paint_order=True)
        content,rename=_graft_text(doc,request.page,layer)
        doc.update_stream(context['ref'],content)
        for record in updated:record[_OWNED]=dict(sha256=_digest(content))
        records=[record for index,record in enumerate(records) if index not in context['indices']]+updated
        doc.xref_set_key(doc[request.page].xref,_META_KEY,fitz.get_pdf_str(json.dumps(records,ensure_ascii=True)))
        from .richtext import _drop_affected_groups
        removed=_drop_affected_groups(doc,request.page,selected)
        output=_write_rich_transaction(doc)
    _assert_typography(output,request.page,others+planned)
    def same(a,b):
        return (len(a.get('rect',()))==len(b.get('rect',()))==4
                and all(abs(x-y)<.001 for x,y in zip(a['rect'],b['rect']))
                and a.get('color')==b.get('color'))
    decorations=[a for a in old_underlines if not any(same(a,b) for b in new_underlines)]
    decorations.extend(b for b in new_underlines if not any(same(a,b) for a in old_underlines))
    checked=_validate(data,output,request.page,others+planned,selected+planned,
                      old_underlines,new_underlines,None,pixel_underlines=decorations)
    report.update(checked);_remap_font_evidence(report,rename)
    report.update(page=request.page,native_stream_v316=True,removed_groups=removed,
                  source_regions=[g.bbox for g in selected],overlap_neighbor_count=len(overlaps),
                  elapsed_seconds=round(time.perf_counter()-started,3))
    if overlaps:report['warning']='Solapamiento permitido: el texto vecino conserva su contenido y posición.'
    return output,report


def try_selection_payload_v316(data,page,ids,resolver=None,*,page_model=None):
    from .richtext import _read_metadata,_selection_payload
    from .engine import extract_page
    with fitz.open(stream=data,filetype='pdf') as doc:
        if not any(_OWNED in item for item in _read_metadata(doc,page)):return None
        model=(page_model if page_model is not None and page_model.number==page
               and page_model.revision==_digest(data) else extract_page(doc,page))
        fonts={str(item[4]):item[0] for item in doc[page].get_fonts()}
    context=_isolated_layer(data,page,model,ids)
    if context is None:return None
    payload=_selection_payload(context['data'],0,context['ids'],resolver)
    payload.update(page=page,ids=list(ids),revision=_digest(data),native_stream_v316=True)
    xrefs={}
    for run in payload.get('runs',[]):
        resource=str(run.get('font_resource','')).lstrip('/')
        if resource in fonts:
            xrefs[run.get('font_xref')]=fonts[resource]
            run['font_xref']=fonts[resource]
    for preview in payload.get('font_previews',[]):
        if preview.get('font_xref') in xrefs:
            preview['font_xref']=xrefs[preview['font_xref']]
    for caret in payload.get('carets',[]):
        if 'id' in caret:caret['id']=context['mapping'].get(caret['id'],caret['id'])
    return payload


def _move_isolated_layer(data,request,model,context):
    from .richtext import (_move_rich_pdf,_read_metadata,_write_rich_transaction,
                           _move_rich_metadata,_META_KEY,_assert_typography,_validate)
    selected=model.selected(request.ids)
    def shifted(rect):
        return tuple(v+(request.dx if i%2==0 else request.dy) for i,v in enumerate(rect))
    planned=[replace(g,origin=shifted(g.origin),bbox=shifted(g.bbox),trace_bbox=shifted(g.trace_bbox)) for g in selected]
    others=[g for g in model.glyphs if g.id not in set(request.ids)]
    overlaps={n.id for g in planned for n in others if intersects(g.bbox,n.bbox,.12)}
    if overlaps and not request.allow_overlap:
        raise EditError('El texto movido se solapa con un vecino. Elige otra posición.')
    local=replace(request,page=0,ids=context['ids'],revision=None)
    layer,report=_move_rich_pdf(context['data'],local)
    with fitz.open(stream=layer,filetype='pdf') as doc:
        updated=_read_metadata(doc,0)
    with fitz.open(stream=data,filetype='pdf') as doc:
        content,rename=_graft_text(doc,request.page,layer)
        doc.update_stream(context['ref'],content)
        records=context['records']
        old_underlines=copy.deepcopy([item for index in context['indices']
                                      for item in records[index].get('underlines',[])])
        _move_rich_metadata(doc,request,model,records)
        for record in updated:record[_OWNED]=dict(sha256=_digest(content))
        records=[record for index,record in enumerate(records) if index not in context['indices']]+updated
        doc.xref_set_key(doc[request.page].xref,_META_KEY,fitz.get_pdf_str(json.dumps(records,ensure_ascii=True)))
        output=_write_rich_transaction(doc)
    _assert_typography(output,request.page,others+planned)
    new_underlines=[item for record in updated for item in record.get('underlines',[])]
    checked=_validate(data,output,request.page,others+planned,selected+planned,
                      old_underlines,new_underlines,None)
    report.update(checked);_remap_font_evidence(report,rename)
    report.update(page=request.page,rich_text_move=True,native_stream_v316=True,
                  source_regions=[g.bbox for g in selected],destination_regions=[g.bbox for g in planned],
                  old_bounds=union(g.bbox for g in selected),new_bounds=union(g.bbox for g in planned),
                  overlap_count=len(overlaps))
    if overlaps:report['warning']='Solapamiento permitido: el texto vecino conserva su contenido y posición.'
    return output,report


def _owned_selection(doc,page,model,ids):
    from .richtext import _read_metadata,_match
    if (doc.is_form_pdf or any(doc[page].annots() or [])
            or doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0]!='null'):
        return None
    selected=model.selected(ids)
    if not selected or len(selected)!=len(set(ids)):return None
    records=_read_metadata(doc,page)
    for number,record in enumerate(records):
        marker=record.get(_OWNED,{})
        glyphs=record.get('glyphs',[])
        if (not isinstance(marker,dict) or not isinstance(marker.get('sha256'),str)
                or len(glyphs)!=len(selected)
                or not all(any(_match(g,saved) for g in selected) for saved in glyphs)):
            continue
        if sum(other.get(_OWNED,{}).get('sha256')==marker['sha256'] for other in records)!=1:
            # Partial edits can split logical records within the same stream.
            # Moving one of them needs the small native substring compositor.
            continue
        refs=doc[page].get_contents()
        matches=[ref for ref in refs if _digest(doc.xref_stream(ref))==marker['sha256']]
        if len(matches)!=1:continue
        if not _neutral_entry(doc,page,matches[0]):return None
        return records,number,matches[0],selected
    return None


def _verify_owned_source(doc,page,ref,selected,record):
    """Metadata cannot bless extra painting or turn artwork into owned text."""
    from .richtext import _assert_typography
    raw=doc.xref_stream(ref)
    if len(raw)>512*1024:return False
    from .analysis_reuse_v315 import stream_operations_v316
    operations=stream_operations_v316(raw)
    allowed={b'q',b'Q',b'cm',b'BT',b'ET',b'Tf',b'Tm',b'Td',b'TD',b'T*',
             b'Tj',b'TJ',b'Tc',b'Tw',b'Tz',b'TL',b'Tr',b'Ts',b'rg',b'RG',b'g',b'G',
             b'k',b'K',b're',b'f'}
    if any(op not in allowed for _,op in operations):return False
    with fitz.open(stream=doc.tobytes(garbage=0,no_new_id=True),filetype='pdf') as probe:
        probe[page].set_contents(ref)
        drawings=probe[page].get_drawings()
        from .richtext import _match
        expected=[]
        for saved in record.get('glyphs',[]):
            if not saved.get('underline'):continue
            matches=[g for g in selected if _match(g,saved)]
            if len(matches)!=1:return False
            glyph=matches[0];thickness=max(.35,glyph.size/18)
            rect=(glyph.origin[0],glyph.origin[1]+glyph.size*.12,glyph.bbox[2],
                  glyph.origin[1]+glyph.size*.12+thickness)
            if rect[2]>rect[0]:expected.append((saved['index'],rect,glyph.color))
        declared=record.get('underlines',[])
        if len(drawings)!=len(expected) or len(declared)!=len(expected):return False
        for index,rect,color in expected:
            items=[item for item in declared if item.get('index')==index
                   and len(item.get('rect',()))==4
                   and all(abs(a-b)<.035 for a,b in zip(item.get('rect',()),rect))]
            matches=[drawing for drawing in drawings if drawing.get('type')=='f'
                     and drawing.get('fill') is not None
                     and all(abs(a-b)<.001 for a,b in zip(drawing['fill'],color))
                     and all(abs(a-b)<.035 for a,b in zip(drawing['rect'],rect))]
            if len(items)!=1 or len(matches)!=1:return False
            drawings.remove(matches[0])
        isolated=probe.tobytes(garbage=0,no_new_id=True)
    _assert_typography(isolated,page,selected)
    return True


def try_move_owned_text_v316(data,request):
    """Translate a complete independently checked text layer in one write."""
    from .engine import extract_page,_safe_selection
    from .richtext import (_write_rich_transaction,_validate,_META_KEY,
                           _move_rich_metadata,_assert_typography)
    from .native_layout import _number
    from .clipping import _serialize
    from .textlayout import _check_visibility
    import math
    started=time.perf_counter()
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (request.dx,request.dy)):
        raise EditError('El desplazamiento debe contener coordenadas finitas.')
    with fitz.open(stream=data,filetype='pdf') as doc:
        # The public mover has already checked original permissions/revision.
        if doc.xref_get_key(doc[request.page].xref,'PDFModderRichText')[0]!='string':return None
        model=extract_page(doc,request.page)
        owned=_owned_selection(doc,request.page,model,request.ids)
        if owned is None:
            context=_isolated_layer(data,request.page,model,request.ids)
            return _move_isolated_layer(data,request,model,context) if context is not None else None
        records,number,ref,selected=owned
        if not _verify_owned_source(doc,request.page,ref,selected,records[number]):
            raise EditError('No se pudo verificar la independencia del texto añadido y sus subrayados.')
        _check_visibility(selected)
        dx,dy=request.dx,request.dy
        def shifted(rect):return tuple(v+(dx if i%2==0 else dy) for i,v in enumerate(rect))
        planned=[replace(g,origin=shifted(g.origin),bbox=shifted(g.bbox),
                         trace_bbox=shifted(g.trace_bbox)) for g in selected]
        bounds=fitz.Rect(0,0,doc[request.page].cropbox.width,doc[request.page].cropbox.height)
        if any(not bounds.contains(fitz.Rect(g.bbox)) for g in planned):
            raise EditError('La posición de destino queda fuera de la página.')
        others=[g for g in model.glyphs if g.id not in set(request.ids)]
        overlaps={n.id for g in planned for n in others if intersects(g.bbox,n.bbox,.12)}
        if overlaps and not request.allow_overlap:
            raise EditError('El texto movido se solapa con un vecino. Elige otra posición.')
        _safe_selection(doc[request.page],model,selected,preserve_paint_order=True)
        _safe_selection(doc[request.page],model,planned,preserve_paint_order=True)
        old_underlines=copy.deepcopy(records[number].get('underlines',[]))
        rotation=doc[request.page].rotation
        doc[request.page].set_rotation(0)
        matrix=doc[request.page].transformation_matrix
        doc[request.page].set_rotation(rotation)
        inverse=~matrix
        delta=fitz.Point(dx,dy)*inverse-fitz.Point(0,0)*inverse
        prefix=_serialize([([],b'q'),([_number(v) for v in (1,0,0,1,delta.x,delta.y)],b'cm')])
        content=prefix+doc.xref_stream(ref)+b'\nQ\n'
        doc.update_stream(ref,content)
        _move_rich_metadata(doc,request,model,records)
        record=records[number]
        for item in record.get('underlines',[]):
            item['rect']=shifted(item['rect'])
            item['start']+=2
        record[_OWNED]=dict(sha256=_digest(content))
        doc.xref_set_key(doc[request.page].xref,_META_KEY,fitz.get_pdf_str(json.dumps(records,ensure_ascii=True)))
        output=_write_rich_transaction(doc)
    _assert_typography(output,request.page,others+planned)
    report=_validate(data,output,request.page,others+planned,selected+planned,
                     old_underlines,record.get('underlines',[]),None)
    report.update(page=request.page,rich_text_move=True,native_stream_v316=True,
        underlines_moved=len(old_underlines),source_regions=[g.bbox for g in selected],
        destination_regions=[g.bbox for g in planned],old_bounds=union(g.bbox for g in selected),
        new_bounds=union(g.bbox for g in planned),overlap_count=len(overlaps),
        elapsed_seconds=round(time.perf_counter()-started,3))
    if overlaps:report['warning']='Solapamiento permitido: el texto vecino conserva su contenido y posición.'
    checkpoint()
    return output,report


def annotate_owned_resources_v316(data,page,model):
    """Bind fonts by probing small streams when they account for every glyph."""
    from .richtext import _read_metadata,_match,_assert_typography
    from .engine import extract_page
    from .clipping import operator_glyph_map
    if not model.glyphs or len(model.glyphs)>30_000:return None
    with fitz.open(stream=data,filetype='pdf') as doc:
        if doc.is_form_pdf or any(doc[page].annots() or []):return None
        records=_read_metadata(doc,page)
        if not any(_OWNED in item for item in records):return None
        fonts={str(row[4]):row[0] for row in doc[page].get_fonts()}
        groups={}
        for record in records:
            digest=record.get(_OWNED,{}).get('sha256')
            if digest:groups.setdefault(digest,[]).append(record)
        restored={}
        for group in groups.values():
            selected=[]
            for saved in (saved for record in group for saved in record.get('glyphs',[])):
                candidates=[g for g in model.glyphs if g.id not in restored and _match(g,saved)]
                if len(candidates)!=1:return None
                selected.append(candidates[0])
            if not selected:continue
            context=_isolated_layer(data,page,model,[g.id for g in selected])
            if context is None:return None
            _,_,_,mapping=operator_glyph_map(context['data'],0,context['model'])
            by_id={g.id:g for g in selected}
            for identifier,actual_id in context['mapping'].items():
                if identifier not in mapping:return None
                resource=mapping[identifier]['font_resource']
                xref=fonts.get(resource.lstrip('/'))
                if xref is None:return None
                restored[actual_id]=replace(by_id[actual_id],font_xref=xref,font_resource=resource)
        if len(restored)!=len(model.glyphs):return None
    return replace(model,glyphs=[restored[g.id] for g in model.glyphs])
