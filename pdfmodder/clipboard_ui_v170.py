"""Clipboard actions with native input priority and PDF object placement."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QEvent, QMimeData, QByteArray, QBuffer, QIODevice, QTimer
from PySide6.QtGui import QImage, QAction, QTextCursor
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit, QTextEdit, QPlainTextEdit, QMenu

from .model import pt
from .clipboard_formats_v200 import clipboard_has_paste_v200
from .action_state_v310 import set_ui_enabled_v310

MIME_V170='application/x-pdfmodder-object-v1'
MAX_BUNDLE_BYTES=64*1024*1024


def _json_value(value):
    if isinstance(value,bytes):return {'$pdfmodder_bytes':base64.b64encode(value).decode('ascii')}
    if isinstance(value,dict):return {str(k):_json_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_json_value(v) for v in value]
    return value


def _decode_value(value):
    if isinstance(value,dict):
        if set(value)=={'$pdfmodder_bytes'}:
            return base64.b64decode(value['$pdfmodder_bytes'],validate=True)
        return {k:_decode_value(v) for k,v in value.items()}
    if isinstance(value,list):return [_decode_value(v) for v in value]
    return value


def bundle_mime_v170(payload):
    """Publish one object and its interoperable plain text/image representation."""
    mime=QMimeData()
    encoded=json.dumps(_json_value(payload['bundle']),ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(encoded)>MAX_BUNDLE_BYTES:raise ValueError('El objeto supera el límite de 64 MB del portapapeles.')
    mime.setData(MIME_V170,QByteArray(encoded))
    if 'text' in payload:mime.setText(payload['text'].replace('\u2028','\n'))
    if payload.get('image_bytes'):
        image=QImage.fromData(payload['image_bytes'])
        if image.isNull():raise ValueError('No se pudo publicar la imagen en el portapapeles.')
        mime.setImageData(image.copy())
    return mime


def mime_bundle_v170(mime):
    if not mime.hasFormat(MIME_V170):return None
    raw=bytes(mime.data(MIME_V170))
    if len(raw)>MAX_BUNDLE_BYTES:raise ValueError('El objeto del portapapeles supera el límite permitido.')
    try:
        value=_decode_value(json.loads(raw.decode('utf-8')))
    except (ValueError,TypeError,UnicodeError) as exc:
        raise ValueError('El objeto de PDFModder del portapapeles está dañado. Copia de nuevo.') from exc
    if not isinstance(value,dict) or value.get('version')!=1 or value.get('kind') not in ('text','image'):
        raise ValueError('El objeto del portapapeles no es compatible. Copia de nuevo.')
    return value


class ClipboardUiV170Mixin:
    def _create_clipboard_ui_v170(self):
        self._clipboard_placement_v170=None
        self._clipboard_menu_v170=None
        self._init_fast_clipboard_v318()
        for attr,label,operation,key in (
                ('copy_action_v170','Copiar','copy','Ctrl+C'),
                ('cut_action_v170','Cortar','cut','Ctrl+X'),
                ('paste_action_v170','Pegar','paste','Ctrl+V'),
                ('delete_action_v170','Eliminar','delete','Supr')):
            action=QAction(label,self);action.setObjectName(attr)
            action.setToolTip(f'{label} texto o imagen · {key}')
            action.triggered.connect(lambda checked=False,op=operation:self._clipboard_command_v170(op))
            setattr(self,attr,action);self.toolbar.addAction(action)
            try:
                from .ui_icons_v170 import icon_v170
                action.setIcon(icon_v170(operation))
            except ImportError:pass
        # These replace the previous preview-only Delete routes. The keyboard
        # filter also prevents Delete from reaching the canvas twice.
        for signal in (self.canvas.delete_requested,self.canvas.image_delete_requested):
            signal.disconnect()
            signal.connect(lambda *args:self.clipboard_delete_v170())
        if hasattr(self.canvas,'text_context_requested'):
            self.canvas.text_context_requested.connect(self.text_context_v170)
        application=QApplication.instance()
        application.clipboard().dataChanged.connect(self._clipboard_changed_v318)
        application.focusChanged.connect(self._clipboard_focus_changed_v170)
        # AdvancedEditing installs the same window as an application filter.
        # Installing once more moves it last without creating a duplicate.
        application.installEventFilter(self)
        self._refresh_clipboard_v170()

    def _init_fast_clipboard_v318(self):
        self._clipboard_epoch_v318=0
        self._clipboard_own_write_v318=False
        self._clipboard_pending_v318=None
        self._clipboard_paste_pending_v318=None
        self._clipboard_copy_timer_v318=QTimer(self)
        self._clipboard_copy_timer_v318.setSingleShot(True)
        self._clipboard_copy_timer_v318.setInterval(40)
        self._clipboard_copy_timer_v318.timeout.connect(self._enrich_clipboard_v318)
        if hasattr(self,'error_raised'):
            self.error_raised.connect(self._clipboard_failed_v318)

    def _clipboard_changed_v318(self):
        # Never retrieve external clipboard data here: Windows OLE providers
        # may block. An ownership epoch also protects delayed enrichment from
        # overwriting a later copy in this application or another program.
        self._clipboard_epoch_v318+=1
        if not self._clipboard_own_write_v318:
            self._clipboard_pending_v318=None
            self._clipboard_paste_pending_v318=None
        self._refresh_clipboard_v170()

    def _publish_clipboard_v318(self,mime):
        self._clipboard_own_write_v318=True
        try:QApplication.clipboard().setMimeData(mime)
        finally:self._clipboard_own_write_v318=False

    def _clipboard_failed_v318(self,*_):
        pending=self._clipboard_pending_v318
        if pending and pending.get('started') and self._command=='clipboard_copy':
            self._clipboard_pending_v318=None
            self._clipboard_paste_pending_v318=None

    def _plain_copy_ready_v318(self):
        model=getattr(self,'model',None)
        state=getattr(self,'state',{})
        canvas=self.canvas
        safe_read=not self.busy or getattr(self,'_render_busy_v310',lambda:False)()
        return bool(model and state.get('copy_allowed',False) and safe_read
            and state.get('document_revision')==model.revision
            and getattr(canvas,'model',None) is model and model.number==self.page_number
            and not state.get('preview') and not self.compare_action.isChecked()
            and not canvas.editor.isVisible() and not getattr(self,'_rich_loading',False)
            and not getattr(self,'_rich_active',False)
            and not getattr(self,'_navigation_pending_v310',lambda:False)()
            and not canvas.selected_image())

    def _copy_plain_v318(self):
        if not self._plain_copy_ready_v318() or not self.canvas.ids:return False
        selected=self.model.selected(self.canvas.ids)
        if (len(selected)!=len(set(self.canvas.ids)) or not selected
                or any(g.mode==3 or g.opacity<=0 for g in selected)):
            return False
        text=self.model.text(self.canvas.ids).replace('\u2028','\n')
        if not text:return False
        payload=self._clipboard_selection_v170()
        mime=QMimeData();mime.setText(text)
        self._publish_clipboard_v318(mime)
        self._clipboard_pending_v318={
            'epoch':self._clipboard_epoch_v318,'payload':payload,
            'session':getattr(self,'_active_session_v200',None),'started':False}
        self._clipboard_paste_pending_v318=None
        self._clipboard_copy_timer_v318.start()
        self._notice('Texto copiado. Preparando el formato editable en segundo plano…')
        return True

    def _enrich_clipboard_v318(self):
        pending=self._clipboard_pending_v318
        if not pending or pending['started']:return
        if getattr(self,'_closed',False):
            self._clipboard_pending_v318=None;return
        if (pending['epoch']!=self._clipboard_epoch_v318
                or pending['session']!=getattr(self,'_active_session_v200',None)
                or pending['payload']['revision']!=self.state.get('document_revision')):
            self._clipboard_pending_v318=None
            self._clipboard_paste_pending_v318=None
            return
        # Clipboard enrichment must yield to a foreground dialog/gesture. A
        # queued read starting inside a modal event loop can otherwise occupy
        # the single worker exactly when that dialog accepts a modification.
        if (self.busy or QApplication.activeModalWidget() is not None
                or getattr(self,'_ui_mutation_locked_v310',lambda:False)()
                or getattr(self.canvas,'pointer_gesture_pending',lambda:False)()):
            self._clipboard_copy_timer_v318.start();return
        if not self.state.get('copy_allowed',False):
            self._clipboard_pending_v318=None
            self._clipboard_paste_pending_v318=None
            return
        def copied(result):
            if (self._clipboard_pending_v318 is not pending
                    or pending['epoch']!=self._clipboard_epoch_v318):return
            try:mime=bundle_mime_v170(result)
            except (ValueError,TypeError,RuntimeError) as exc:
                self._clipboard_pending_v318=None
                self._clipboard_paste_pending_v318=None
                self._error(str(exc));return
            self._publish_clipboard_v318(mime)
            self._clipboard_pending_v318=None
            queued,self._clipboard_paste_pending_v318=self._clipboard_paste_pending_v318,None
            if queued:
                sid,revision,page,point=queued
                if (sid==getattr(self,'_active_session_v200',None)
                        and revision==self.state.get('document_revision') and page==self.page_number):
                    self.clipboard_paste_v170(point)
                else:self._notice('El destino cambió. Vuelve a pulsar Pegar.')
        request=dict(pending['payload'],_background_ui=True)
        if pending['session'] is not None:request['session_id']=pending['session']
        pending['started']=bool(self._submit('clipboard_copy',request,copied))
        if not pending['started']:self._clipboard_copy_timer_v318.start()

    def _clipboard_focus_changed_v170(self,old,new):
        if not getattr(self,'_closed',False):self._refresh_clipboard_v170()

    def _native_clipboard_target_v170(self):
        target=QApplication.focusWidget()
        if isinstance(target,(QLineEdit,QTextEdit,QPlainTextEdit)) and target.window() is self:
            return target
        return None

    def _native_clipboard_v170(self,operation):
        target=self._native_clipboard_target_v170()
        if target is None:return False
        if operation=='delete':
            if target.isReadOnly():return True
            if isinstance(target,QLineEdit):target.del_()
            else:
                cursor=target.textCursor();cursor.removeSelectedText() if cursor.hasSelection() else cursor.deleteChar()
                target.setTextCursor(cursor)
        elif operation=='copy' or not target.isReadOnly():
            getattr(target,operation)()
        return True

    def _clipboard_command_v170(self,operation):
        if self._native_clipboard_v170(operation):return
        getattr(self,'clipboard_'+operation+'_v170')()

    def _clipboard_ready_v170(self,editing=False):
        return bool(self.model and self.state and not self.busy and not self.state.get('preview')
            and not self.compare_action.isChecked() and not self.canvas.editor.isVisible()
            and not getattr(self,'_rich_loading',False) and (not editing or not self.state.get('issues')))

    def _refresh_clipboard_v170(self):
        if getattr(self,'_closed',False):return
        if not hasattr(self,'copy_action_v170'):return
        target=self._native_clipboard_target_v170()
        has_paste=clipboard_has_paste_v200()
        if target is not None:
            has_selection=target.hasSelectedText() if isinstance(target,QLineEdit) else target.textCursor().hasSelection()
            writable=not target.isReadOnly()
            set_ui_enabled_v310(self, self.copy_action_v170, has_selection)
            set_ui_enabled_v310(self, self.cut_action_v170, writable and has_selection)
            set_ui_enabled_v310(self, self.paste_action_v170, writable and has_paste)
            set_ui_enabled_v310(self, self.delete_action_v170, writable)
            return
        image=self.canvas.selected_image()
        selected=bool(self.canvas.ids or image)
        ready=self._clipboard_ready_v170()
        editable=self._clipboard_ready_v170(True)
        fast_ready=bool(getattr(self,'model',None) and self._plain_copy_ready_v318())
        set_ui_enabled_v310(self, self.copy_action_v170, (ready or fast_ready) and selected)
        set_ui_enabled_v310(self, self.cut_action_v170, editable and selected and (not image or image.get('editable')))
        set_ui_enabled_v310(self, self.delete_action_v170, editable and selected and (not image or image.get('editable')))
        set_ui_enabled_v310(self, self.paste_action_v170, editable and has_paste)

    def eventFilter(self,obj,event):
        if event.type()==QEvent.KeyPress and isinstance(obj,QWidget) and obj.window() is self:
            modifiers=event.modifiers()
            operation=None
            if modifiers==Qt.ControlModifier:
                operation={Qt.Key_C:'copy',Qt.Key_X:'cut',Qt.Key_V:'paste'}.get(event.key())
            elif modifiers==Qt.NoModifier and event.key()==Qt.Key_Delete:operation='delete'
            if operation:
                if self._native_clipboard_target_v170() is not None:
                    return super().eventFilter(obj,event)
                # Page lists and non-document controls keep their own keyboard
                # behavior. PDF shortcuts belong to the focused canvas.
                if obj is self.canvas or obj is self.canvas.viewport() or self.canvas.isAncestorOf(obj):
                    self._clipboard_command_v170(operation);event.accept();return True
        return super().eventFilter(obj,event)

    def _clipboard_selection_v170(self):
        payload={'page':self.page_number,'revision':self.model.revision}
        image=self.canvas.selected_image()
        if image:payload['image_id']=image['id']
        else:payload['ids']=self.canvas.ids[:]
        return payload

    def clipboard_copy_v170(self):self._copy_object_v170(False)
    def clipboard_cut_v170(self):self._copy_object_v170(True)

    def _copy_object_v170(self,cut):
        if self._native_clipboard_v170('cut' if cut else 'copy'):return
        if not cut and self._copy_plain_v318():return
        if not self._clipboard_ready_v170(cut) or not (self.canvas.ids or self.canvas.selected_image()):return
        payload=self._clipboard_selection_v170()
        source_session=getattr(self,'_active_session_v200',None)
        def copied(result):
            if (not self.model or source_session!=getattr(self,'_active_session_v200',None)
                    or payload!=self._clipboard_selection_v170()):return
            try:
                mime=bundle_mime_v170(result)
                QApplication.clipboard().setMimeData(mime)
                installed=mime_bundle_v170(QApplication.clipboard().mimeData())
                if installed is None:raise ValueError('No se pudo guardar el objeto en el portapapeles.')
            except (ValueError,TypeError,RuntimeError) as exc:
                self._error(str(exc));return
            if cut:
                if not installed.get('portable',False):
                    self._error('El texto se ha copiado, pero no se ha cortado porque la fuente no permite garantizar su recuperación. '
                                +str(installed.get('font_error',''))+' Importa y asocia la fuente exacta antes de cortar.')
                    return
                deletion=dict(payload,operation='delete')
                if source_session is not None:deletion['session_id']=source_session
                self._submit('clipboard_apply',deletion,self._edited)
            else:
                self._notice('Objeto copiado. Pegar permite elegir su posición en la página. '+result.get('notice',''))
        self._submit('clipboard_copy',payload,copied)

    def clipboard_delete_v170(self):
        if self._native_clipboard_v170('delete'):return
        if not self._clipboard_ready_v170(True) or not (self.canvas.ids or self.canvas.selected_image()):return
        self._submit('clipboard_apply',dict(self._clipboard_selection_v170(),operation='delete'),self._edited)

    def _external_clipboard_v170(self,mime):
        if mime.hasImage():
            image=QImage(mime.imageData())
            storage=QByteArray();buffer=QBuffer(storage);buffer.open(QIODevice.WriteOnly)
            if image.isNull() or not image.save(buffer,'PNG'):raise ValueError('La imagen del portapapeles no se puede leer.')
            ratio=image.width()/image.height();width=pt(60)
            return {'version':1,'kind':'image','image_bytes':bytes(storage),'rect':(0,0,width,width/ratio),'portable':True}
        if mime.hasText() and mime.text().strip():
            root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
            font=root/'assets/fonts/LiberationSans-Regular.ttf'
            if not font.is_file():raise ValueError('Falta la fuente Liberation Sans para texto nuevo. Elige una fuente explícita en Agregar texto.')
            return {'version':1,'kind':'plain_text','text':mime.text().replace('\r\n','\n').replace('\r','\n'),
                    'font_name':'LiberationSans','font_file':str(font),'rect':(0,0,pt(75),pt(30)),'portable':True}
        raise ValueError('El portapapeles no contiene texto o una imagen para pegar.')

    def clipboard_paste_v170(self,point=None):
        if self._native_clipboard_v170('paste'):return
        pending=getattr(self,'_clipboard_pending_v318',None)
        if pending and pending['epoch']==self._clipboard_epoch_v318:
            # Waiting for the portable object keeps an immediate in-app paste
            # from silently substituting a different font or losing styles.
            if (self._plain_copy_ready_v318() and not self.state.get('issues')
                    and getattr(self,'application_mode','editing')=='editing'):
                self._clipboard_paste_pending_v318=(getattr(self,'_active_session_v200',None),
                    self.state.get('document_revision'),self.page_number,point)
                self._notice('Preparando el formato del texto para pegar…')
            return
        if not self._clipboard_ready_v170(True):return
        try:
            mime=QApplication.clipboard().mimeData()
            bundle=mime_bundle_v170(mime) or self._external_clipboard_v170(mime)
        except (ValueError,TypeError,RuntimeError) as exc:
            self._error(str(exc));return
        self._clipboard_placement_v170=deepcopy(bundle)
        if point is not None:
            self._place_clipboard_v170(*point);return
        self._placement='clipboard_v170';self.canvas.placement_mode=True;self.canvas.setCursor(Qt.CrossCursor)
        message='Pulsa en la página para pegar el objeto editable. Escape cancela.'
        if bundle['kind']=='plain_text':message+=' Texto sin formato: Liberation Sans, 12 pt.'
        self._notice(message);self._refresh_actions()

    def placed(self,x,y):
        if self._placement=='clipboard_v170':return self._place_clipboard_v170(x,y)
        return super().placed(x,y)

    def _place_clipboard_v170(self,x,y):
        if not self.model or not self._clipboard_placement_v170:return
        bundle=deepcopy(self._clipboard_placement_v170)
        payload={'operation':'paste','page':self.page_number,'revision':self.model.revision,
                 'bundle':bundle,'point':(x,y),'allow_overlap':self.allow_overlap_box.isChecked(),
                 'auto_adapt':self.auto_adapt_box.isChecked()}
        self._cancel_placement();self._clipboard_placement_v170=None
        self.canvas.setFocus()
        self._submit('clipboard_apply',payload,self._edited)

    def _clipboard_context_v170(self,position,image=False):
        if self.busy or not self.model or self.state.get('preview'):return
        self.canvas.setFocus();self._refresh_clipboard_v170()
        menu=QMenu(self);menu.setObjectName('imageContextMenu' if image else 'textContextMenu')
        for action in (self.copy_action_v170,self.cut_action_v170,self.paste_action_v170,self.delete_action_v170):menu.addAction(action)
        save=edit=None
        if image:
            menu.addSeparator();save=menu.addAction('Guardar / exportar imagen…');edit=menu.addAction('Recortar / girar / reemplazar…')
            item=self.canvas.selected_image();edit.setEnabled(bool(item and item.get('editable')) and not self.state.get('issues'))
        menu.aboutToHide.connect(lambda:setattr(self,'_clipboard_menu_v170',None))
        def selected(action):
            if action is save:self.export_selected_image()
            elif action is edit:self.edit_selected_image()
        menu.triggered.connect(selected);self._clipboard_menu_v170=menu;menu.popup(position)

    def text_context_v170(self,position):self._clipboard_context_v170(position)
    def image_context(self,image_id,position):self._clipboard_context_v170(position,True)
