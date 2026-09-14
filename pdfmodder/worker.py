"""API de proceso único. La GUI sólo intercambia valores y PNG, nunca Document."""
from collections import OrderedDict
from pathlib import Path
import hashlib
import os
import uuid
import pymupdf as fitz
from .engine import extract_page, edit_pdf, atomic_save
from .fonts import FontResolver
from .history import History
from .model import EditError, EditRequest
from .validation import document_issues


class Session:
    def __init__(self,path,password='',config_path=None,history_dir=None):
        self.path=str(Path(path).resolve())
        self.original=Path(path).read_bytes()
        self.password=password
        with self._open(self.original) as doc:
            self.page_count=doc.page_count
            if not self.page_count:
                raise EditError('El documento no contiene páginas.')
            self.issues=document_issues(self.original,doc)
            self.tagged=doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0]!='null'
        self.history=History(self.original,directory=history_dir)
        self.resolver=FontResolver(config_path=config_path)
        self.pending=None
        self.pending_report=None
        self.cache=OrderedDict()
        self.cache_bytes=0
        self.saved_digest=hashlib.sha256(self.original).hexdigest()
        self.original_page_count=self.page_count
        self.protected_paths={self.path}

    def _page_keys(self, pending=True):
        reports=self.history.base_reports+self.history.reports[:self.history.index+1]
        if pending and self.pending_report:
            reports=reports+[self.pending_report]
        for report in reversed(reports):
            if report and '_page_keys' in report:
                return report['_page_keys'][:]
        return list(range(self.original_page_count))

    def _instance_keys(self, pending=True):
        """Current page identities, separate from the original-page comparison map."""
        reports=self.history.base_reports+self.history.reports[:self.history.index+1]
        if pending and self.pending_report:
            reports=reports+[self.pending_report]
        for report in reversed(reports):
            if report and '_instance_keys' in report:
                return report['_instance_keys'][:]
        return [f'original:{index}' for index in range(self.original_page_count)]

    def _instance_changes(self, pending=True):
        """Replay only highlight metadata; duplicated pages inherit a timed snapshot.

        PDF bytes still come from immutable history snapshots. A clone inherits
        changes that already existed when it was made, never later edits to its
        parent or siblings. base_reports keeps this provenance after trimming.
        """
        reports=self.history.base_reports+self.history.reports[:self.history.index+1]
        if pending and self.pending_report:
            reports=reports+[self.pending_report]
        changes={}
        for report in reports:
            if not report:
                continue
            for copied,source in report.get('_instance_clones',{}).items():
                changes[copied]=list(changes.get(source,[]))
            for edit in [*report.get('edits',[]),report]:
                instance=edit.get('_instance_key')
                if instance is not None:
                    changes.setdefault(instance,[]).extend(edit.get('source_regions',[])+edit.get('destination_regions',[]))
        return changes

    def _mark_page_edit(self,report,page):
        report.update(_page_key=self._page_keys(False)[page],_instance_key=self._instance_keys(False)[page])

    def _clear_cache(self):
        self.cache.clear()
        self.cache_bytes=0

    def _put_preview(self,candidate,report):
        self.pending,self.pending_report=candidate,report
        self._clear_cache()
        return {'state':self.state(),'report':report}

    def _writable(self):
        if self.issues:
            raise EditError('\n'.join(self.issues))
        if self.pending is not None:
            raise EditError('Aplica o cancela la vista previa antes de otra operación.')

    def _safe_destination(self,path):
        target=Path(path).resolve()
        for source in self.protected_paths:
            if target==Path(source).resolve() or (target.exists() and Path(source).exists() and os.path.samefile(target,source)):
                raise EditError('El destino no puede sobrescribir un PDF original usado en este trabajo.')

    def _open(self,data):
        doc=fitz.open(stream=data,filetype='pdf')
        if not doc.is_pdf:
            doc.close()
            raise EditError('Selecciona un archivo PDF digital.')
        if doc.needs_pass and not doc.authenticate(self.password):
            doc.close()
            raise EditError('PASSWORD_REQUIRED: El PDF necesita una contraseña válida para abrirlo.')
        return doc

    def state(self):
        keys=self._page_keys()
        return {'path':self.path,'page_count':len(keys),'original_pages':[k if k>=0 else None for k in keys],'undo':self.history.index>0,
                'redo':self.history.index+1<len(self.history.states),'issues':self.issues,'tagged':self.tagged,
                'preview':self.pending is not None,'dirty':hashlib.sha256(self.history.current).hexdigest()!=self.saved_digest,
                'history_index':self.history.index,'history_dropped':self.history.dropped}

    def page(self,number,zoom=1.,original=False,thumbnail=False):
        data=self.original if original else (self.pending or self.history.current)
        keys=self._page_keys()
        if not 0<=number<len(keys):
            raise EditError('La página seleccionada ya no está en el documento.')
        source_number=keys[number] if original else number
        if source_number<0:
            raise EditError('Esta página se añadió al combinar PDFs y no existe en el original.')
        zoom=max(.1,min(float(zoom),4.))
        key=(hashlib.sha256(data).digest(),number,round(zoom,3),thumbnail)
        if key in self.cache:
            result=self.cache.pop(key)
            self.cache[key]=result
            return {**result,'state':self.state()}
        with self._open(data) as doc:
            page=doc[source_number]
            if page.rect.width*page.rect.height*zoom*zoom>16_000_000:
                zoom=(16_000_000/(page.rect.width*page.rect.height))**.5
            pix=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),alpha=False,colorspace=fitz.csRGB)
            png=pix.tobytes('png')
            model=None if thumbnail else extract_page(doc,source_number,None if doc.needs_pass else data)
            fonts=[] if thumbnail else self.resolver.inspect(doc,source_number)
            if thumbnail:
                images=[]
            else:
                from .media import image_items
                images=image_items(doc,source_number)
        changes=self._instance_changes().get(self._instance_keys()[number],[])
        result={'png':png,'number':number,'zoom':zoom,'model':model,'fonts':fonts,'images':images,'changes':changes}
        self.cache[key]=result
        self.cache_bytes+=len(png)
        while self.cache_bytes>32*1024*1024 or len(self.cache)>12:
            _,removed=self.cache.popitem(last=False)
            self.cache_bytes-=len(removed['png'])
        return {**result,'state':self.state()}

    def preview(self,request):
        if self.issues:
            raise EditError('\n'.join(self.issues))
        if isinstance(request,dict):
            request=EditRequest(**request)
        # Failed previews leave both the working state and last valid preview intact.
        from .textlayout import edit_with_layout
        candidate,report=edit_with_layout(self.history.current,request,self.resolver)
        report['page']=request.page
        self._mark_page_edit(report,request.page)
        return self._put_preview(candidate,report)

    def insert_text(self,request):
        self._writable()
        from .composition import AddTextRequest,insert_text_pdf
        if isinstance(request,dict):
            request=AddTextRequest(**request)
        candidate,report=insert_text_pdf(self.history.current,request,self.resolver)
        report.update(page=request.page,operation='insert_text')
        self._mark_page_edit(report,request.page)
        return self._put_preview(candidate,report)

    def image_operation(self,operation,page,rect=None,image_bytes=None,image_id=None,revision=None,
                        replacement_bytes=None,crop=None,rotation=0):
        self._writable()
        from .media import add_image_pdf,transform_image_pdf,delete_image_pdf
        if operation=='add':
            candidate,report=add_image_pdf(self.history.current,page,image_bytes,rect,revision=revision)
        elif operation=='transform':
            candidate,report=transform_image_pdf(self.history.current,page,image_id,rect,revision=revision)
        elif operation=='delete':
            candidate,report=delete_image_pdf(self.history.current,page,image_id,revision=revision)
        elif operation=='edit':
            from .media import edit_image_pdf
            candidate,report=edit_image_pdf(self.history.current,page,image_id,replacement_bytes=replacement_bytes,
                                           crop=crop,rotation=rotation,revision=revision)
        else:
            raise EditError('Operación de imagen desconocida.')
        report.update(page=page,operation='image_'+operation)
        self._mark_page_edit(report,page)
        return self._put_preview(candidate,report)

    def export_image(self,page,image_id,revision,path=None):
        from .media import export_image_pdf
        asset=export_image_pdf(self.history.current,page,image_id,revision=revision)
        if path is None:return asset
        self._safe_destination(path)
        import tempfile
        target=Path(path).resolve()
        temporary=None
        try:
            fd,temporary=tempfile.mkstemp(prefix='.pdfmodder-image-',dir=target.parent)
            with os.fdopen(fd,'wb') as stream:
                stream.write(asset['image_bytes']);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,target);temporary=None
        finally:
            if temporary and os.path.exists(temporary):os.unlink(temporary)
        return {'path':str(target),'state':self.state(),'ext':asset['ext']}

    def find_replacements(self,**parameters):
        from .search_replace import find_matches
        matches=find_matches(self.history.current,**parameters)
        self._review_matches={m['id']:m for m in matches}
        return {'matches':matches}

    def preview_replacements(self,match_ids,replacement,auto_width=True):
        if self.issues:raise EditError('\n'.join(self.issues))
        records=getattr(self,'_review_matches',{})
        if len(match_ids)!=len(set(match_ids)) or any(i not in records for i in match_ids):
            raise EditError('Repite la búsqueda y marca coincidencias válidas.')
        from .search_replace import replace_matches
        candidate,report=replace_matches(self.history.current,[records[i] for i in match_ids],replacement,self.resolver,auto_width)
        for edit in report['edits']:self._mark_page_edit(edit,edit['page'])
        self._put_preview(candidate,report)
        return self.review_page(records[match_ids[0]]['page'])

    def review_page(self,number):
        result=self.page(number,zoom=2.)
        result['report']=self.pending_report or {}
        return result

    def organizer_info(self,path=None):
        data=Path(path).read_bytes() if path else self.history.current
        with fitz.open(stream=data,filetype='pdf') as doc:
            issues=document_issues(data,doc)
            if issues:raise EditError('\n'.join(issues))
            pages=[{'page':p.number,'width':p.rect.width,'height':p.rect.height,'rotation':p.rotation} for p in doc]
        return {'pages':pages,'source_id':hashlib.sha256(data).hexdigest() if path else 'current','path':path}

    def organizer_thumbnail(self,page,path=None):
        data=Path(path).read_bytes() if path else self.history.current
        with fitz.open(stream=data,filetype='pdf') as doc:
            p=doc[page];scale=min(110/p.rect.width,150/p.rect.height)
            png=p.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).tobytes('png')
        return {'png':png,'page':page}

    def organize_pages(self,plan,paths=None):
        self._writable()
        from .pageops import organize_pages_pdf
        additions={key:Path(path).read_bytes() for key,path in (paths or {}).items()}
        for key,data in additions.items():
            if key!=hashlib.sha256(data).hexdigest():raise EditError('Un PDF a insertar cambió desde su previsualización. Vuelve a incorporarlo.')
        candidate,report=organize_pages_pdf(self.history.current,plan,additions)
        original_keys=self._page_keys(False)
        original_instances=self._instance_keys(False)
        next_key=min(original_keys+[0])-1
        keys=[];instances=[];clones={};used=set()
        for number in report['page_map']:
            if number is None:
                keys.append(next_key);next_key-=1
                instances.append(uuid.uuid4().hex)
            else:
                keys.append(original_keys[number])
                source=original_instances[number]
                if source in used:
                    copied=uuid.uuid4().hex
                    clones[copied]=source
                    instances.append(copied)
                else:
                    instances.append(source);used.add(source)
        report.update(operation='organize_pages',_page_keys=keys,_instance_keys=instances,_instance_clones=clones)
        self.protected_paths.update(str(Path(path).resolve()) for path in (paths or {}).values())
        return self._put_preview(candidate,report)

    def delete_pages(self,expression):
        self._writable()
        from .pageops import parse_pages,delete_pages_pdf
        keys=self._page_keys(False)
        pages=parse_pages(expression,len(keys))
        candidate,report=delete_pages_pdf(self.history.current,pages)
        instances=self._instance_keys(False)
        report.update(operation='delete_pages',_page_keys=[k for i,k in enumerate(keys) if i not in pages],
                      _instance_keys=[key for i,key in enumerate(instances) if i not in pages])
        self._put_preview(candidate,report)
        return self.commit()

    def extract_pages(self,expression,path):
        self._writable()
        from .pageops import parse_pages,extract_pages_pdf
        self._safe_destination(path)
        pages=parse_pages(expression,len(self._page_keys(False)))
        candidate,report=extract_pages_pdf(self.history.current,pages)
        output=atomic_save(candidate,path,self.path)
        return {'path':output,'report':report,'state':self.state()}

    def merge(self,paths):
        self._writable()
        if not paths:
            raise EditError('Selecciona al menos un PDF para añadir.')
        from .pageops import merge_pdfs
        additions=[Path(p).read_bytes() for p in paths]
        candidate,report=merge_pdfs(self.history.current,additions)
        keys=self._page_keys(False)
        with fitz.open(stream=candidate,filetype='pdf') as check:
            count=check.page_count-len(keys)
        first=min(keys+[0])-1
        report.update(operation='merge',_page_keys=keys+list(range(first,first-count,-1)),
                      _instance_keys=self._instance_keys(False)+[uuid.uuid4().hex for _ in range(count)])
        self._put_preview(candidate,report)
        result=self.commit()
        self.protected_paths.update(str(Path(p).resolve()) for p in paths)
        return result

    def commit(self):
        if self.pending is None:
            raise EditError('No hay una previsualización validada para aplicar.')
        report=self.pending_report
        self.history.push(self.pending,report)
        self.pending=self.pending_report=None
        self.cache.clear()
        self.cache_bytes=0
        self.page_count=len(self._page_keys(False))
        return {'state':self.state(),'report':report}

    def cancel(self):
        self.pending=self.pending_report=None
        self.cache.clear()
        self.cache_bytes=0
        return {'state':self.state()}

    def navigate_history(self,redo=False):
        self.cancel()
        self.history.redo() if redo else self.history.undo()
        self.page_count=len(self._page_keys(False))
        return {'state':self.state()}

    def save(self,path):
        if self.issues:
            raise EditError('\n'.join(self.issues))
        if self.pending is not None:
            raise EditError('Aplica o cancela la previsualización antes de guardar.')
        self._safe_destination(path)
        result=atomic_save(self.history.current,path,self.path)
        self.saved_digest=hashlib.sha256(self.history.current).hexdigest()
        return {'path':result,'state':self.state()}

    def search(self,text):
        if not text:
            return {'matches':[]}
        matches=[]
        with self._open(self.history.current) as doc:
            for page in doc:
                for rect in page.search_for(text):
                    matches.append({'page':page.number,'rect':tuple(rect)})
        return {'matches':matches}

    def associate(self,name,path):
        self.resolver.associate(name,path)
        self.cache.clear()
        self.cache_bytes=0
        return {'state':self.state()}

    def font_evidence(self,page,ids,revision,original=False):
        data=self.original if original else (self.pending or self.history.current)
        if revision!=hashlib.sha256(data).hexdigest():
            raise EditError('La selección cambió; vuelve a seleccionar el texto para inspeccionar su fuente.')
        number=self._page_keys()[page] if original else page
        with self._open(data) as doc:
            model=extract_page(doc,number,data)
            selected=model.selected(ids)
            if not selected or len(selected)!=len(set(ids)):
                raise EditError('Selecciona texto del documento actual para identificar su fuente.')
            groups={}
            for glyph in selected:
                groups.setdefault((glyph.font,glyph.font_xref,glyph.font_resource),[]).append(glyph)
            evidence=[]
            for (name,xref,resource),glyphs in groups.items():
                item=self.resolver.inspect_selection(doc,number,name,''.join(g.text for g in glyphs),font_xref=xref,resource=resource)
                item['selection_text']=''.join(g.text for g in glyphs)
                item['render_modes']=sorted({g.mode for g in glyphs})
                evidence.append(item)
        return {'evidence':evidence}

    def close(self):
        self.history.close()


