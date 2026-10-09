"""Actionable capabilities for the selected operation, without changing a PDF."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget,QHBoxLayout,QPushButton,QComboBox


class CompatibilityUiV300Mixin:
    def _init_compatibility_v300(self):
        self._operation_tooltips_v300={name:getattr(self,name).toolTip() for name in
            ('add_image_action','image_mode_action','objects_action') if hasattr(self,name)}
        self.capability_operation_v300=QComboBox()
        self.capability_operation_v300.setObjectName('capabilityOperationV300')
        for label,key in [('Cambiar texto / formato','text'),('Mover','move'),
                          ('Cambiar escala','scale'),('Girar','rotate'),('Duplicar','duplicate')]:
            self.capability_operation_v300.addItem(label,key)
        self.property_box.layout().insertRow(1,'Comprobar operación',self.capability_operation_v300)
        self.capability_operation_v300.currentIndexChanged.connect(self._capability_operation_changed_v300)
        row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
        self.capability_buttons_v300={}
        for key,label,callback in [('fonts','Elegir fuente…',self.font_inspector),
            ('objects','Editar objetos…',self.open_native_objects_v300),
            ('area','Delimitar área…',self.begin_cell_v200),
            ('forms','Editar campo…',self.choose_form_editor_v200),
            ('ocr','Corregir capa OCR',self._select_ocr_v300)]:
            button=QPushButton(label);button.setObjectName('capabilityActionV300_'+key)
            button.clicked.connect(callback);button.hide();layout.addWidget(button)
            self.capability_buttons_v300[key]=button
        self.property_box.layout().insertRow(3,row)
        self._show_capability_v300()

    def _select_ocr_v300(self):
        self.ocr_mode_box.setChecked(True)
        self._notice('Corregir capa OCR buscable está activado. Se utiliza el OCR que ya contiene el documento.')
        self.start_edit()

    def selection_changed(self,ids):
        super().selection_changed(ids)
        if hasattr(self,'capability_buttons_v300'):
            for button in self.capability_buttons_v300.values():button.hide()

    def _show_capability_v300(self,*unused):
        if not hasattr(self,'capability_operation_v300'):return
        result=getattr(self,'_preflight_result_v200',None)
        if not result:return
        key=self.capability_operation_v300.currentData()
        capability=result.get('operations',{}).get(key,result)
        self.capability_label_v200.setText(capability['label']+'\n'+'\n'.join(capability.get('reasons',[])+capability.get('actions',[])))
        colour={'available':'#286444','conditional':'#855300','blocked':'#a32b22'}[capability['status']]
        self.capability_label_v200.setStyleSheet('color: '+colour+';')
        resolutions=set(capability.get('resolution_ids',[]))
        for name,button in self.capability_buttons_v300.items():button.setVisible(name in resolutions)

    def _capability_operation_changed_v300(self,*unused):
        self._show_capability_v300()
        result=getattr(self,'_preflight_result_v200',None)
        key=self.capability_operation_v300.currentData()
        if (self.model and self.canvas.ids and (not result or
                result.get('operations',{}).get(key,{}).get('requires_check'))):
            self._preflight_pending_v200=(self.page_number,self.model.revision,tuple(self.canvas.ids))
            self._preflight_timer_v200.start(0)

    def _pump_preflight_v200(self):
        if getattr(self,'_modal_depth_v200',0):return
        pending=self._preflight_pending_v200
        if not pending or not self.model:return
        if self.busy:self._preflight_timer_v200.start(120);return
        if pending!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):
            self._preflight_pending_v200=None;return
        self._preflight_pending_v200=None
        operation=self.capability_operation_v300.currentData()
        def ready(result):
            if not self.model or pending!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):return
            if operation!=self.capability_operation_v300.currentData():
                self._preflight_pending_v200=pending;self._preflight_timer_v200.start(0);return
            self._preflight_result_v200=result;self._show_capability_v300()
            if self._start_edit_requested_v200==pending:
                self._start_edit_requested_v200=None;QTimer.singleShot(0,self.start_edit)
        self._submit('selection_capabilities_v300',{'page':pending[0],'revision':pending[1],
            'ids':list(pending[2]),'operation':operation},ready)

    def _refresh_actions(self):
        super()._refresh_actions()
        for name,tooltip in getattr(self,'_operation_tooltips_v300',{}).items():
            action=getattr(self,name)
            if self.state.get('has_form_fields'):
                action.setEnabled(False)
                action.setToolTip('Usa «Editar objetos PDF…» para transformar las apariciones de este documento con campos interactivos.')
            else:action.setToolTip(tooltip)
        if hasattr(self,'native_objects_action'):
            self.native_objects_action.setEnabled(bool(self.model and self.application_mode=='editing'
                and not self.busy and not self.state.get('preview') and not self.canvas.editor.isVisible()
                and not getattr(self,'_save_transaction_v300',None)))
