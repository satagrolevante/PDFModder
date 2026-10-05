"""API de proceso único. La GUI sólo intercambia valores y PNG, nunca Document."""
from collections import OrderedDict
from dataclasses import replace
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
    def __init__(self,path,password='',config_path=None,history_dir=None,reading=False,
                 recovery_root=None,session_id=None):
        self.session_id=session_id or uuid.uuid4().hex
        self.recovery_id=uuid.uuid4().hex
        self.path=str(Path(path).resolve())
        self.original=Path(path).read_bytes()
        self.password=password
        self._editing_prepared=not bool(reading)
        self._config_path=config_path
        with self._open(self.original) as doc:
            self.page_count=doc.page_count
            self.copy_allowed=bool(doc.permissions & fitz.PDF_PERM_COPY)
            if not self.page_count:
                raise EditError('El documento no contiene páginas.')
            self.issues=[] if reading else document_issues(self.original,doc)
            self.tagged=doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0]!='null'
        from .recovery_v200 import recovery_path
        original_digest=hashlib.sha256(self.original).hexdigest()
        self.history=History(self.original,directory=history_dir,
            persistent_root=recovery_path(self.recovery_id,recovery_root or (Path(history_dir)/'recovery' if history_dir else None)),
            metadata={'path':self.path,'saved_digest':original_digest,
                      'original_digest':original_digest,'protected_paths':[self.path]})
        self._initial_original=None
        self.resolver=None if reading else FontResolver(config_path=config_path)
        self.pending=None
        self.pending_report=None
        self.cache=OrderedDict()
        self.cache_bytes=0
        self.saved_digest=original_digest
        self._tagged_revision=self.saved_digest
        self.original_page_count=self.page_count
        self.protected_paths={self.path}
        self._page_caps_cache=OrderedDict()
        self._reading_info_cache=OrderedDict()
        self._documents=OrderedDict()
        self._displaylists=OrderedDict()
        self._model_cache=OrderedDict()
        self._model_bytes=0
        self.workspace={}
        self.recovered_draft=None

    @property
    def original(self):
        return self.history.original if hasattr(self,'history') else self._initial_original

    @original.setter
    def original(self,data):self._initial_original=data

    @property
    def pending(self):return getattr(self,'_pending',None)

    @pending.setter
    def pending(self,data):
        self._pending=data
        self._pending_digest=hashlib.sha256(data).hexdigest() if data is not None else None

    def _revision(self,original=False):
        if original:return self.history.metadata['original_digest']
        return self._pending_digest if self.pending is not None else self.history.revision

    def _checkpoint(self):
        self.history.checkpoint({'path':self.path,'saved_digest':self.saved_digest,
            'protected_paths':sorted(self.protected_paths),'workspace':self.workspace},
            self.pending,self.pending_report)

    def update_workspace(self,workspace):
        # Only UI state is accepted. Do not persist caller dictionaries containing secrets.
        self.workspace={key:workspace[key] for key in ('page','zoom','reading','scroll','selection') if key in workspace}
        if self.history.root.exists():self._checkpoint()
        return {'state':self.state()}

    def store_draft(self,draft=None,workspace=None):
        """Persist bounded JSON text/format, never font buffers or credentials."""
        import json
        workspace={key:workspace[key] for key in ('page','zoom','reading','scroll','selection')
                   if workspace and key in workspace}
        clean=None
        if draft:
            self._require_editing()
            kind=draft.get('kind')
            if kind=='legacy':
                clean={key:draft[key] for key in ('kind','page','ids','revision','text') if key in draft}
            elif kind=='rich':
                source=draft.get('payload',{})
                payload={key:source[key] for key in ('page','ids','rect','revision','width','height','allow_overlap','auto_width','auto_height') if key in source}
                styles=('text','font_name','font_file','font_xref','font_resource','size','color','opacity','char_spacing','underline','bold','italic','_complementary_source')
                settings=('index','alignment','left_indent','right_indent','first_indent','line_spacing','space_before','space_after','tab_stops','tab_interval')
                payload['runs']=[{key:run[key] for key in styles if key in run} for run in source.get('runs',[])]
                payload['paragraphs']=[{key:p[key] for key in settings if key in p} for p in source.get('paragraphs',[])]
                clean={'kind':'rich','payload':payload}
            else:raise EditError('El tipo de borrador no es compatible.')
            try:serialized=json.dumps(clean,allow_nan=False,ensure_ascii=False).encode('utf-8')
            except (TypeError,ValueError) as exc:raise EditError('El borrador contiene propiedades no serializables.') from exc
            if len(serialized)>8*1024*1024:raise EditError('El borrador supera 8 MB; acepta por fragmentos más pequeños.')
        changed=(clean!=self.history.metadata.get('draft') or workspace!=self.workspace)
        self.workspace=workspace
        if changed and (clean is not None or self.history.root.exists()):
            self.history.checkpoint({'path':self.path,'saved_digest':self.saved_digest,
                'protected_paths':sorted(self.protected_paths),'workspace':workspace,'draft':clean},self.pending,self.pending_report)
        self.recovered_draft=None
        return {'state':self.state()}

    def _cleanup_print(self):
        folder=getattr(self,'_print_folder_v200',None)
        if folder:folder.cleanup();self._print_folder_v200=None

    def _document(self,data,revision):
        if revision in self._documents:
            doc=self._documents.pop(revision);self._documents[revision]=doc;return doc
        doc=self._open(data);self._documents[revision]=doc
        while len(self._documents)>2:
            key,old=self._documents.popitem(last=False)
            for cache_key in list(self._displaylists):
                if cache_key[0]==key:self._displaylists.pop(cache_key)
            old.close()
        return doc

    def _close_documents(self):
        self._displaylists.clear()
        for doc in self._documents.values():doc.close()
        self._documents.clear()

    def suspend(self):
        self._cleanup_print()
        self._clear_cache();self._close_documents()
        self.history.suspend()
        if self.pending is not None:
            self._checkpoint();self._pending=None
        self._suspended_pending=bool(self.history.pending_path)
        self.resolver=None
        self._rich_catalog=None;self._review_matches={};self._prepared_rich=None

    def resume(self):
        if getattr(self,'_suspended_pending',False):
            self.pending=self.history.pending_path.read_bytes();self.pending_report=self.history.pending_report
            self._suspended_pending=False
        if self._editing_prepared and self.resolver is None:self.resolver=FontResolver(config_path=self._config_path)

    @classmethod
    def recover(cls,identifier,password='',config_path=None,recovery_root=None,session_id=None):
        from .recovery_v200 import read_checkpoint
        folder,manifest=read_checkpoint(identifier,recovery_root,verify=True)
        # Validate all PDF credentials and structure before attaching the existing checkpoint.
        obj=cls.__new__(cls);obj.password=password
        history=History.restore(folder,manifest)
        try:
            with obj._open(history.current) as doc:
                count=doc.page_count;copy_allowed=bool(doc.permissions & fitz.PDF_PERM_COPY)
                issues=document_issues(history.current,doc)
                tagged=doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0]!='null'
            with obj._open(history.original) as doc:original_count=doc.page_count
        except Exception:
            history._lock.close();history._lock=None;raise
        obj.session_id=session_id or uuid.uuid4().hex;obj.recovery_id=identifier
        obj.path=manifest['metadata']['path'];obj.history=history;obj._initial_original=None
        obj._config_path=config_path;obj._editing_prepared=True;obj.resolver=FontResolver(config_path=config_path)
        obj.page_count=count;obj.copy_allowed=copy_allowed;obj.issues=issues;obj.tagged=tagged
        obj.original_page_count=original_count;obj.saved_digest=manifest['metadata']['saved_digest']
        obj.protected_paths=set(manifest['metadata'].get('protected_paths',[obj.path]))
        obj.pending=history.pending_path.read_bytes() if history.pending_path else None
        obj.pending_report=history.pending_report;obj._tagged_revision=None
        obj.cache=OrderedDict();obj.cache_bytes=0;obj._page_caps_cache=OrderedDict();obj._reading_info_cache=OrderedDict()
        obj._documents=OrderedDict();obj._displaylists=OrderedDict();obj._model_cache=OrderedDict();obj._model_bytes=0
        obj.workspace=manifest['metadata'].get('workspace',{})
        obj.recovered_draft=manifest['metadata'].get('draft')
        if obj.recovered_draft and obj.recovered_draft.get('kind')=='rich':
            payload=obj.recovered_draft['payload']
            if payload.get('revision')==history.revision:
                try:
                    source=obj.rich_selection(payload['page'],payload['ids'])
                    obj.recovered_draft={'kind':'rich','payload':{**source,**payload}}
                except EditError:pass  # Text remains recoverable even when its original font is unavailable.
        return obj

    def reading_info(self,original=False):
        data=self.original if original else (self.pending or self.history.current)
        revision=self._revision(original)
        keys=self._page_keys()
        cache_key=(revision,bool(original),tuple(keys))
        if cache_key not in self._reading_info_cache:
            with self._open(data) as document:
                geometries=[]
                for index in range(len(keys)):
                    source=keys[index] if original else index
                    rect=document[source].rect if source>=0 else fitz.Rect(0,0,595,842)
                    geometries.append({'width':rect.width,'height':rect.height})
                self._reading_info_cache[cache_key]={'page_geometries':geometries,'revision':revision}
            while len(self._reading_info_cache)>3:self._reading_info_cache.popitem(last=False)
        return dict(self._reading_info_cache[cache_key])

    def reading_copy_range(self,start,end,revision,original=False):
        from .reading_order_v180 import selection_text
        data=self.original if original else (self.pending or self.history.current)
        if revision!=self._revision(original):
            raise EditError('El documento cambió después de seleccionar. Selecciona de nuevo el texto.')
        keys=self._page_keys()
        first,last=int(start['page']),int(end['page'])
        if not 0<=first<=last<len(keys):raise EditError('El rango de páginas seleccionado no es válido.')
        parts=[];length=0
        with self._open(data) as document:
            if not document.permissions & fitz.PDF_PERM_COPY:
                raise EditError('El documento no permite copiar texto con las credenciales aportadas.')
            for number in range(first,last+1):
                source=keys[number] if original else number
                if source<0:raise EditError('La página seleccionada no existe en el original.')
                model=extract_page(document,source,None)
                try:
                    text=selection_text(model,start_id=start['id'] if number==first else None,
                                         end_id=end['id'] if number==last else None)
                except (KeyError,ValueError) as error:
                    raise EditError('No se reconoce el extremo seleccionado. Selecciona de nuevo.') from error
                parts.append(text);length+=len(text)
                if length>8_000_000:raise EditError('La selección supera ocho millones de caracteres. Copia un rango menor.')
        return {'text':'\n\n'.join(parts),'revision':revision}

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

    def _instance_changes(self, pending=True, original=False):
        """Replay only highlight metadata; duplicated pages inherit a timed snapshot.

        PDF bytes still come from immutable history snapshots. A clone inherits
        changes that already existed when it was made, never later edits to its
        parent or siblings. base_reports keeps this provenance after trimming.
        """
        reports=self.history.base_reports+self.history.reports[:self.history.index+1]
        if pending and self.pending_report:
            reports=reports+[self.pending_report]
        changes={}; offsets={}
        for report in reports:
            if not report:
                continue
            for copied,source in report.get('_instance_clones',{}).items():
                changes[copied]=list(changes.get(source,[]))
                offsets[copied]=offsets.get(source,(0.,0.))
            for instance,shift in report.get('_region_translations',{}).items():
                dx,dy=shift
                ox,oy=offsets.get(instance,(0.,0.))
                offsets[instance]=(ox+dx,oy+dy)
                if not original:
                    changes[instance]=[(r[0]+dx,r[1]+dy,r[2]+dx,r[3]+dy)
                                       for r in changes.get(instance,[])]
            for edit in [*report.get('edits',[]),report]:
                instance=edit.get('_instance_key')
                if instance is not None:
                    regions=edit.get('source_regions',[])+edit.get('destination_regions',[])
                    if original:
                        dx,dy=offsets.get(instance,(0.,0.))
                        regions=[(r[0]-dx,r[1]-dy,r[2]-dx,r[3]-dy) for r in regions]
                    changes.setdefault(instance,[]).extend(regions)
        return changes

    def _geometry_changed_instances(self, pending=True):
        reports=self.history.base_reports+self.history.reports[:self.history.index+1]
        if pending and self.pending_report:reports=reports+[self.pending_report]
        changed=set()
        for report in reports:
            if not report:continue
            for copied,source in report.get('_instance_clones',{}).items():
                if source in changed:changed.add(copied)
            changed.update(report.get('_geometry_changed_instances',[]))
        return changed

    def _mark_page_edit(self,report,page):
        report.update(_page_key=self._page_keys(False)[page],_instance_key=self._instance_keys(False)[page])

    def _clear_cache(self):
        self.cache.clear()
        self.cache_bytes=0
        self._model_cache.clear();self._model_bytes=0

    def _put_preview(self,candidate,report):
        self.history.checkpoint({'path':self.path,'saved_digest':self.saved_digest,
            'protected_paths':sorted(self.protected_paths),'workspace':self.workspace},candidate,report)
        self.pending,self.pending_report=candidate,report
        self._clear_cache()
        return {'state':self.state(),'report':report}

    def _writable(self):
        self._require_editing()
        if self.issues:
            raise EditError('\n'.join(self.issues))
        if self.pending is not None:
            raise EditError('Aplica o cancela la vista previa antes de otra operación.')

    def _require_editing(self):
        if not self._editing_prepared:
            raise EditError('Activa las herramientas para preparar y comprobar el PDF antes de modificarlo o exportarlo.')

    def prepare_editing(self,number=0,zoom=1.,original=False):
        """Materialise edit checks once; retain the document and its history."""
        if not self._editing_prepared:
            with self._open(self.history.current) as document:
                issues=document_issues(self.history.current,document)
            resolver=FontResolver(config_path=self._config_path)
            self.issues=issues
            self.resolver=resolver
            self._editing_prepared=True
            self._clear_cache()
        return self.page(number,zoom=zoom,original=original,reading=False)

    def copy_reading_selection(self,page,ids=None,image_id=None,revision=None):
        """Copy selected plain text without resolving portable font programs."""
        data=self.history.current
        digest=self.history.revision
        if revision and revision!=digest:
            raise EditError('El documento cambió. Selecciona el texto de nuevo antes de copiar.')
        if image_id is not None:
            raise EditError('Activa las herramientas para copiar una imagen del PDF.')
        with self._open(data) as document:
            if not document.permissions & fitz.PDF_PERM_COPY:
                raise EditError('Los permisos del PDF no permiten copiar contenido.')
            if not 0<=page<document.page_count:
                raise EditError('La página seleccionada ya no existe.')
            model=extract_page(document,page,None)
        ids=list(ids or [])
        selected=model.selected(ids)
        if not selected or len(selected)!=len(set(ids)):
            raise EditError('Selecciona texto del PDF actual para copiar.')
        from .model import union
        text=model.text(ids)
        return {'text':text,'bundle':{'version':1,'kind':'plain_text','text':text,
                    'rect':union(g.bbox for g in selected),'source_revision':digest,'source_page':page},
                'notice':'Texto copiado. Activa las herramientas para copiar objetos con su formato.'}

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
        current_digest=self.history.revision
        tagged_revision=self._revision()
        if tagged_revision!=self._tagged_revision:
            with self._open(self.pending or self.history.current) as document:
                self.tagged=document.xref_get_key(document.pdf_catalog(),'StructTreeRoot')[0]!='null'
            self._tagged_revision=tagged_revision
        page_caps={key:True for key in ('supported','delete','extract','reorder','rotate','duplicate','insert_blank','insert_pdf')}
        page_caps['reason']=''
        if not self._editing_prepared:
            page_caps={key:False for key in page_caps if key!='reason'}
            page_caps['reason']='Activa las herramientas para comprobar las operaciones disponibles.'
        elif self.issues:
            page_caps={key:False for key in page_caps if key!='reason'}
            page_caps['reason']='\n'.join(self.issues)
        elif self.tagged:
            candidate=self.pending if self.pending is not None else self.history.current
            digest=tagged_revision
            if digest not in self._page_caps_cache:
                from .tagged_pages import page_capabilities
                self._page_caps_cache[digest]=page_capabilities(candidate)
                while len(self._page_caps_cache)>6:self._page_caps_cache.popitem(last=False)
            page_caps=dict(self._page_caps_cache[digest])
        geometry_changed=self._geometry_changed_instances()
        special_only=False
        if self._editing_prepared and self.issues and self.history.index>0:
            from .forms_redaction_v200 import install_session_tools_v200
            install_session_tools_v200(Session)
            special_only=self.form_only_save_v200()
        return {'path':self.path,'session_id':self.session_id,'recovery_id':self.recovery_id,
                'recovered_draft':getattr(self,'recovered_draft',None),
                'workspace':self.workspace,'page_count':len(keys),'original_pages':[k if k>=0 else None for k in keys],'undo':self.history.index>0,
                'redo':self.history.index+1<len(self.history.states),'issues':self.issues,'tagged':self.tagged,
                'page_capabilities':page_caps,
                'document_revision':tagged_revision,
                'comparison_geometry_changed':[key in geometry_changed for key in self._instance_keys()],
                'preview':self.pending is not None,'dirty':current_digest!=self.saved_digest,
                'history_index':self.history.index,'history_dropped':self.history.dropped,
                'reading':not self._editing_prepared,'editing_prepared':self._editing_prepared,
                'copy_allowed':self.copy_allowed,
                'validation_pending':not self._editing_prepared,
                'metadata_only_save':bool(self.issues) and self._metadata_only_history(),
                'special_only_save':special_only}

    def _metadata_only_history(self):
        reports=[r for r in self.history.base_reports+self.history.reports[:self.history.index+1] if r]
        return bool(reports) and all(r.get('operation')=='document_metadata' for r in reports)

    def page(self,number,zoom=1.,original=False,thumbnail=False,reading=False):
        reading=bool(reading or not self._editing_prepared)
        data=self.original if original else (self.pending or self.history.current)
        keys=self._page_keys()
        if not 0<=number<len(keys):
            raise EditError('La página seleccionada ya no está en el documento.')
        source_number=keys[number] if original else number
        if source_number<0:
            raise EditError('Esta página se añadió al combinar PDFs y no existe en el original.')
        zoom=max(.1,min(float(zoom),4.))
        revision=self._revision(original)
        key=(revision,number,round(zoom,3),thumbnail,bool(original),reading)
        if key in self.cache:
            result=self.cache.pop(key)
            self.cache[key]=result
            return {**result,'state':self.state()}
        doc=self._document(data,revision)
        page=doc[source_number]
        if page.rect.width*page.rect.height*zoom*zoom>16_000_000:
            zoom=(16_000_000/(page.rect.width*page.rect.height))**.5
        display_key=(revision,source_number)
        if display_key in self._displaylists:
            display=self._displaylists.pop(display_key)
        else:display=page.get_displaylist(annots=1)
        self._displaylists[display_key]=display
        while len(self._displaylists)>4:self._displaylists.popitem(last=False)
        png=display.get_pixmap(matrix=fitz.Matrix(zoom,zoom),alpha=False,colorspace=fitz.csRGB).tobytes('png')
        model=None;fonts=[];images=[]
        if not thumbnail:
            model_key=(revision,source_number,reading)
            if model_key in self._model_cache:
                cached=self._model_cache.pop(model_key);self._model_cache[model_key]=cached
                model,fonts,images,_=cached
            else:
                model=extract_page(doc,source_number,None if reading or doc.needs_pass else data)
                if reading:model=replace(model,revision=revision)
                fonts=[] if reading else self.resolver.inspect(doc,source_number)
                if not reading:
                    from .media import image_items
                    images=image_items(doc,source_number)
                estimate=2048+len(model.glyphs)*512+len(fonts)*2048+len(images)*2048
                self._model_cache[model_key]=(model,fonts,images,estimate);self._model_bytes+=estimate
                while self._model_bytes>16*1024*1024 or len(self._model_cache)>12:
                    _,removed=self._model_cache.popitem(last=False);self._model_bytes-=removed[3]
        instance=self._instance_keys()[number]
        changes=self._instance_changes(original=original).get(instance,[])
        geometry_changed=instance in self._geometry_changed_instances()
        result={'png':png,'number':number,'zoom':zoom,'model':model,'fonts':fonts,'images':images,'changes':changes,
                'reading':reading,
                'comparison_geometry_changed':geometry_changed,
                'comparison_warning':('El recorte cambió el área visible. El original conserva sus dimensiones; los resaltados se muestran en las coordenadas de cada vista.' if geometry_changed else '')}
        self.cache[key]=result
        self.cache_bytes+=len(png)
        while self.cache_bytes>32*1024*1024 or len(self.cache)>12:
            _,removed=self.cache.popitem(last=False)
            self.cache_bytes-=len(removed['png'])
        return {**result,'state':self.state()}

    def preview(self,request):
        self._require_editing()
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

    def rich_selection(self,page,ids):
        self._require_editing()
        from .richtext import selection_payload
        if self.issues:raise EditError('\n'.join(self.issues))
        payload=selection_payload(self.history.current,page,ids,self.resolver)
        catalog=getattr(self,'_rich_catalog',None)
        if catalog is None:
            catalog=self.resolver.catalog()
            for entry in catalog:
                if entry.get('source')=='Base14':
                    face=self.resolver.resolve_explicit(entry['name'],'')
                    entry['buffer']=bytes(face.font.buffer)
            self._rich_catalog=catalog
        payload['catalog']=catalog
        payload.update(page=page,ids=ids)
        return payload

    def rich_preview(self,request,zoom=1.25,apply=False,prepare=False):
        """Live previews use final export bytes, without replacing session state."""
        from .richtext import edit_rich_pdf
        from .richmodels import RichTextRequest
        self._writable()
        if isinstance(request,dict):request=RichTextRequest(**request)
        candidate,report=edit_rich_pdf(self.history.current,request,self.resolver)
        report.update(page=request.page,operation='rich_text')
        self._mark_page_edit(report,request.page)
        if prepare:
            token=uuid.uuid4().hex
            self._prepared_rich=(token,self.history.revision,candidate,report)
            return {'token':token,'report':report,'state':self.state()}
        if apply:
            self._put_preview(candidate,report)
            return self.commit()
        with self._open(candidate) as doc:
            page=doc[request.page]
            scale=max(.1,min(float(zoom),4.))
            if page.rect.width*page.rect.height*scale*scale>16_000_000:
                scale=(16_000_000/(page.rect.width*page.rect.height))**.5
            png=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False,colorspace=fitz.csRGB).tobytes('png')
        return {'png':png,'report':report,'zoom':scale,'state':self.state()}

    def rich_commit(self,token):
        self._writable()
        prepared=getattr(self,'_prepared_rich',None)
        if not prepared or prepared[0]!=token or prepared[1]!=self.history.revision:
            raise EditError('La edición preparada ya no corresponde al documento actual. Repite la aceptación.')
        self._prepared_rich=None
        self._put_preview(prepared[2],prepared[3])
        return self.commit()

    def object_info(self,page):
        from .objects import object_info
        return object_info(self.history.current,page)

    def object_operation(self,page,operation,items=None,**kwargs):
        self._writable()
        from .objects import group_pdf,transform_objects_pdf
        if operation=='group':
            candidate,report=group_pdf(self.history.current,page,items,**kwargs)
        else:
            candidate,report=transform_objects_pdf(self.history.current,page,items,operation,**kwargs)
        self._mark_page_edit(report,page)
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
                        replacement_bytes=None,crop=None,rotation=0,fit_mode=None,
                        flip_horizontal=False,flip_vertical=False,
                        accessibility_order=None,alt_text=None,decorative=False):
        self._writable()
        from .media import add_image_pdf,transform_image_pdf,delete_image_pdf
        if operation=='add':
            candidate,report=add_image_pdf(self.history.current,page,image_bytes,rect,revision=revision,
                accessibility_order=accessibility_order,alt_text=alt_text,decorative=decorative)
        elif operation=='transform':
            from .image_transform_v160 import transform_image_instance_pdf
            candidate,report=transform_image_instance_pdf(self.history.current,page,image_id,rect,revision=revision)
        elif operation=='rotate':
            from .image_transform_v160 import transform_image_instance_pdf
            candidate,report=transform_image_instance_pdf(self.history.current,page,image_id,
                                                        revision=revision,rotation=rotation)
        elif operation=='delete':
            candidate,report=delete_image_pdf(self.history.current,page,image_id,revision=revision)
        elif operation=='edit':
            from .media import edit_image_pdf
            candidate,report=edit_image_pdf(self.history.current,page,image_id,replacement_bytes=replacement_bytes,
                                           crop=crop,rotation=rotation,revision=revision,fit_mode=fit_mode,
                                           flip_horizontal=flip_horizontal,flip_vertical=flip_vertical)
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
        self._require_editing()
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

    def preview_replace_pages_v150(self,expression,path,source_expression):
        self._writable()
        from .pageops import parse_pages
        from .page_tools_v150 import replace_pages_pdf
        source_path=Path(path).resolve()
        addition=source_path.read_bytes()
        pages=parse_pages(expression,len(self._page_keys(False)))
        try:
            with fitz.open(stream=addition,filetype='pdf') as doc:
                sources=parse_pages(source_expression,doc.page_count)
        except EditError:
            raise
        except Exception as exc:
            raise EditError('No se puede abrir el PDF de sustitución.') from exc
        candidate,report=replace_pages_pdf(self.history.current,pages,addition,sources)
        keys=self._page_keys(False)
        instances=self._instance_keys(False)
        next_key=min(keys+[0])-1
        for number in pages:
            keys[number]=next_key;next_key-=1
            instances[number]=uuid.uuid4().hex
        report.update(_page_keys=keys,_instance_keys=instances)
        self.protected_paths.add(str(source_path))
        return self._put_preview(candidate,report)

    def preview_crop_pages_v150(self,expression,margins):
        self._writable()
        from .pageops import parse_pages
        from .page_tools_v150 import crop_pages_pdf
        pages=parse_pages(expression,len(self._page_keys(False)))
        candidate,report=crop_pages_pdf(self.history.current,pages,margins)
        instances=self._instance_keys(False)
        shifts={instances[box['page']]:(box['before'][0]-box['after'][0],
                                       box['before'][1]-box['after'][1])
                for box in report['crop_boxes']}
        changed=[instances[box['page']] for box in report['crop_boxes'] if box['before']!=box['after']]
        report.update(_page_keys=self._page_keys(False),_instance_keys=instances,
                      _region_translations=shifts,_geometry_changed_instances=changed)
        return self._put_preview(candidate,report)

    def split_document_v150(self,destination,expression=None,pages_per_part=None):
        self._writable()
        from .page_tools_v150 import parse_split_groups,split_pdf
        from .export_v150 import ExportError,_destination,_file_report,_publish,_stage
        self._safe_destination(destination)
        folder=_destination(destination,'png')  # Same checked directory contract.
        groups=None if expression is None else parse_split_groups(expression,len(self._page_keys(False)))
        outputs,report=split_pdf(self.history.current,page_groups=groups,pages_per_part=pages_per_part)
        targets=[folder/f'parte-{number+1:03d}.pdf' for number in range(len(outputs))]
        for target in targets:
            self._safe_destination(target)
            if os.path.lexists(target):
                raise EditError(f'El destino ya existe; elige otra carpeta: {target}')
        staged=[];published=[];files=[]
        try:
            folder.mkdir(exist_ok=True)
            for data,target in zip(outputs,targets):
                temporary=_stage(folder,lambda stream,payload=data:stream.write(payload))
                staged.append(temporary)
                files.append(_file_report(temporary,target))
            for temporary,target in zip(staged,targets):
                _publish(temporary,target)
                published.append(str(target))
        except Exception as exc:
            raise ExportError(f'No se pudo completar la división: {exc}',published) from exc
        finally:
            for temporary in staged:temporary.unlink(missing_ok=True)
        report.update(files=files,atomic_per_file=True)
        return {'destination':str(folder),'files':files,'report':report,'state':self.state()}

    def export_document_v150(self,destination,format,pages=None,dpi=144):
        self._writable()
        self._safe_destination(destination)
        from .export_v150 import export_document
        if isinstance(pages,str):
            from .pageops import parse_pages
            pages=parse_pages(pages,len(self._page_keys(False)))
        report=export_document(self.history.current,destination,format,pages,dpi)
        return {'destination':report['destination'],'files':report['files'],
                'report':report,'state':self.state()}

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
        self._require_editing()
        if self.pending is None:
            raise EditError('No hay una previsualización validada para aplicar.')
        report=self.pending_report
        previous_draft=self.history.metadata.get('draft')
        self.history.metadata['draft']=None
        try:self.history.push(self.pending,report)
        except Exception:
            self.history.metadata['draft']=previous_draft;raise
        self.recovered_draft=None
        self.pending=self.pending_report=None
        self._clear_cache()
        self.page_count=len(self._page_keys(False))
        return {'state':self.state(),'report':report}

    def cancel(self):
        if self.pending is not None or self.history.metadata.get('draft'):
            self.history.checkpoint({'saved_digest':self.saved_digest,'draft':None})
        self.recovered_draft=None
        self.pending=self.pending_report=None
        self._clear_cache()
        return {'state':self.state()}

    def navigate_history(self,redo=False):
        self.cancel()
        self.history.redo() if redo else self.history.undo()
        self.page_count=len(self._page_keys(False))
        return {'state':self.state()}

    def save(self,path):
        self._require_editing()
        if self.issues:
            from .forms_redaction_v200 import install_session_tools_v200
            install_session_tools_v200(Session)
            if self.form_only_save_v200():
                result=self.save_form_v200(path)
                self.saved_digest=self.history.revision
                try:self._checkpoint()
                except OSError:result['notice']='PDF guardado; no se pudo actualizar la recuperación local.'
                result['state']=self.state();return result
        metadata_only=bool(self.issues) and self._metadata_only_history()
        if self.issues and not metadata_only:
            raise EditError('\n'.join(self.issues))
        if self.pending is not None:
            raise EditError('Aplica o cancela la previsualización antes de guardar.')
        self._safe_destination(path)
        if metadata_only:
            from .document_ops_v170 import save_metadata_snapshot
            result=save_metadata_snapshot(self.history.current,path,protected_paths=self.protected_paths)
        else:
            result=atomic_save(self.history.current,path,self.path)
        self.saved_digest=self.history.revision
        try:self._checkpoint()
        except OSError:
            # The PDF was saved successfully; retain work and report the recovery issue.
            return {'path':result,'state':self.state(),'notice':'PDF guardado; no se pudo actualizar el borrador de recuperación local.'}
        return {'path':result,'state':self.state()}

    def signing_pages(self):
        """Displayed CropBox sizes for placement; engine documents stay in worker."""
        with self._open(self.history.current) as document:
            return [{'page':p.number,'width':p.rect.width,'height':p.rect.height}
                    for p in document]

    def signature_preview(self, **payload):
        self._writable()
        from .signing import preview_signature
        return preview_signature(self.history.current, **payload)

    def sign_pdf(self,path,certificate_path='',password='',reason='',location='',
                 certificate_thumbprint='',certificate_store='CurrentUser',visible_signature=None):
        """Export the committed snapshot; signed bytes never enter edit history."""
        self._writable()
        self._safe_destination(path)
        from .signing import sign_pdf, atomic_save_signed
        # The destination may not overwrite the certificate either.
        protected = list(self.protected_paths)
        target = Path(path).resolve()
        if certificate_path:
            protected.append(certificate_path)
            certificate = Path(certificate_path).resolve()
            if target == certificate or (target.exists() and certificate.exists() and os.path.samefile(target,certificate)):
                raise EditError('La copia PDF no puede sobrescribir el certificado seleccionado.')
        try:
            signed, report = sign_pdf(self.history.current, certificate_path, password,
                                      reason=reason, location=location,
                                      certificate_thumbprint=certificate_thumbprint,
                                      certificate_store=certificate_store,
                                      visible_signature=visible_signature)
            output = atomic_save_signed(signed,path,protected_paths=protected,
                                        certificate_sha256=report['certificate_sha256'])
        finally:
            password = None
        return {'path':output,'signature':report,'state':self.state()}

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
        self._require_editing()
        self.resolver.associate(name,path)
        self._clear_cache()
        return {'state':self.state()}

    def font_evidence(self,page,ids,revision,original=False):
        self._require_editing()
        data=self.original if original else (self.pending or self.history.current)
        if revision!=self._revision(original):
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
        self._cleanup_print()
        self._close_documents()
        self.history.close()


