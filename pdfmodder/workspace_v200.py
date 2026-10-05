"""Document tabs, recovery, selection preflight and bounded cell editing."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt,QTimer,QSize
from PySide6.QtGui import QAction,QIcon,QPixmap
from PySide6.QtWidgets import (QTabBar,QLabel,QFileDialog,QMessageBox,QListWidgetItem,
    QDialog,QVBoxLayout,QFormLayout,QDoubleSpinBox,QComboBox,QDialogButtonBox,
    QListWidget,QPushButton,QHBoxLayout,QGraphicsView,QGraphicsScene,QInputDialog,QLineEdit)

from .model import pt,mm,transform_rect,union
from .ui_icons_v170 import icon_v170


class CellDialogV200(QDialog):
    def __init__(self,rect,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Editar párrafo / celda delimitada')
        self.setObjectName('cellEditorDialogV200')
        layout=QVBoxLayout(self)
        note=QLabel('El área limita la redistribución. Las letras conservan su tamaño y los elementos vecinos mantienen su posición.')
        note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();self.boxes=[]
        for name,value in zip(('X','Y','Anchura','Altura'),(rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1])):
            spin=QDoubleSpinBox();spin.setDecimals(3);spin.setRange(0,3000);spin.setSuffix(' mm');spin.setValue(mm(value))
            spin.setObjectName('cell'+name);form.addRow(name,spin);self.boxes.append(spin)
        self.padding=QDoubleSpinBox();self.padding.setDecimals(2);self.padding.setRange(0,100);self.padding.setSuffix(' mm');self.padding.setValue(0)
        form.addRow('Margen interior',self.padding)
        self.align=QComboBox()
        for name,value in [('Izquierda','left'),('Centro','center'),('Derecha / importes','right'),('Justificada','justify')]:self.align.addItem(name,value)
        form.addRow('Alineación',self.align);layout.addLayout(form)
        layout.addWidget(QLabel('Intro crea un párrafo; Mayús+Intro, una línea. El editor ofrece sangrías, tabulaciones e interlineado.'))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Abrir editor');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def options(self):
        x,y,w,h=[pt(s.value()) for s in self.boxes]
        return {'rect':[x,y,x+w,y+h],'padding':pt(self.padding.value()),'alignment':self.align.currentData()}


class SplitCompareV200(QDialog):
    def __init__(self,titles,parent=None):
        super().__init__(parent);self.setWindowTitle('Comparar documentos');self.resize(1250,850)
        self.setObjectName('splitCompareDialogV200');layout=QVBoxLayout(self)
        note=QLabel('Comparación de páginas actuales. Las barras verticales se desplazan juntas.');layout.addWidget(note)
        controls=QHBoxLayout()
        for title,factor in [('−',1/1.25),('+',1.25)]:
            button=QPushButton(title);button.clicked.connect(lambda _,f=factor:self.zoom(f));controls.addWidget(button)
        fit=QPushButton('Ajustar anchura');fit.clicked.connect(self.fit_width);controls.addWidget(fit);controls.addStretch();layout.addLayout(controls)
        row=QHBoxLayout();self.views=[]
        self._syncing=False
        for title in titles:
            col=QVBoxLayout();col.addWidget(QLabel(title))
            view=QGraphicsView();view.setScene(QGraphicsScene(view));view.setBackgroundBrush(Qt.darkGray)
            col.addWidget(view);row.addLayout(col);self.views.append(view)
        layout.addLayout(row)
        for i,view in enumerate(self.views):view.verticalScrollBar().valueChanged.connect(lambda value,n=i:self.sync(n,value))
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(self.reject);layout.addWidget(close)
    def set_page(self,index,png):
        pix=QPixmap();pix.loadFromData(png);view=self.views[index];view.scene().clear();view.scene().addPixmap(pix);view.scene().setSceneRect(pix.rect())
        self.fit_width()
    def zoom(self,factor):
        for view in self.views:view.scale(factor,factor)
    def fit_width(self):
        for view in self.views:
            if view.sceneRect().width()>0:
                view.resetTransform();factor=max(.05,(view.viewport().width()-20)/view.sceneRect().width());view.scale(factor,factor)
    def sync(self,index,value):
        if self._syncing:return
        self._syncing=True
        try:
            source=self.views[index].verticalScrollBar();target=self.views[1-index].verticalScrollBar()
            target.setValue(round(value/max(1,source.maximum())*target.maximum()))
        finally:self._syncing=False


class WorkspaceV200Mixin:
    def _exec_edit_dialog(self,dialog):
        self._modal_depth_v200=getattr(self,'_modal_depth_v200',0)+1
        timers=[getattr(self,name,None) for name in ('_workspace_timer_v200','_preflight_timer_v200')]
        for timer in timers:
            if timer:timer.stop()
        try:
            return super()._exec_edit_dialog(dialog)
        finally:
            self._modal_depth_v200-=1
            if not self._modal_depth_v200:
                if getattr(self,'_preflight_pending_v200',None):self._preflight_timer_v200.start(200)
                if getattr(self,'state',None):self._workspace_timer_v200.start(750)

    def _init_workspace_v200(self):
        self._session_views_v200={};self._session_paths_v200={};self._active_session_v200=None
        self._preflight_pending_v200=None;self._preflight_result_v200=None;self._cell_draw_v200=False
        self._legacy_accept_v200=False;self._legacy_cancel_v200=False
        self._start_edit_requested_v200=None;self._restored_draft_v200=None
        self._drop_queue_v200=[]
        self.document_tabs_v200=QTabBar();self.document_tabs_v200.setObjectName('documentTabsV200')
        self.document_tabs_v200.setTabsClosable(True);self.document_tabs_v200.setMovable(False)
        self.document_tabs_v200.setExpanding(False)
        self.document_tabs_v200.currentChanged.connect(self._switch_tab_v200)
        self.document_tabs_v200.tabCloseRequested.connect(self._close_tab_v200)
        self.centralWidget().layout().insertWidget(0,self.document_tabs_v200)
        self.capability_label_v200=QLabel('Selecciona texto para comprobar su compatibilidad.');self.capability_label_v200.setWordWrap(True)
        self.capability_label_v200.setObjectName('selectionCapabilityV200')
        self.property_box.layout().insertRow(1,self.capability_label_v200)
        self.cell_action_v200=QAction('Delimitar párrafo / celda…',self);self.cell_action_v200.setIcon(icon_v170('text_properties'))
        self.cell_action_v200.setObjectName('cellEditorActionV200');self.cell_action_v200.triggered.connect(self.begin_cell_v200)
        self._tool_button_v150(self.content_tools_section.body,self.cell_action_v200,'toolCellV200')
        self.recovery_action_v200=QAction('Recuperar trabajo…',self);self.recovery_action_v200.setIcon(icon_v170('undo'))
        self.recovery_action_v200.triggered.connect(self.show_recovery_v200);self.toolbar.addAction(self.recovery_action_v200)
        self.split_action_v200=QAction('Comparar dos documentos…',self);self.split_action_v200.setIcon(icon_v170('compare'))
        self.split_action_v200.triggered.connect(self.split_compare_v200);self.toolbar.addAction(self.split_action_v200)
        self._preflight_timer_v200=QTimer(self);self._preflight_timer_v200.setSingleShot(True)
        self._preflight_timer_v200.timeout.connect(self._pump_preflight_v200)
        self._workspace_timer_v200=QTimer(self);self._workspace_timer_v200.setSingleShot(True)
        self._workspace_timer_v200.timeout.connect(self._persist_view_v200)
        self.reader.verticalScrollBar().valueChanged.connect(lambda _:self._workspace_timer_v200.start(900))
        self.canvas.verticalScrollBar().valueChanged.connect(lambda _:self._workspace_timer_v200.start(900))
        self.canvas.editor.textChanged.connect(lambda:self._workspace_timer_v200.start(750))
        self.operation_finished.connect(self._operation_v200)
        self.preview_button.setText('Aceptar texto ✓ · Ctrl+Intro')
        self.preview_step_button.setText('Aceptar ✓ · Ctrl+Intro')
        self.apply_step_button.setText('Aceptar ✓')
        self.error_raised.connect(self._legacy_failed_v200)
        QTimer.singleShot(250,self._offer_recovery_v200)

    def _reading_command_allowed_v171(self,command):
        if command in ('activate_session','close_session','close_all','list_sessions','list_recovery','recover','discard_recovery','print_pages_v200','snapshot_v200','update_workspace','store_draft'):
            return True
        return super()._reading_command_allowed_v171(command)

    def _submit(self,command,payload=None,callback=None):
        payload=dict(payload or {})
        if command=='recover':self._recovery_retry_v200=(payload,callback)
        if getattr(self,'_active_session_v200',None) and command not in ('open','combine','recover','list_recovery','discard_recovery','close_all'):
            payload.setdefault('session_id',self._active_session_v200)
        return super()._submit(command,payload,callback)

    def _retry_recovery_password_v200(self):
        attempt=getattr(self,'_recovery_retry_v200',None)
        if not attempt:return
        dialog=QInputDialog(self);dialog.setWindowTitle('Recuperar PDF cifrado')
        dialog.setLabelText('Introduce una contraseña legítima del documento. No se guarda en la recuperación.')
        dialog.setTextEchoMode(QLineEdit.Password)
        if self._exec_edit_dialog(dialog)==QDialog.Accepted:
            payload,callback=attempt
            self._submit('recover',dict(payload,password=dialog.textValue()),callback)
        else:
            self._recovery_retry_v200=None;self._notice('Recuperación cancelada. El borrador local se conserva.')

    def choose_open(self):
        path,_=QFileDialog.getOpenFileName(self,'Abrir PDF en nueva pestaña','','Documentos PDF (*.pdf)')
        if path:self.open_document(path)

    def _open_recent_v170(self,item):
        path=item.data(Qt.UserRole)
        if path and Path(path).is_file() and not self.busy:self.open_document(path)
        elif path and not Path(path).is_file():self._notice('El documento se ha movido o eliminado. Usa Abrir para localizarlo.')

    def dragEnterEvent(self,event):
        if self._drop_paths(event.mimeData()) and not self.busy and not self.canvas.editor.isVisible():event.acceptProposedAction()
        else:event.ignore()

    def dropEvent(self,event):
        paths=self._drop_paths(event.mimeData())
        if self.busy or not paths or self.canvas.editor.isVisible() or self.state.get('preview'):event.ignore();return
        self._drop_queue_v200=list(paths);event.acceptProposedAction();self._drain_drop_v200()

    def _drain_drop_v200(self):
        if self._closed or not self._drop_queue_v200:return
        if self.busy:QTimer.singleShot(100,self._drain_drop_v200);return
        path=self._drop_queue_v200.pop(0);self.open_document(path)
        if self._drop_queue_v200:QTimer.singleShot(100,self._drain_drop_v200)

    def combine_pdfs(self,paths):
        self._stash_view_v200();sid=uuid4().hex
        payload={'paths':[str(p) for p in paths],'session_id':sid,'retain_existing':True}
        for name in ('config_path','history_dir'):
            if getattr(self,name):payload[name]=str(getattr(self,name))
        def combined(result):
            self._active_session_v200=sid;self.page_number=0;self._add_tab_v200(sid,self.state['path'])
            self._reset_view_v200();self._set_mode_v171('editing');self._edited(result)
        self._submit('combine',payload,combined)

    def open_document(self,path,password=''):
        if self.busy:return False
        if self.canvas.editor.isVisible() or self.state.get('preview'):
            self._notice('Acepta o cancela el borrador antes de abrir otra pestaña.');return False
        self._stash_view_v200()
        original_submit=self._submit
        new_id=uuid4().hex
        def intercept(command,payload=None,callback=None):
            if command=='open':
                payload=dict(payload or {},session_id=new_id,retain_existing=True)
                def opened(result):
                    self._active_session_v200=result['state']['session_id'];self._add_tab_v200(self._active_session_v200,str(path))
                    self.page_number=0
                    self._reset_view_v200()
                    if callback:callback(result)
                return original_submit(command,payload,opened)
            return original_submit(command,payload,callback)
        self._submit=intercept
        try:return super().open_document(path,password)
        finally:self._submit=original_submit

    def _add_tab_v200(self,session_id,path):
        self._session_paths_v200[session_id]=path
        bar=self.document_tabs_v200;bar.blockSignals(True)
        index=next((i for i in range(bar.count()) if bar.tabData(i)==session_id),None)
        if index is None:index=bar.addTab(Path(path).name);bar.setTabData(index,session_id)
        bar.setTabToolTip(index,path);bar.setCurrentIndex(index);bar.blockSignals(False)

    def _stash_view_v200(self):
        if not self._active_session_v200:return
        self._session_views_v200[self._active_session_v200]={'page':self.page_number,'zoom':self.zoom,'mode':self.application_mode,
            'scroll':self.reader.verticalScrollBar().value() if self.application_mode=='reading' else self.canvas.verticalScrollBar().value(),
            'ids':self.canvas.ids[:],'state':deepcopy(self.state)}

    def _reset_view_v200(self):
        self._reader_generation_v180+=1;self._reader_key_v180=None;self._reader_queue_v180.clear()
        self._reader_copy_v180=None;self._preflight_pending_v200=None;self._preflight_result_v200=None
        self._format_copy=None;self._rich_catalog=None;self._text_draft=None;self._font_catalog=None
        self._restore_ids=None;self._restore_regions=None;self._restore_image_rect=None;self._editing_context=None
        self._thumbnail_pages.clear();self._thumbnail_order.clear();self._search_matches=[];self._last_search=None
        self.canvas.ids=[];self.canvas.images=[];self.canvas.search_rects=[];self.canvas.image_id=None
        self.canvas.end_signature_rectangle();self.canvas.editor.hide();self.canvas._release_editor_proxy()
        self.canvas.scene().clear();self.canvas.overlays=[];self.canvas._pixmap_item=None
        self.canvas._editor_bounds=None;self.canvas.changes=[]
        self.canvas.model=None;self.model=None;self.fonts=[]
        self.reader.reset_document([],zoom=self.zoom)
        self.compare_action.setChecked(False);self.rich_result.hide()

    def _switch_tab_v200(self,index):
        if index<0:return
        sid=self.document_tabs_v200.tabData(index)
        if sid==self._active_session_v200:return
        if self.busy or self.canvas.editor.isVisible() or self.state.get('preview') or self._cell_draw_v200:
            self._notice('Espera o acepta/cancela el borrador antes de cambiar de pestaña.')
            self.document_tabs_v200.blockSignals(True)
            for i in range(self.document_tabs_v200.count()):
                if self.document_tabs_v200.tabData(i)==self._active_session_v200:self.document_tabs_v200.setCurrentIndex(i)
            self.document_tabs_v200.blockSignals(False);return
        self._stash_view_v200()
        def activated(result):
            self._active_session_v200=sid;self._restore_tab_v200(sid)
        self._submit('activate_session',{'session_id':sid},activated)

    def _restore_tab_v200(self,sid):
        view=self._session_views_v200.get(sid,{})
        self.page_number=0
        self._reset_view_v200();self.page_number=min(view.get('page',0),self.state['page_count']-1);self.zoom=view.get('zoom',1.25)
        self._sync_zoom_control();self.pages.blockSignals(True);self.pages.clear()
        for i in range(self.state['page_count']):
            item=QListWidgetItem(f'Página {i+1}');item.setSizeHint(QSize(118,158));self.pages.addItem(item)
        self.pages.setCurrentRow(self.page_number);self.pages.blockSignals(False)
        self._set_mode_v171(view.get('mode','reading'));self._restore_ids=view.get('ids') or None
        self.load_page();self._refresh_actions()
        QTimer.singleShot(200,lambda:(self.reader if self.application_mode=='reading' else self.canvas).verticalScrollBar().setValue(view.get('scroll',0)))

    def _close_tab_v200(self,index):
        if self.busy or self.canvas.editor.isVisible() or self.state.get('preview'):return
        sid=self.document_tabs_v200.tabData(index)
        dirty=self.state.get('dirty') if sid==self._active_session_v200 else self._session_views_v200.get(sid,{}).get('state',{}).get('dirty')
        if dirty and QMessageBox.question(self,'Cerrar documento','Hay cambios sin guardar. ¿Descartar el trabajo de esta pestaña?',QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Discard:return
        def closed(result):
            self.document_tabs_v200.blockSignals(True);self.document_tabs_v200.removeTab(index);self.document_tabs_v200.blockSignals(False)
            self._session_paths_v200.pop(sid,None);self._session_views_v200.pop(sid,None)
            if sid==self._active_session_v200:
                self._active_session_v200=None;self.state={};self._reset_view_v200();self.pages.clear()
                if self.document_tabs_v200.count():self._switch_tab_v200(self.document_tabs_v200.currentIndex())
                else:self._refresh_actions()
        self._submit('close_session',{'session_id':sid},closed)

    def _operation_v200(self,command,result):
        if self._background_ui_v200:return
        if self._active_session_v200:
            self._stash_view_v200()
            for i in range(self.document_tabs_v200.count()):
                if self.document_tabs_v200.tabData(i)==self._active_session_v200:
                    self.document_tabs_v200.setTabText(i,Path(self._session_paths_v200.get(self._active_session_v200,'Documento')).name+(' *' if self.state.get('dirty') else ''))
        if self._preflight_pending_v200:self._preflight_timer_v200.start(120)
        if command not in ('page','reading_info','list_recovery','update_workspace','store_draft','selection_capabilities_v200'):
            self._workspace_timer_v200.start(500)

    def _persist_view_v200(self):
        if getattr(self,'_modal_depth_v200',0):return
        if not self.state or self._closed:return
        if self.busy:self._workspace_timer_v200.start(500);return
        self._stash_view_v200()
        view=self._session_views_v200.get(self._active_session_v200,{})
        workspace={'page':self.page_number,'zoom':self.zoom,'reading':self.application_mode=='reading',
                   'scroll':view.get('scroll',0),'selection':self.canvas.ids[:]}
        draft=None
        if self.canvas.editor.isVisible():
            if self._rich_active:draft={'kind':'rich','payload':self.canvas.editor.payload()}
            elif self.canvas.ids and self.model:
                draft={'kind':'legacy','page':self.page_number,'ids':self.canvas.ids[:],
                       'revision':self.model.revision,'text':self.canvas.editor.toPlainText()}
        self._submit('store_draft',{'draft':draft,'workspace':workspace})

    def selection_changed(self,ids):
        super().selection_changed(ids)
        if not hasattr(self,'capability_label_v200'):return
        self._preflight_result_v200=None
        if ids and self.model and self.application_mode=='editing' and not self.state.get('preview'):
            self._preflight_pending_v200=(self.page_number,self.model.revision,tuple(ids));self.capability_label_v200.setText('Comprobando la selección…')
            self._preflight_timer_v200.start(180)
        else:
            self._preflight_pending_v200=None;self.capability_label_v200.setText('Selecciona texto para comprobar su compatibilidad.')

    def _pump_preflight_v200(self):
        if getattr(self,'_modal_depth_v200',0):return
        pending=self._preflight_pending_v200
        if not pending or not self.model:return
        if self.busy:self._preflight_timer_v200.start(120);return
        if pending!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):
            self._preflight_pending_v200=None;return
        self._preflight_pending_v200=None
        def ready(result):
            if not self.model or pending!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):return
            self._preflight_result_v200=result
            self.capability_label_v200.setText(result['label']+'\n'+'\n'.join(result.get('reasons',[])+result.get('actions',[])))
            self.capability_label_v200.setStyleSheet('color: '+('#a32b22' if result['status']=='blocked' else '#286444')+';')
            if self._start_edit_requested_v200==pending:
                self._start_edit_requested_v200=None
                QTimer.singleShot(0,self.start_edit)
        self._submit('selection_capabilities_v200',{'page':pending[0],'revision':pending[1],'ids':list(pending[2])},ready)

    def start_edit(self):
        if self._preflight_result_v200 and self._preflight_result_v200['status']=='blocked':
            self._error('\n'.join(self._preflight_result_v200.get('reasons',[])+self._preflight_result_v200.get('actions',[])));return
        if self.model and self.canvas.ids and not self._preflight_result_v200:
            self._start_edit_requested_v200=(self.page_number,self.model.revision,tuple(self.canvas.ids))
            self._preflight_pending_v200=self._start_edit_requested_v200
            self._preflight_timer_v200.start(0);return
        return super().start_edit()

    def preview_text(self,text):
        if not getattr(self,'_rich_active',False):self._legacy_accept_v200=True;self._legacy_cancel_v200=False
        return super().preview_text(text)

    def _legacy_preview_finished_v200(self,result):
        if self._legacy_accept_v200:
            self._legacy_accept_v200=False
            if self._legacy_cancel_v200:
                self._legacy_cancel_v200=False;self._submit('cancel',callback=lambda _:self.load_page());return
            self.canvas.editor.hide();self._editing_context=None
            self._submit('commit',callback=self._edited)
        else:self._previewed(result)

    def _legacy_failed_v200(self,message):
        self._legacy_accept_v200=False
        if self.canvas.editor.isVisible() and not self._rich_active:self.canvas.editor.setReadOnly(False)

    def _refresh_actions(self):
        super()._refresh_actions()
        if not hasattr(self,'document_tabs_v200'):return
        opened=bool(self.state);draft=self.canvas.editor.isVisible() or self.state.get('preview')
        self.document_tabs_v200.setEnabled(not self.busy and not draft and not self._cell_draw_v200)
        self.cell_action_v200.setEnabled(opened and self.application_mode=='editing' and not self.busy and not draft and not self.state.get('issues'))
        self.recovery_action_v200.setEnabled(not self.busy and not draft)
        self.split_action_v200.setEnabled(len(self._session_paths_v200)>1 and not self.busy and not draft)
        if self.state.get('special_only_save') and self.application_mode=='editing':self.save_action.setEnabled(not self.busy and not draft)
        if not self._rich_active:
            self.preview_step_button.setText('Aceptar ✓ · Ctrl+Intro')
            self.edit_step_label.setText('Aceptar valida y aplica una sola operación. Cancelar conserva el PDF anterior.')
            if self.canvas.editor.isVisible():self.apply_step_button.hide()
        if hasattr(self,'forms_action_v200'):self.refresh_forms_redaction_v200()
        if hasattr(self,'print_action_v200'):self.print_action_v200.setEnabled(opened and not self.busy and not draft)
        if self._cell_draw_v200:
            self.pages.setEnabled(False);self.zoom_box.setEnabled(False)
            for action in self.findChildren(QAction):action.setEnabled(False)
            self.cancel_button.setEnabled(True);self.cancel_step_button.setEnabled(True)
            self.edit_steps.show();self.edit_step_label.setText('Dibuja el área del párrafo o celda. Escape cancela.')
            self.preview_step_button.setEnabled(False);self.apply_step_button.hide()

    def begin_cell_v200(self):
        if self.busy or not self.model:return
        self._cell_draw_v200=True;self._placement='cell_rectangle';self.canvas.begin_signature_rectangle()
        self.canvas.signature_rectangle_selected.connect(self._cell_chosen_v200)
        self.canvas.signature_rectangle_cancelled.connect(self._cancel_cell_v200)
        self._notice('Arrastra un rectángulo alrededor del párrafo o celda que quieres editar. Escape cancela.')
        self._refresh_actions()

    def _cancel_cell_v200(self):
        if not self._cell_draw_v200:return False
        self._cell_draw_v200=False;self._placement=None;self.canvas.end_signature_rectangle()
        self.canvas.signature_rectangle_selected.disconnect(self._cell_chosen_v200)
        self.canvas.signature_rectangle_cancelled.disconnect(self._cancel_cell_v200)
        self._refresh_actions();return True

    def _cell_chosen_v200(self,display_rect):
        rect=transform_rect(display_rect,self.model.derotation_matrix);self._cancel_cell_v200()
        dialog=CellDialogV200(rect,self)
        if self._exec_edit_dialog(dialog)!=QDialog.Accepted:return
        def ready(result):
            self.canvas.set_selection(result['ids']);self._preflight_pending_v200=None
            self._rich_generation+=1;self._open_rich_payload(result['payload'])
            self._notice('Edita sólo esta celda. Aceptar comprueba desbordamientos; las letras conservan su tamaño.')
        self._submit('cell_selection_v200',dict(page=self.page_number,revision=self.model.revision,**dialog.options()),ready)

    def cancel(self):
        if getattr(self,'_cell_draw_v200',False):self._cancel_cell_v200();return
        if self.busy and self._command=='preview' and self._legacy_accept_v200:
            self._legacy_cancel_v200=True;self._notice('Cancelando el borrador cuando termine su validación…');return
        return super().cancel()

    def _offer_recovery_v200(self):
        if self._closed:return
        if self.busy:QTimer.singleShot(300,self._offer_recovery_v200);return
        self._submit('list_recovery',self._recovery_options_v200(),callback=lambda result:self._show_recoveries_v200(result,automatic=True))

    def show_recovery_v200(self):
        self._submit('list_recovery',self._recovery_options_v200(),callback=self._show_recoveries_v200)

    def _recovery_options_v200(self):
        return {'recovery_root':str(Path(self.history_dir)/'recovery')} if self.history_dir else {}

    def _show_recoveries_v200(self,result,automatic=False):
        entries=result.get('entries',[])
        if not entries:
            if not automatic:self._notice('No hay trabajo pendiente de recuperación.')
            return
        dialog=QDialog(self);dialog.setWindowTitle('Recuperar trabajo local');layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel('Se encontraron sesiones sin cerrar. Los archivos originales se conservan.'))
        choices=QListWidget();layout.addWidget(choices)
        for entry in entries:choices.addItem(Path(entry['path']).name+' · '+str(entry.get('updated','')))
        choices.setCurrentRow(0);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Recuperar');buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        discard=buttons.addButton('Descartar borrador',QDialogButtonBox.DestructiveRole)
        discard.clicked.connect(lambda:dialog.done(2));layout.addWidget(buttons)
        answer=self._exec_edit_dialog(dialog)
        if answer not in (QDialog.Accepted,2) or choices.currentRow()<0:return
        selected=entries[choices.currentRow()]
        if answer==2:
            self._submit('discard_recovery',dict(recovery_id=selected['recovery_id'],**self._recovery_options_v200()),lambda _:self._notice('Borrador local descartado.'));return
        self._stash_view_v200()
        def recovered(value):
            self._recovery_retry_v200=None
            self._active_session_v200=value['state']['session_id'];self._add_tab_v200(self._active_session_v200,selected['path'])
            view=selected.get('workspace',{})
            self._session_views_v200[self._active_session_v200]={'page':view.get('page',0),'zoom':view.get('zoom',1.25),
                'mode':'reading' if view.get('reading',True) else 'editing','scroll':view.get('scroll',0),'ids':view.get('selection',[])}
            self._restored_draft_v200=value['state'].get('recovered_draft')
            if self._restored_draft_v200:self._session_views_v200[self._active_session_v200]['mode']='editing'
            self._restore_tab_v200(self._active_session_v200);self._notice('Trabajo recuperado con su historial. Guarda una copia cuando lo hayas revisado.')
        payload=dict(recovery_id=selected['recovery_id'],session_id=uuid4().hex,retain_existing=True,**self._recovery_options_v200())
        if self.config_path:payload['config_path']=str(self.config_path)
        self._submit('recover',payload,recovered)

    def _loaded_page(self,result):
        super()._loaded_page(result)
        draft=self._restored_draft_v200
        if not draft or self.state.get('preview'):return
        self._restored_draft_v200=None
        if draft.get('kind')=='rich':
            payload=draft['payload'];self.canvas.set_selection(payload.get('ids',[]));self._rich_generation+=1;self._open_rich_payload(payload)
        elif draft.get('kind')=='legacy':
            self.canvas.set_selection(draft.get('ids',[]));self.canvas.start_editor(draft.get('text',''))
            self._editing_context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
        self._notice('Borrador recuperado. Revísalo y pulsa Aceptar o Cancelar.')

    def split_compare_v200(self):
        ids=list(self._session_paths_v200)
        if len(ids)<2:return
        other=next(s for s in ids if s!=self._active_session_v200)
        dialog=SplitCompareV200([Path(self._session_paths_v200[self._active_session_v200]).name,Path(self._session_paths_v200[other]).name],self)
        active=self._active_session_v200;page=self.page_number
        def left(result):
            dialog.set_page(0,result['png'])
            def right(value):
                dialog.set_page(1,value['png']);self._exec_edit_dialog(dialog)
                self._submit('activate_session',{'session_id':active},lambda _:self._refresh_actions())
            other_page=self._session_views_v200.get(other,{}).get('page',0)
            self._submit('page',{'session_id':other,'number':other_page,'zoom':1.5,'reading':True,'_background_ui':True},right)
        self._submit('page',{'number':page,'zoom':1.5,'reading':True},left)

    def _confirm_discard(self):
        dirty=[v for s,v in self._session_views_v200.items() if s!=self._active_session_v200 and v.get('state',{}).get('dirty')]
        if dirty:
            return QMessageBox.question(self,'Cerrar PDF Modder','Hay cambios sin guardar en varias pestañas. ¿Descartarlos y cerrar?',QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)==QMessageBox.Discard
        return super()._confirm_discard()
