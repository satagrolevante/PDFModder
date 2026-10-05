"""Visible AcroForm editor and reviewed redaction zones for PDF Modder 2.0."""
from PySide6.QtCore import Qt,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QAction,QColor,QImage,QPainter,QPen
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QDialogButtonBox,
    QDoubleSpinBox,QFormLayout,QHBoxLayout,QLabel,QListWidget,QPushButton,
    QSpinBox,QTableWidget,QTableWidgetItem,QTextEdit,QVBoxLayout,QWidget)

from .image_editor import CropCanvas
from .model import PT_PER_MM,transform_rect


class FormEditorDialog(QDialog):
    def __init__(self,listing,parent=None):
        super().__init__(parent)
        self.setObjectName('formEditorV200');self.setWindowTitle('Campos de formulario');self.resize(870,540)
        self.listing=listing;self.selected=None
        self.table=QTableWidget(0,4);self.table.setObjectName('formFieldsTable')
        self.table.setHorizontalHeaderLabels(['Página','Campo','Tipo','Valor'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for field in listing['fields']:
            row=self.table.rowCount();self.table.insertRow(row)
            for column,value in enumerate((field['page']+1,field['name'],field['type'],field['value'])):
                self.table.setItem(row,column,QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.value_edit=QTextEdit();self.value_edit.setObjectName('formValue');self.value_edit.setMaximumHeight(95)
        self.choice=QComboBox();self.check=QCheckBox('Marcado')
        self.change_value=QCheckBox('Cambiar valor');self.change_value.setObjectName('formChangeValue')
        self.change_geometry=QCheckBox('Cambiar posición o dimensiones');self.change_geometry.setObjectName('formChangeGeometry')
        self.geometry=[];form=QFormLayout()
        for label,key in zip(('X','Y','Anchura','Altura'),('X','Y','Width','Height')):
            spin=QDoubleSpinBox();spin.setObjectName('form'+key);spin.setDecimals(3);spin.setRange(0,10000);spin.setSuffix(' mm')
            form.addRow(label,spin);self.geometry.append(spin)
        self.notice=QLabel();self.notice.setWordWrap(True)
        details=QVBoxLayout();details.addWidget(self.change_value);details.addWidget(self.value_edit);details.addWidget(self.choice)
        details.addWidget(self.check);details.addWidget(self.change_geometry);details.addLayout(form);details.addWidget(self.notice);details.addStretch()
        arrangement=QHBoxLayout();arrangement.addWidget(self.table,2);arrangement.addLayout(details,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.accept_button=buttons.button(QDialogButtonBox.Ok);self.accept_button.setText('Previsualizar campo')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Los campos siguen siendo rellenables. Se conservan sus nombres, opciones y scripts.'))
        layout.addLayout(arrangement);layout.addWidget(buttons)
        self.table.currentCellChanged.connect(self._selected)
        self.change_value.toggled.connect(self._controls);self.change_geometry.toggled.connect(self._controls)
        self._controls()
        if self.table.rowCount():self.table.setCurrentCell(0,0)
        else:self.notice.setText(listing.get('reason') or 'El PDF no contiene campos AcroForm.')

    def _selected(self,row,*_):
        if not 0<=row<len(self.listing['fields']):return
        field=self.selected=self.listing['fields'][row]
        self.change_value.setChecked(False);self.change_geometry.setChecked(False)
        self.value_edit.setPlainText(str(field['value'] or ''))
        self.check.setChecked(field.get('checked',False));self.choice.clear();self.choice.addItems([str(v) for v in field['choices']])
        self.choice.setCurrentText(str(field['value'] or ''))
        x0,y0,x1,y1=field['rect']
        for spin,value in zip(self.geometry,(x0,y0,x1-x0,y1-y0)):spin.setValue(value/PT_PER_MM)
        scripted=self.listing.get('has_calculations') or self.listing.get('has_document_scripts') or field['scripts']
        self.notice.setText(field['reason'] or ('Hay cálculos o validaciones JavaScript: se permite mover y redimensionar, conservando las apariencias; cambiar valores requiere evaluar sus scripts.' if scripted else
            ('Campo de sólo lectura: puedes cambiar su posición.' if field['read_only'] else 'Revisa la apariencia real del campo antes de aplicar.')))
        self._controls()

    def _controls(self,*_):
        field=self.selected;editable=bool(field and field['editable'])
        value_allowed=editable and not field['read_only'] and not field['scripts'] and not self.listing.get('has_calculations') and not self.listing.get('has_document_scripts')
        self.change_value.setEnabled(value_allowed);self.change_geometry.setEnabled(editable)
        kind=field['field_type'] if field else -1
        self.value_edit.setVisible(kind==7);self.check.setVisible(kind==2);self.choice.setVisible(kind in (3,4))
        self.value_edit.setEnabled(value_allowed and self.change_value.isChecked())
        self.choice.setEnabled(value_allowed and self.change_value.isChecked());self.check.setEnabled(value_allowed and self.change_value.isChecked())
        for spin in self.geometry:spin.setEnabled(editable and self.change_geometry.isChecked())
        self.accept_button.setEnabled(editable and (self.change_value.isChecked() or self.change_geometry.isChecked()))

    def operation(self):
        field=self.selected;changes={}
        if self.change_value.isChecked():
            changes['value']=self.check.isChecked() if field['field_type']==2 else self.choice.currentText() if field['field_type'] in (3,4) else self.value_edit.toPlainText()
        if self.change_geometry.isChecked():
            x,y,w,h=(s.value()*PT_PER_MM for s in self.geometry);changes['rect']=(x,y,x+w,y+h)
        return {'page':field['page'],'xref':field['xref'],'revision':self.listing['revision'],'changes':changes}


class RedactionDialog(QDialog):
    pageRequested=Signal(int)
    def __init__(self,info,parent=None):
        super().__init__(parent);self.setWindowTitle('Censura definitiva: revisar zonas');self.setObjectName('redactionV200')
        self.resize(850,720);self.regions=[];self.info={};self.drawn=False
        self.canvas=CropCanvas();self.canvas.setObjectName('redactionCanvas')
        self.page_number=QSpinBox();self.page_number.setObjectName('redactionPage');self.page_number.setRange(1,info['page_count'])
        self.page_number.setValue(info['page']+1)
        self.page_number.valueChanged.connect(self._request_page)
        self.add_button=QPushButton('Añadir zona dibujada');self.add_button.setObjectName('redactionAddRegion')
        self.remove_button=QPushButton('Quitar zona');self.zone_list=QListWidget();self.zone_list.setObjectName('redactionZones');self.zone_list.setMaximumHeight(120)
        self.notice=QLabel('Dibuja un rectángulo alrededor de los datos. Se eliminarán realmente el texto/OCR y los píxeles cubiertos. Revisa otras apariciones, adjuntos y metadatos antes de compartir la copia.');self.notice.setWordWrap(True)
        self.notice.setStyleSheet('background:#fff4ce;padding:8px')
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.accept_button=buttons.button(QDialogButtonBox.Ok);self.accept_button.setText('Previsualizar censura')
        self.accept_button.setEnabled(False);buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        tools=QHBoxLayout();tools.addWidget(QLabel('Página'));tools.addWidget(self.page_number);tools.addStretch();tools.addWidget(self.add_button);tools.addWidget(self.remove_button)
        layout=QVBoxLayout(self);layout.addWidget(self.notice);layout.addWidget(self.canvas,1);layout.addLayout(tools);layout.addWidget(self.zone_list);layout.addWidget(buttons)
        self.canvas.cropChanged.connect(self._drawn);self.add_button.clicked.connect(self.add_region);self.remove_button.clicked.connect(self.remove_region)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);self.set_page(info)

    def _request_page(self,value):
        self.drawn=False;self.set_busy(True);self.pageRequested.emit(value-1)

    def set_busy(self,busy):
        self.page_number.setEnabled(not busy);self.canvas.setEnabled(not busy);self.remove_button.setEnabled(not busy)
        self.add_button.setEnabled(not busy and self.drawn);self.accept_button.setEnabled(not busy and bool(self.regions))

    def set_error(self,message):
        self.notice.setText(str(message));self.set_busy(False)
        with QSignalBlocker(self.page_number):self.page_number.setValue(self.info['page']+1)

    def set_page(self,info):
        image=QImage.fromData(info['png'],'PNG')
        if image.isNull():raise ValueError('No se pudo mostrar la página para revisar la censura.')
        self.info=info;self.canvas.set_image(image);self.drawn=False;self.set_busy(False)

    def _drawn(self,*_):self.drawn=True;self.add_button.setEnabled(True)

    def add_region(self):
        if not self.drawn:return
        w,h=self.info['width'],self.info['height'];rotation=self.info['rotation'];crop=self.canvas.crop
        dw,dh=(h,w) if rotation in (90,270) else (w,h)
        rect=(crop[0]*dw,crop[1]*dh,crop[2]*dw,crop[3]*dh)
        inverse={0:(1,0,0,1,0,0),90:(0,-1,1,0,0,h),180:(-1,0,0,-1,w,h),270:(0,1,-1,0,w,0)}[rotation]
        rect=transform_rect(rect,inverse)
        if rect[2]-rect[0]<.2 or rect[3]-rect[1]<.2:return
        self.regions.append({'page':self.info['page'],'rect':rect})
        self.zone_list.addItem(f"Página {self.info['page']+1}: X {rect[0]/PT_PER_MM:.1f}, Y {rect[1]/PT_PER_MM:.1f}, {((rect[2]-rect[0])/PT_PER_MM):.1f} × {((rect[3]-rect[1])/PT_PER_MM):.1f} mm")
        self.drawn=False;self.add_button.setEnabled(False);self.accept_button.setEnabled(True)

    def remove_region(self):
        row=self.zone_list.currentRow()
        if row>=0:self.regions.pop(row);self.zone_list.takeItem(row)
        self.accept_button.setEnabled(bool(self.regions))


class FormsRedactionMixin:
    def setup_forms_redaction_v200(self,menu=None):
        from .ui_icons_v170 import icon_v170
        self.forms_action_v200=QAction('Campos de formulario…',self)
        self.forms_action_v200.setObjectName('formEditorActionV200');self.forms_action_v200.setIcon(icon_v170('document_properties'))
        self.forms_action_v200.triggered.connect(self.choose_form_editor_v200)
        self.redaction_action_v200=QAction('Censura definitiva…',self)
        self.redaction_action_v200.setObjectName('redactionActionV200');self.redaction_action_v200.setIcon(icon_v170('delete'))
        self.redaction_action_v200.triggered.connect(self.choose_redaction_v200)
        for action in (self.forms_action_v200,self.redaction_action_v200):
            if menu is not None:menu.addAction(action)
            if hasattr(self,'advanced_tools_section'):self._tool_button_v150(self.advanced_tools_section.body,action,action.objectName()+'Button')

    def refresh_forms_redaction_v200(self):
        ready=bool(self.state) and not self.busy and getattr(self,'application_mode','reading')=='editing'
        ready=ready and not self.state.get('preview') and not self.compare_action.isChecked() if ready else False
        draft=(self.canvas.editor.isVisible() or getattr(self,'_rich_active',False)
               or getattr(self,'_rich_loading',False) or bool(getattr(self,'_placement',None)))
        ready=ready and not draft
        self.forms_action_v200.setEnabled(ready);self.redaction_action_v200.setEnabled(ready and not self.state.get('issues'))

    def choose_form_editor_v200(self):
        if not self.state or self.busy:return
        self._submit('form_fields_v200',callback=lambda result:QTimer.singleShot(0,lambda:self._show_form_editor_v200(result)))

    def _show_form_editor_v200(self,result):
        dialog=FormEditorDialog(result,self)
        try:
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:self._submit('preview_form_v200',dialog.operation(),self._form_preview_v200)
        finally:dialog.deleteLater()

    def _form_preview_v200(self,result):
        self._previewed(result);self._notice('Campo conservado como formulario interactivo. Revisa el resultado y pulsa «Aceptar ✓»; después guarda una copia.')

    def choose_redaction_v200(self):
        if not self.state or self.busy:return
        self._submit('redaction_page_v200',{'page':self.page_number},lambda result:QTimer.singleShot(0,lambda:self._show_redaction_v200(result)))

    def _show_redaction_v200(self,result):
        dialog=RedactionDialog(result,self)
        submit=self._start_dialog_jobs(dialog)
        dialog.pageRequested.connect(lambda page:submit('redaction_page_v200',{'page':page},dialog.set_page))
        try:
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:self._submit('preview_redaction_v200',{'regions':dialog.regions},self._redaction_preview_v200)
        finally:dialog.deleteLater()

    def _redaction_preview_v200(self,result):
        self._previewed(result);self._notice('Vista previa del PDF realmente censurado. Pulsa «Aceptar ✓» y «Guardar como…». La copia elimina los datos cubiertos; el historial local permite deshacer durante el trabajo.')
