"""Selection-level capability feedback, with original resource evidence.

Preflight never commits content. A font available by Unicode is different from
a usable original PDF code; neither name match nor preflight replaces final
content/appearance validation by the compositor.
"""
from hashlib import sha256
import unicodedata
import pymupdf as fitz

from .fonts import FontResolver, FontError
from .model import EditRequest, EditError


def preflight_text(data, page, ids, new_text=None, resolver=None):
    """Return JSON-safe status/actions/font evidence for a selected text.

    Use on selection or when requesting an edit, rather than on each keypress.
    Forms are prepared in a discarded copy. Native glyph availability is
    probed in its actual resource; any new CFF/TTF code uses the isolated font
    preparation path. A successful font check promises only these characters.
    """
    from .engine import extract_page
    from .validation import document_issues
    from .form_instances_v200 import isolate_selected_forms
    from .clipping import operator_glyph_map
    from .native_codes import verified_catalog
    from .richtext import _catalog
    from .native_font_extension import prepare_native_font

    result={'status':'blocked','label':'No editable','reasons':[],'actions':[],
            'fonts':[],'revision':sha256(data).hexdigest(),'scope':'selección y caracteres solicitados',
            'requires_final_validation':True,'normalized_text':None,'form_isolation':None}
    resolver=resolver or FontResolver()
    text=unicodedata.normalize('NFC',new_text) if new_text is not None else None
    result['normalized_text']=text
    result['unicode_normalization']=bool(new_text is not None and text!=new_text)
    try:
        with fitz.open(stream=data,filetype='pdf') as doc:
            problems=document_issues(data,doc,operation='content')
            if problems:
                result['reasons']=problems
                result['actions']=['Abrir una copia con permisos legítimos o conservar el documento firmado.']
                return result
        isolated=isolate_selected_forms(data,EditRequest(page,tuple(ids)))
        local=isolated[0] if isolated is not None else data
        if isolated is not None:
            result['form_isolation']=isolated[2]
        with fitz.open(stream=local,filetype='pdf') as doc:
            model=extract_page(doc,page,local)
            selected=model.selected(ids)
            if not selected or len(selected)!=len(set(ids)):
                raise EditError('Selecciona texto de la revisión actual.')
            if model.issues:
                from .clipping import CLIP_ISSUE
                problems=[issue for issue in model.issues if issue!=CLIP_ISSUE]
                if problems:
                    result['reasons']=problems
                    return result
            if any(g.direction!=(1.,0.) or not g.reliable for g in selected):
                raise EditError('La dirección o codificación del texto necesita una ruta específica todavía no compatible.')
            if any(g.mode==3 for g in selected):
                result.update(status='conditional',label='Capa OCR: elegir modo explícitamente',
                              actions=['Activar Corregir capa OCR buscable o editar la apariencia visible.'])
                return result
            _,operations,shows,mapping=operator_glyph_map(local,page,model)
            sources={show['operation']:show for show in shows}
            grouped={}
            for glyph in selected:
                if glyph.id not in mapping:
                    raise EditError('No se identificó un operador de fuente para esta selección.')
                show=sources[mapping[glyph.id]['operation']]
                grouped.setdefault((show['xref'],show['resource']),[]).append(glyph)
            for (xref,resource),glyphs in grouped.items():
                needed=(text if len(grouped)==1 and text is not None else ''.join(g.text for g in glyphs)).replace('\r','').replace('\n','').replace('\u2028','').replace('\t','')
                show=next(s for s in shows if s['xref']==xref and s['resource']==resource)
                evidence=resolver.inspect_selection(doc,page,glyphs[0].font,needed,font_xref=xref,
                                                    resource=resource,include_local=False)
                codes=verified_catalog(local,page,show,_catalog(shows,operations,resource),set(needed))
                missing=sorted({char for char in needed if len(codes.get(char,set()))!=1})
                evidence['requested_text']=needed
                evidence['native_missing_characters']=missing
                evidence['availability']='original_codes_verified' if not missing else 'requires_new_codes'
                if missing:
                    try:
                        extension=prepare_native_font(local,page,show,needed,resolver=resolver)
                        evidence.update(availability='new_codes_verified',extension_evidence=extension.evidence,
                                        native_missing_characters=[])
                    except FontError as exc:
                        evidence['availability']='font_required'
                        evidence['detail']=str(exc)
                        result['reasons'].append(str(exc))
                        result['actions'].append('Importar la variante completa o elegir una fuente explícitamente.')
                result['fonts'].append(evidence)
            if result['reasons']:
                result.update(status='conditional',label='Necesita una fuente o caracteres adicionales')
            else:
                result.update(status='available',label='Editable con los recursos verificados',
                              actions=['Editar y revisar la previsualización antes de aceptar.'])
            if len(grouped)>1 and text is not None:
                result.setdefault('warnings',[]).append('Selección con varias fuentes: escribir mediante el editor por fragmentos para conservar cada estilo.')
    except (EditError,FontError,ValueError,RuntimeError,KeyError,IndexError) as exc:
        result['reasons'].append(str(exc))
        result['actions'].append('Seleccionar un fragmento aislado o abrir el inspector de fuentes.')
    return result