_session=None
_sessions=OrderedDict()


def _activate(identifier):
    global _session
    if identifier not in _sessions:raise EditError('El documento seleccionado ya no está abierto.')
    new=_sessions[identifier]
    if _session is not new:
        if _session:_session.suspend()
        new.resume();_session=new
    return new


def _attach(new,retain_existing=False):
    global _session
    if new.session_id in _sessions:raise EditError('El identificador del documento ya está abierto.')
    if retain_existing:
        if _session:_session.suspend()
    else:
        for old in list(_sessions.values()):old.close()
        if _session and _session not in _sessions.values():_session.close()
        _sessions.clear()
    _sessions[new.session_id]=new;_session=new


def _install_v200_tools(command):
    # Imported only on use; the reader needs neither form/redaction nor printing dependencies.
    if command in ('form_fields_v200','preview_form_v200','preview_redaction_v200','save_form_v200','redaction_page_v200'):
        from .forms_redaction_v200 import install_session_tools_v200
        install_session_tools_v200(Session)
    else:
        from .editor_tools_v200 import install_editor_tools_v200
        install_editor_tools_v200(Session)


def dispatch(command,payload=None):
    """ProcessPoolExecutor(max_workers=1, spawn) invokes this serially."""
    global _session
    payload=dict(payload or {})
    if command=='list_recovery':
        from .recovery_v200 import list_recovery
        return list_recovery(payload.get('recovery_root'),exclude=[s.recovery_id for s in _sessions.values()])
    if command=='discard_recovery':
        from .recovery_v200 import discard_recovery
        identifier=payload['recovery_id']
        if any(s.recovery_id==identifier for s in _sessions.values()):raise EditError('Cierra el documento antes de descartar su recuperación.')
        return discard_recovery(identifier,payload.get('recovery_root'))
    if command=='recover':
        retain=payload.pop('retain_existing',False)
        identifier=payload.pop('recovery_id')
        existing=next((s for s in _sessions.values() if s.recovery_id==identifier),None)
        if existing:return {'state':_activate(existing.session_id).state()}
        new=Session.recover(identifier,**payload);_attach(new,retain)
        return {'state':new.state()}
    if command=='list_sessions':
        return {'sessions':[{'session_id':s.session_id,'path':s.path,
            'dirty':s.history.revision!=s.saved_digest,'preview':bool(s.pending is not None or getattr(s,'_suspended_pending',False)),
            'reading':not s._editing_prepared,'active':s is _session} for s in _sessions.values()]}
    if command=='close_all':
        for current in list(_sessions.values()):current.close()
        if _session and _session not in _sessions.values():_session.close()
        _sessions.clear();_session=None;return {}
    if command not in ('open','combine') and 'session_id' in payload:
        _activate(payload.pop('session_id'))
    if command=='activate_session':return {'state':_session.state()} if _session else {}
    if command=='close_session':command='close'
    if command=='list_encryption_certificates':
        from .document_ops_v170 import list_encryption_certificates
        return list_encryption_certificates()
    if command=='list_signing_certificates':
        from .signing import list_signing_certificates
        result=list_signing_certificates()
        if _session is not None:
            result['pages']=_session.signing_pages()
            result['visible_signature_error']=(
                'Este PDF está etiquetado. Puedes firmarlo sin sello visible; añadir el sello '
                'requiere integrar su campo en la estructura accesible.' if _session.tagged else '')
        return result
    if command=='font_catalog':
        if _session is not None and not _session._editing_prepared:
            return {'catalog':[],'reading':True}
        return {'catalog':(_session.resolver if _session else FontResolver()).catalog()}
    if command=='combine':
        paths=payload.get('paths',[])
        if len(paths)<2:
            raise EditError('Selecciona al menos dos archivos PDF para combinar.')
        new=Session(paths[0],config_path=payload.get('config_path'),history_dir=payload.get('history_dir'),
                    recovery_root=payload.get('recovery_root'),session_id=payload.get('session_id'))
        try:
            result=new.merge(paths[1:])
        except Exception:
            new.close()
            raise
        _attach(new,payload.get('retain_existing',False))
        return result
    if command=='open':
        retain=payload.pop('retain_existing',False)
        new=Session(**payload)
        _attach(new,retain)
        return {'state':new.state()}
    if _session is None:
        raise EditError('Abre primero un PDF.')
    if command=='update_workspace':return _session.update_workspace(**payload)
    if command=='store_draft':return _session.store_draft(**payload)
    if command in ('form_fields_v200','preview_form_v200','preview_redaction_v200','save_form_v200','redaction_page_v200',
                   'selection_capabilities_v200','cell_selection_v200','print_pages_v200','snapshot_v200'):
        _install_v200_tools(command)
        if command=='save_form_v200' and not _session.form_only_save_v200():
            raise EditError('El historial contiene otras operaciones; utiliza Guardar como para comprobarlas.')
        return getattr(_session,command)(**payload)
    if command=='prepare_editing':return _session.prepare_editing(**payload)
    if command=='reading_info':return {**_session.reading_info(**payload),'state':_session.state()}
    if command=='reading_copy_range':return _session.reading_copy_range(**payload)
    if command=='remove_tags':
        _session._require_editing()
        if _session.issues:raise EditError('\n'.join(_session.issues))
        if _session.pending is not None:raise EditError('Aplica o cancela la vista previa anterior.')
        from .untag_v180 import remove_tags
        candidate,report=remove_tags(_session.history.current,password=_session.password)
        return _session._put_preview(candidate,report)
    # Engines retain their own document-specific checks. This guard prevents
    # any mutation/export route from using the deliberately unchecked reader.
    if command in ('clipboard_apply','edit_document_metadata','export_secure_pdf',
                   'preview','rich_selection','rich_preview','rich_apply','rich_prepare','rich_commit',
                   'object_info','object_operation','insert_text','image','export_image',
                   'find_replacements','preview_replacements','review_page','organizer_info','organizer_thumbnail',
                   'organize_pages','image_apply','delete_pages','extract_pages','preview_replace_pages_v150',
                   'preview_crop_pages_v150','split_document_v150','export_document_v150','merge',
                   'commit','apply','save','sign_pdf','signature_preview','associate','font_evidence'):
        _session._require_editing()
    if command=='document_properties':
        from .document_ops_v170 import document_properties
        return document_properties(_session.history.current,_session.path,password=_session.password)
    if command=='clipboard_copy':
        if not _session._editing_prepared:
            return _session.copy_reading_selection(**payload)
        from .clipboard_ops_v170 import copy_selection_v170
        return copy_selection_v170(_session,**payload)
    if command=='clipboard_apply':
        from .clipboard_ops_v170 import apply_clipboard_v170
        return apply_clipboard_v170(_session,**payload)
    if command=='edit_document_metadata':
        if _session.pending is not None:
            raise EditError('Aplica o cancela la vista previa antes de modificar las propiedades.')
        from .document_ops_v170 import update_document_metadata
        candidate,report=update_document_metadata(_session.history.current,payload['metadata'],password=_session.password)
        return _session._put_preview(candidate,report)
    if command=='export_secure_pdf':
        if _session.pending is not None:
            raise EditError('Aplica o cancela la vista previa antes de exportar una copia protegida.')
        _session._safe_destination(payload['path'])
        from .document_ops_v170 import export_secure_pdf
        result=export_secure_pdf(_session.history.current,source_password=_session.password,
                                 protected_paths=_session.protected_paths,**payload)
        return {**result,'state':_session.state()}
    if command=='page': return _session.page(**payload)
    if command=='preview': return _session.preview(payload['request'])
    if command=='rich_selection': return _session.rich_selection(**payload)
    if command=='rich_preview': return _session.rich_preview(**payload)
    if command=='rich_apply': return _session.rich_preview(**payload,apply=True)
    if command=='rich_prepare': return _session.rich_preview(**payload,prepare=True)
    if command=='rich_commit': return _session.rich_commit(**payload)
    if command=='object_info': return _session.object_info(**payload)
    if command=='object_operation': return _session.object_operation(**payload)
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
    if command=='preview_replace_pages_v150': return _session.preview_replace_pages_v150(**payload)
    if command=='preview_crop_pages_v150': return _session.preview_crop_pages_v150(**payload)
    if command=='split_document_v150': return _session.split_document_v150(**payload)
    if command=='export_document_v150': return _session.export_document_v150(**payload)
    if command=='merge': return _session.merge(payload['paths'])
    if command=='commit': return _session.commit()
    if command=='cancel': return _session.cancel()
    if command=='apply':
        _session.preview(payload['request'])
        return _session.commit()
    if command=='undo': return _session.navigate_history()
    if command=='redo': return _session.navigate_history(True)
    if command=='save': return _session.save(payload['path'])
    if command=='sign_pdf': return _session.sign_pdf(**payload)
    if command=='signature_preview': return _session.signature_preview(**payload)
    if command=='search': return _session.search(payload['text'])
    if command=='associate': return _session.associate(**payload)
    if command=='font_evidence': return _session.font_evidence(**payload)
    if command=='close':
        _sessions.pop(_session.session_id,None)
        _session.close()
        _session=None
        return {}
    raise EditError(f'Comando desconocido: {command}')