_session=None


def dispatch(command,payload=None):
    """ProcessPoolExecutor(max_workers=1, spawn) invokes this serially."""
    global _session
    payload=payload or {}
    if command=='font_catalog':
        return {'catalog':(_session.resolver if _session else FontResolver()).catalog()}
    if command=='combine':
        paths=payload.get('paths',[])
        if len(paths)<2:
            raise EditError('Selecciona al menos dos archivos PDF para combinar.')
        new=Session(paths[0],config_path=payload.get('config_path'),history_dir=payload.get('history_dir'))
        try:
            result=new.merge(paths[1:])
        except Exception:
            new.close()
            raise
        if _session:
            _session.close()
        _session=new
        return result
    if command=='open':
        new=Session(**payload)
        if _session:
            _session.close()
        _session=new
        return {'state':new.state()}
    if _session is None:
        raise EditError('Abre primero un PDF.')
    if command=='page': return _session.page(**payload)
    if command=='preview': return _session.preview(payload['request'])
    if command=='insert_text': return _session.insert_text(payload['request'])
    if command=='image': return _session.image_operation(**payload)
    if command=='export_image': return _session.export_image(**payload)
    if command=='find_replacements': return _session.find_replacements(**payload)
    if command=='preview_replacements': return _session.preview_replacements(**payload)
    if command=='review_page': return _session.review_page(**payload)
    if command=='organizer_info': return _session.organizer_info(**payload)
    if command=='organizer_thumbnail': return _session.organizer_thumbnail(**payload)
    if command=='organize_pages': return _session.organize_pages(**payload)
    if command=='image_apply':
        _session.image_operation(**payload)
        return _session.commit()
    if command=='delete_pages': return _session.delete_pages(payload['expression'])
    if command=='extract_pages': return _session.extract_pages(**payload)
    if command=='merge': return _session.merge(payload['paths'])
    if command=='commit': return _session.commit()
    if command=='cancel': return _session.cancel()
    if command=='apply':
        _session.preview(payload['request'])
        return _session.commit()
    if command=='undo': return _session.navigate_history()
    if command=='redo': return _session.navigate_history(True)
    if command=='save': return _session.save(payload['path'])
    if command=='search': return _session.search(payload['text'])
    if command=='associate': return _session.associate(**payload)
    if command=='font_evidence': return _session.font_evidence(**payload)
    if command=='close':
        _session.close()
        _session=None
        return {}
    raise EditError(f'Comando desconocido: {command}')
