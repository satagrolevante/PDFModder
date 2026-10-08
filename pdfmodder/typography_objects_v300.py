"""Maintain verified Unicode clusters when native paint occurrences move.

Ownership is supplied by the operator probe. Output correspondence follows
the unchanged paint order, and verifies Unicode, GID, font bytes and origins.
No bounding-box search chooses a glyph or a metadata owner.
"""
from dataclasses import asdict
from hashlib import sha256
import copy
import json

import pymupdf as fitz

from .model import EditError,union
from .typography_v300 import KEY,SCHEMA,_records,_verified_records


def prepare_typography_object_context(data,page):
    from .engine import extract_page
    with fitz.open(stream=data,filetype='pdf') as doc:
        records=_records(doc,page)
        if not records:return dict(records=[],verified=[],model=None)
        model=extract_page(doc,page,data)
        verified=_verified_records(doc,page,model)
        return dict(records=records,verified=verified,model=model)


def native_object_record_issue(data,page,glyph_ids,duplicate=False,context=None):
    if not glyph_ids:return ''
    context=context or prepare_typography_object_context(data,page)
    if not context['records']:return ''
    if len(context['verified'])!=len(context['records']):
        return 'Hay registros tipográficos cuyo propietario no puede verificarse; conserva su posición o vuelve a componer el texto antes de transformarlo.'
    selected=set(glyph_ids)
    for record,actual in context['verified']:
        actual_ids={glyph.id for glyph in actual}
        if not selected.intersection(actual_ids):continue
        if duplicate and (not actual_ids<=selected or record.get('paragraph_tag')):
            return 'Duplica el bloque tipográfico completo para conservar sus rangos Unicode y su identidad de párrafo.'
        by_index={saved['physical_index']:glyph.id for saved,glyph in zip(record['glyphs'],actual)}
        for cluster in record['clusters']:
            members={by_index[index] for index in cluster['physical_indices']}
            if members.intersection(selected) and not members<=selected:
                return 'Transforma juntos los glifos de la ligadura o marca; comparten un único clúster Unicode.'
    return ''


def _box(rect,matrix):
    return tuple(fitz.Rect(rect)*matrix)


def _restyle_runs(record):
    """Split logical styles only at independently verified cluster boundaries."""
    result=[];offset=0
    for original in record.get('runs',[]):
        stop=offset+len(original['text'])
        cuts=sorted({offset,stop}|{max(offset,min(stop,c[key]))
                    for c in record['clusters'] for key in ('start','end')})
        for begin,end in zip(cuts,cuts[1:]):
            if begin==end:continue
            run=dict(original,text=record['text'][begin:end])
            clusters=[c for c in record['clusters'] if c['start']<end and c['end']>begin]
            physical=[record['glyphs'][i] for c in clusters for i in c['physical_indices']]
            visible=[g for g in physical if not g.get('auxiliary')]
            if visible:
                if max(g['size'] for g in visible)-min(g['size'] for g in visible)>.002:
                    raise EditError('El clúster transformado mezcla escalas que necesitan recomposición tipográfica.')
                colours={tuple(g['color']) for g in visible}
                if len(colours)>1:
                    raise EditError('El clúster transformado mezcla colores que necesitan recomposición tipográfica.')
                run['size']=visible[0]['size'];run['color']=visible[0]['color']
            if result and {k:v for k,v in result[-1].items() if k!='text'}=={k:v for k,v in run.items() if k!='text'}:
                result[-1]['text']+=run['text']
            else:result.append(run)
        offset=stop
    record['runs']=result


