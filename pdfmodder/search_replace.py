"""Coincidencias revisables ligadas a una revisión y a caracteres concretos."""
import hashlib
import re
import pymupdf as fitz
from .model import EditError,EditRequest,union
from .draft_control_v305 import checkpoint


def _query_pattern(query):
    """A space in a phrase may stand for a PDF's physical line wrapping."""
    pieces=re.split(r'(\s+)',query.replace('\r\n','\n').replace('\r','\n'))
    return ''.join(r'\s+' if piece.isspace() else re.escape(piece) for piece in pieces)


def _text_streams(model, *, paragraphs=False, include_ocr=False):
    """Geometric scopes prevent phrases crossing columns/cells or OCR layers.

    Synthetic line separators have no glyph ID. Each real character remains
    bound to its original glyph, even when search whitespace spans a line.
    """
    from .selection_v300 import selection_index
    index=selection_index(model)
    by_id={g.id:g for g in model.glyphs}
    emitted=set()
    for line in index.lines:
        checkpoint()
        seed=line[0]
        if (seed.mode==3 or seed.opacity<=0) and not include_ocr:
            continue
        ids=index.group(seed,'paragraph') if paragraphs else [g.id for g in line]
        identity=tuple(ids)
        if identity in emitted:
            continue
        emitted.add(identity)
        text=[];positions=[];previous=None
        for identifier in ids:
            glyph=by_id[identifier]
            row=index.by_id.get(identifier)
            if previous is not None and row is not previous:
                text.append('\n');positions.append(None)
            text.extend(glyph.text);positions.extend([glyph]*len(glyph.text))
            previous=row
        yield ''.join(text),positions


def find_matches(data,query,pages=None,selection=None,case_sensitive=True,whole_word=False,include_ocr=False):
    from .engine import extract_page
    from .pageops import parse_pages
    revision=hashlib.sha256(data).hexdigest()
    if not isinstance(query,str) or not query.strip():raise EditError('Escribe el texto que deseas buscar.')
    pattern=_query_pattern(query)
    if whole_word:pattern=r'(?<!\w)'+pattern+r'(?!\w)'
    expression=re.compile(pattern,0 if case_sensitive else re.IGNORECASE)
    result=[]
    with fitz.open(stream=data,filetype='pdf') as doc:
        numbers=parse_pages(pages,len(doc)) if pages else list(range(len(doc)))
        if selection:
            if selection.get('revision')!=revision:raise EditError('La selección de búsqueda pertenece a una revisión anterior.')
            numbers=[number for number in numbers if number==selection['page']]
        for number in numbers:
            checkpoint()
            model=extract_page(doc,number,data)
            allowed=set(selection['ids']) if selection else None
            seen=set()
            for text,positions in _text_streams(model,paragraphs=any(c.isspace() for c in query),include_ocr=include_ocr):
                for match in expression.finditer(text):
                    chosen=[]
                    for glyph in positions[match.start():match.end()]:
                        if glyph is not None and (not chosen or chosen[-1].id!=glyph.id):chosen.append(glyph)
                    if not chosen:continue
                    if allowed is not None and any(g.id not in allowed for g in chosen):continue
                    identity=tuple(g.id for g in chosen)
                    if identity in seen:continue
                    seen.add(identity)
                    key=f'{revision}:{number}:'+','.join(str(g.id) for g in chosen)
                    result.append({'id':hashlib.sha256(key.encode()).hexdigest(), 'page':number,
                        'ids':[g.id for g in chosen],'rect':union(g.bbox for g in chosen),
                        'text':match.group(),'context':text[max(0,match.start()-35):match.end()+35],
                        'glyph_texts':[g.text for g in chosen],
                        'multiline':len({g.line for g in chosen})>1,
                        'revision':revision,'ocr':chosen[0].mode==3,
                        'visible':chosen[0].opacity>0,
                        'unsupported_reason':'Texto invisible mediante opacidad 0: sólo se admite corregir capas OCR con Tr=3.'
                            if chosen[0].mode!=3 and chosen[0].opacity<=0 else '',
                        'origins':[g.origin for g in chosen],'font':chosen[0].font,'size':chosen[0].size})
    return result


