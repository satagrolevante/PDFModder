"""Explicit local reconstruction when the source font codes cannot be reused.

The original is never painted over. MuPDF removes real source text; a complete
chosen face is composed separately, then the final bytes are checked against
the original page, including every unselected glyph and graphic object.
"""
from dataclasses import replace
from hashlib import sha256
import math

import pymupdf as fitz

from .model import EditError, Glyph, intersects, union
from .draft_control_v305 import checkpoint, DraftCancelled


def reconstruction_issues(data, model, selected):
    """Advisory eligibility; never waives the final reconstruction checks."""
    from .validation import document_issues, content_widget_issues, scope_text_graphics_v322
    from .tagged import require_untagged
    if not selected:
        return ['Selecciona el bloque original que quieres reconstruir.']
    try:
        require_untagged(data,'Reconstruir un bloque con codificación no reutilizable')
        if any(g.mode!=0 or g.layer or abs(g.direction[0]-1)+abs(g.direction[1])>1e-6 for g in selected):
            return ['Este bloque necesita conservar su orientación, capa o modo de pintura mediante edición nativa.']
        if any(fitz.Rect(g.bbox).is_empty or not all(math.isfinite(v) for v in g.bbox) for g in selected):
            return ['La geometría del bloque no permite una eliminación verificable.']
        scoped=scope_text_graphics_v322(data,model,selected,require_neutral_final=True)
        from .clipping import CLIP_ISSUE
        issues=[issue for issue in scoped.issues if issue!=CLIP_ISSUE]
        if issues:return issues
        with fitz.open(stream=data,filetype='pdf') as doc:
            if doc.is_repaired:
                return ['La estructura del PDF necesita reparación antes de reconstruir un bloque.']
            issues=document_issues(data,doc,operation='content')
            if issues:return issues
            page=doc[model.number]
            regions=[g.bbox for g in selected]
            issues=content_widget_issues(page,regions)
            if issues:return issues
            for region in regions:
                if any(intersects(region,tuple(fitz.Rect(link['from'])*page.derotation_matrix)) for link in page.get_links()):
                    return ['El texto del enlace debe conservar también su destino mediante edición nativa.']
                if any(intersects(region,tuple(a.rect)) for a in page.annots() or []):
                    return ['El bloque toca una anotación que debe conservarse conjuntamente.']
        return []
    except DraftCancelled:
        raise
    except EditError as error:
        return [str(error)]
    except Exception:
        return ['No se pudo verificar la estructura del bloque para reconstruirlo.']


def reconstruction_selection(data, page, ids, resolver):
    """A recoverable draft, not authority to apply a reconstructed edit."""
    from .engine import extract_page
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, page, data)
    chosen = model.selected(ids)
    if not chosen or len(chosen) != len(set(ids)):
        raise EditError('Selecciona un bloque de la revisión actual.')
    issues=reconstruction_issues(data,model,chosen)
    if issues:raise EditError('\n'.join(issues))
    first = chosen[0]
    return dict(page=page, ids=list(ids), rect=union(g.bbox for g in chosen),
        revision=model.revision, runs=[dict(text=''.join(g.text for g in chosen),
            font_name=first.font, font_file=None, font_resource=first.font_resource,
            font_xref=first.font_xref, size=first.size, color=first.color,
            opacity=first.opacity, char_spacing=0.)], paragraphs=[], carets=[],
        baseline=first.origin[1], font_previews=[], reconstruction_available=True,
        text=''.join(g.text for g in chosen),
        reconstruction_reason='El bloque necesita una fuente completa y reconstrucción explícita. '
                              'Revisa y corrige el texto del borrador antes de reconstruirlo.')