def update_native_object_records_v300(data,output,page,glyph_ids,transform,duplicate=False,context=None):
    context=context or prepare_typography_object_context(data,page)
    selected=set(glyph_ids)
    affected=[(record,actual) for record,actual in context['verified']
              if selected.intersection(g.id for g in actual)]
    if not affected:return output,dict(updated_records=0,cloned_records=0,verified=True)
    issue=native_object_record_issue(data,page,glyph_ids,duplicate,context)
    if issue:raise EditError(issue)
    matrix=fitz.Matrix(*transform)
    before_model=context['model']
    source_ids=sorted(selected)
    if duplicate and source_ids!=list(range(source_ids[0],source_ids[-1]+1)):
        raise EditError('La aparición tipográfica no ocupa un rango de pintura continuo que permita verificar su copia.')
    amount=len(source_ids) if duplicate else 0
    low,high=(source_ids[0],source_ids[-1]) if source_ids else (0,-1)
    from .engine import extract_page
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        source=[(span,ch) for span in before[page].get_texttrace() for ch in span['chars']]
        target=[(span,ch) for span in after[page].get_texttrace() for ch in span['chars']]
        if len(target)!=len(source)+amount:
            raise EditError('La transformación tipográfica no conserva la cantidad esperada de glifos reales.')
        after_model=extract_page(after,page,output)
        def target_id(index,copying=False):
            if copying:return high+1+(index-low)
            return index+(amount if duplicate and index>high else 0)
        # An affine wrapper leaves every original glyph's paint order intact.
        # Check every glyph, including neighbours without private metadata.
        for index,(span,ch) in enumerate(source):
            mappings=[(target_id(index),matrix if index in selected and not duplicate else fitz.Identity)]
            if duplicate and index in selected:mappings.append((target_id(index,True),matrix))
            for index_after,current in mappings:
                actual_span,actual=target[index_after]
                expected=fitz.Point(ch[2])*current
                if (ch[0]!=actual[0] or ch[1]!=actual[1] or span['font']!=actual_span['font']
                        or max(abs(a-b) for a,b in zip(expected,actual[2]))>.035):
                    raise EditError('La correspondencia por operador no confirma Unicode, GID, fuente y posición del resultado tipográfico.')
        font_hashes={}
        def font_hash(glyph):
            if glyph.font_xref:
                if glyph.font_xref not in font_hashes:
                    font_hashes[glyph.font_xref]=sha256(after.extract_font(glyph.font_xref)[3]).hexdigest()
                return font_hashes[glyph.font_xref]
            candidates=[entry[0] for entry in after[page].get_fonts() if entry[3]==glyph.font]
            hashes={sha256(after.extract_font(xref)[3]).hexdigest() for xref in candidates}
            return next(iter(hashes)) if len(hashes)==1 else None
        def changed_record(record,actual,copying=False):
            changed=copy.deepcopy(record)
            actual_by_index={saved['physical_index']:glyph for saved,glyph in zip(record['glyphs'],actual)}
            for saved in changed['glyphs']:
                old=actual_by_index[saved['physical_index']]
                index_after=target_id(old.id,copying)
                now=after_model.glyphs[index_after]
                raw_span,raw=target[index_after]
                if saved.get('font_sha256') and font_hash(now)!=saved['font_sha256']:
                    raise EditError('El programa de fuente del glifo transformado no coincide con su huella verificada.')
                saved.update(asdict(now),gid=raw[1],physical_index=saved['physical_index'])
            for cluster in changed['clusters']:
                indices=cluster['physical_indices']
                members=[changed['glyphs'][i] for i in indices]
                moved=copying or (not duplicate and all(actual_by_index[i].id in selected for i in indices))
                bounds=[g['bbox'] for g in members]
                bounds.append(_box(cluster['bbox'],matrix) if moved else cluster['bbox'])
                cluster['bbox']=union(bounds)
                if moved:
                    for key in ('origin','end_origin'):
                        if key in cluster:cluster[key]=tuple(fitz.Point(cluster[key])*matrix)
                if copying:cluster['line']=members[0]['line']
            all_moved=copying or (not duplicate and all(g.id in selected for g in actual))
            changed['rect']=union([_box(record['rect'],matrix) if all_moved else record['rect']]
                                  +[c['bbox'] for c in changed['clusters']])
            if copying and changed['glyphs']:changed['block']=changed['glyphs'][0]['block']
            _restyle_runs(changed)
            return changed
        records=[];clones=[]
        for record in context['records']:
            # JSON records and verified records share their value rather than
            # object identity after extraction; use their exact equality.
            actual=next((actual for owned,actual in affected if owned==record),None)
            if actual is None:records.append(copy.deepcopy(record));continue
            records.append(changed_record(record,actual))
            if duplicate:
                clone=changed_record(record,actual,True)
                clone['paragraph_id']='O'+sha256(output+str(len(clones)).encode()).hexdigest()[:20]
                clone['paragraph_text']=clone['text'];clone['paragraph_offset']=0
                clones.append(clone)
        records.extend(clones)
        after.xref_set_key(after[page].xref,KEY,fitz.get_pdf_str(json.dumps(
            dict(schema=SCHEMA,records=records),ensure_ascii=True)))
        result=after.tobytes(garbage=0,deflate=False,no_new_id=True)
    with fitz.open(stream=result,filetype='pdf') as doc:
        final=extract_page(doc,page,result)
        verified=_verified_records(doc,page,final)
        if len(verified)!=len(records):
            raise EditError('No se pudieron verificar todos los clústeres tipográficos al reabrir el resultado.')
    return result,dict(updated_records=len(affected),cloned_records=len(clones),
                       verified=True,ownership='operator-paint-order+Unicode+GID+fontSHA256')