def _apply_font_choices(runs, match, choices):
    from .font_choice_v321 import face_identity
    for choice in choices or ():
        if choice.get('match_id')!=match['id']:continue
        source=choice.get('source_style',{});entry=choice.get('entry',{})
        if not entry.get('name'):raise EditError('La fuente elegida no identifica una variante válida.')
        for run in runs:
            if face_identity(run)==face_identity(source):
                run.update(font_name=entry['name'],font_file=entry.get('path') or entry.get('font_file'),
                           font_xref=None,font_resource=None,font_axes=entry.get('font_axes') or {})
    return runs


def replace_matches(data,matches,replacement,resolver=None,auto_width=True,*,font_choices=None,allow_overlap=True,auto_adapt=True):
    from .engine import extract_page
    from .textlayout import edit_with_layout
    revision=hashlib.sha256(data).hexdigest()
    if not matches:raise EditError('Marca al menos una coincidencia para previsualizar.')
    if any(m['revision']!=revision for m in matches):raise EditError('El PDF cambió; repite la búsqueda antes de reemplazar.')
    if any(m.get('unsupported_reason') for m in matches):
        raise EditError(next(m['unsupported_reason'] for m in matches if m.get('unsupported_reason')))
    seen=set()
    for match in matches:
        selected={(match['page'],i) for i in match['ids']}
        if seen & selected:raise EditError('Las coincidencias marcadas se superponen. Revisa la selección.')
        seen.update(selected)
    candidate=data
    reports=[]
    # Locate each original appearance anew by text + exact origin; prior edits
    # change numeric glyph ids, never retarget another occurrence by its spelling.
    for match in sorted(matches,key=lambda m:(m['page'],m['ids'][0]),reverse=True):
        checkpoint()
        with fitz.open(stream=candidate,filetype='pdf') as doc:
            model=extract_page(doc,match['page'],candidate)
        chosen=[]
        for char,origin in zip(match.get('glyph_texts',list(match['text'])),match['origins']):
            found=[g for g in model.glyphs if g.text==char and (g.mode==3)==match['ocr'] and
                   (g.opacity>0)==match.get('visible',True) and
                   abs(g.origin[0]-origin[0])<.035 and abs(g.origin[1]-origin[1])<.035 and g not in chosen]
            if len(found)!=1:raise EditError('Una coincidencia ya no se puede aislar. Repite la búsqueda.')
            chosen.append(found[0])
        try:
            if match['ocr']:
                request=EditRequest(match['page'],[g.id for g in chosen],text=replacement,revision=model.revision,
                    auto_width=auto_width,line_reflow=False,ocr_mode='searchable')
                candidate,report=edit_with_layout(candidate,request,resolver)
            else:
                from .richtext import selection_payload,edit_rich_pdf
                from .richmodels import RichTextRequest
                from .native_panel import _replace_runs
                payload=selection_payload(candidate,match['page'],[g.id for g in chosen],resolver,page_model=model)
                runs=_apply_font_choices(_replace_runs(payload['runs'],replacement),match,font_choices)
                rect=payload['rect']
                if match.get('multiline'):
                    first=chosen[0]
                    # A match starting midway through line one must not move
                    # onto its unselected prefix just because line two starts
                    # farther left. Keep the actual first source anchor.
                    rect=(first.bbox[0],first.bbox[1],max(rect[2],first.bbox[2]),rect[3])
                request=RichTextRequest(match['page'],payload['ids'],runs,rect=rect,
                    paragraphs=payload.get('paragraphs',[]),revision=model.revision,
                    auto_width=bool(auto_width),auto_height=True,
                    auto_adapt=auto_adapt,allow_overlap=allow_overlap)
                candidate,report=edit_rich_pdf(candidate,request,resolver)
        except EditError as exc:
            from .font_choice_v321 import FontChoiceRequired
            if isinstance(exc,FontChoiceRequired):
                exc.match_id=match['id'];exc.match_text=match['text'];exc.page=match['page']
                raise
            raise EditError(f"Página {match['page']+1}, «{match['text']}»: {exc}") from exc
        report.update(match_id=match['id'],page=match['page'])
        reports.append(report)
    return candidate,{'operation':'replace_matches','verified':True,'match_count':len(matches),'edits':reports,
                      'warning':'Las coincidencias OCR modifican sólo la capa buscable, sin cambiar la imagen.' if any(m['ocr'] for m in matches) else ''}