def reconstruct_text_pdf(data, request, resolver):
    from .engine import extract_page, transaction_write_v318
    from .richtext import _validate, _drop_affected_groups
    from .validation import document_issues, content_widget_issues, scope_text_graphics_v322
    from .tagged import require_untagged
    from .font_choice_v321 import FontChoiceRequired
    from .fonts import FontError
    if request.revision and request.revision != sha256(data).hexdigest():
        raise EditError('El documento cambió desde la selección. Selecciona el bloque de nuevo.')
    if not request.ids:
        raise EditError('Selecciona el texto original que quieres reconstruir.')
    require_untagged(data,'Reconstruir un bloque con codificación no reutilizable')
    # No nominal or platform font fallback: this action uses the face the user
    # chose explicitly and proves its coverage before removing any source code.
    for run in request.runs:
        text=''.join(c for c in str(run.get('text','')) if c not in '\n\r\u2028\t')
        if not text:continue
        try:
            resolver.resolve_explicit(run.get('font_name') or '',text,font_file=run.get('font_file'),
                                      font_axes=run.get('font_axes'))
        except FontError as error:
            raise FontChoiceRequired(str(error),run,text) from error
    checkpoint()
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc,operation='content')
        if issues:raise EditError('\n'.join(issues))
        model=extract_page(doc,request.page,data)
        selected=model.selected(request.ids)
        if not selected or len(selected)!=len(set(request.ids)):
            raise EditError('La selección pertenece a otra revisión.')
        if any(g.mode!=0 or g.layer or abs(g.direction[0]-1)+abs(g.direction[1])>1e-6 for g in selected):
            raise EditError('Reconstruye un bloque horizontal visible sin capas; conserva los otros efectos mediante edición nativa.')
        scoped=scope_text_graphics_v322(data,model,selected,require_neutral_final=True)
        from .clipping import CLIP_ISSUE
        if any(issue!=CLIP_ISSUE for issue in scoped.issues):raise EditError('\n'.join(scoped.issues))
        areas=[]
        for glyph in selected:
            region=fitz.Rect(glyph.bbox)
            if region.is_empty or any(not math.isfinite(v) for v in region):
                raise EditError('La geometría del bloque no permite una eliminación verificable.')
            areas.append(tuple(region))
        page=doc[request.page]
        conflicts=content_widget_issues(page,areas)
        if conflicts:raise EditError('\n'.join(conflicts))
        for region in areas:
            if any(intersects(region,tuple(fitz.Rect(link['from'])*page.derotation_matrix)) for link in page.get_links()):
                raise EditError('Reconstruye el texto del enlace con su editor para conservar también su destino.')
            if any(intersects(region,tuple(a.rect)) for a in page.annots() or []):
                raise EditError('El bloque toca una anotación que debe conservarse conjuntamente.')
        from .richtext import _read_metadata, _match
        if any(any(_match(g,saved) for saved in record.get('glyphs',[]))
               for record in _read_metadata(doc,request.page) for g in selected):
            raise EditError('Este texto ya dispone de edición nativa; conserva sus estilos mediante el editor normal.')
        for region in areas:page.add_redact_annot(region,fill=None,cross_out=False)
        if not page.apply_redactions(images=0,graphics=0,text=0):
            raise EditError('No se pudo retirar el texto original del bloque.')
        _drop_affected_groups(doc,request.page,selected)
        intermediate=transaction_write_v318(doc)
    chosen={g.id for g in selected}; others=[g for g in model.glyphs if g.id not in chosen]
    # A font-code ambiguity may remove too much or too little. This independent
    # check must succeed before the replacement is even composed.
    _validate(data,intermediate,request.page,others,selected,[],[],None)
    if not any(str(r.get('text','')) for r in request.runs):
        checked=_validate(data,intermediate,request.page,others,selected,[],[],None)
        checked.update(page=request.page,rect=request.rect or union(areas),glyphs=[],carets=[],
            reconstruction=True,replacement='',original=model.text(request.ids),source_regions=areas,
            destination_regions=[],fonts={},source_sha256=sha256(data).hexdigest())
        return intermediate,checked
    checkpoint()
    from .richtext import edit_rich_pdf
    inserted=replace(request,ids=[],revision=sha256(intermediate).hexdigest(),
                     reconstruct=False,rect=request.rect or union(areas))
    output,report=edit_rich_pdf(intermediate,inserted,resolver)
    planned=[Glyph(**g) for g in report['glyphs']]
    checked=_validate(data,output,request.page,others+planned,selected+planned,[],[],None)
    report.update(checked,reconstruction=True,original=model.text(request.ids),
        source_regions=areas,source_sha256=sha256(data).hexdigest(),
        reconstruction_policy='Eliminación real y reconstrucción explícita del bloque; vecinos y PDF final verificados.')
    warning='Bloque reconstruido con la fuente elegida. El texto original se ha retirado; revisa la apariencia antes de aceptar.'
    report.setdefault('warnings',[]).append(warning);report['warning']=warning
    return output,report
