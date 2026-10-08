"""Properties and affine transformations for the native occurrence graph."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QPen
from PySide6.QtWidgets import (QDialog,QDialogButtonBox,QVBoxLayout,QHBoxLayout,
    QFormLayout,QLabel,QTreeWidget,QTreeWidgetItem,QComboBox,QDoubleSpinBox,
    QPushButton,QCheckBox,QColorDialog,QGraphicsView,QGraphicsScene)

from .model import mm,pt,transform_rect


class NativeObjectsDialog(QDialog):
    def __init__(self,info,parent=None):
        super().__init__(parent)
        self.info=info;self.result_request=None;self.colours={};self._selected_id=None
        self.setWindowTitle('Objetos PDF · posición, forma y propiedades')
        self.resize(920,640)
        layout=QVBoxLayout(self)
        tip=QLabel('Selecciona una aparición o un grupo. Los cambios conservan texto, imágenes, vectores, capas y recortes del PDF.');tip.setWordWrap(True);layout.addWidget(tip)
        body=QHBoxLayout();layout.addLayout(body)
        self.tree=QTreeWidget();self.tree.setObjectName('nativeObjectTreeV300')
        self.tree.setHeaderLabels(['Objeto','Capas / recurso'])
        inventory=QVBoxLayout();body.addLayout(inventory,3);inventory.addWidget(self.tree,3)
        self.page_preview=None;self.highlight=None;self.preview_matrix=None
        canvas=getattr(parent,'canvas',None);model=getattr(parent,'model',None)
        pixmap_item=getattr(canvas,'_pixmap_item',None)
        if pixmap_item is not None and model is not None:
            self.preview_matrix=model.rotation_matrix
            self.preview_zoom=canvas.zoom
            self.page_preview=QGraphicsView();self.page_preview.setObjectName('nativeObjectPagePreviewV300')
            scene=QGraphicsScene(self.page_preview);self.page_preview.setScene(scene)
            pixmap=pixmap_item.pixmap();scene.addPixmap(pixmap);scene.setSceneRect(QRectF(pixmap.rect()))
            self.page_preview.setBackgroundBrush(Qt.darkGray)
            inventory.addWidget(self.page_preview,2)
        rows={}
        for obj in info['items']:
            parent_row=rows.get(obj.get('parent'))
            row=QTreeWidgetItem(parent_row or self.tree,[obj['label'],', '.join(obj.get('layers',[])) or obj.get('resource') or ''])
            row.setData(0,Qt.UserRole,obj);rows[obj['id']]=row
            row.setToolTip(0,obj.get('capabilities',{}).get('reason',''))
        self.tree.expandToDepth(0)
        controls=QVBoxLayout();body.addLayout(controls,2)
        self.description=QLabel('Selecciona un objeto.');self.description.setWordWrap(True);controls.addWidget(self.description)
        form=QFormLayout();controls.addLayout(form)
        self.operation=QComboBox();self.operation.setObjectName('nativeObjectOperationV300')
        for label,value in [('Mover','move'),('Cambiar escala','scale'),('Girar','rotate'),('Duplicar','duplicate'),('Modificar propiedades','properties')]:
            self.operation.addItem(label,value)
        form.addRow('Operación',self.operation)
        self.dx=self.spin(-2000,2000,0);self.dy=self.spin(-2000,2000,0)
        form.addRow('Desplazamiento X (mm)',self.dx);form.addRow('Desplazamiento Y (mm)',self.dy)
        self.sx=self.spin(-1000,1000,100);self.sy=self.spin(-1000,1000,100)
        form.addRow('Escala X (%)',self.sx);form.addRow('Escala Y (%)',self.sy)
        self.angle=self.spin(-3600,3600,0);form.addRow('Giro (°)',self.angle)
        self.opacity_enabled=QCheckBox('Cambiar opacidad');self.opacity=self.spin(0,100,100)
        form.addRow(self.opacity_enabled,self.opacity)
        self.width_enabled=QCheckBox('Cambiar grosor');self.width=self.spin(0,1000,1)
        form.addRow(self.width_enabled,self.width)
        self.fill=QPushButton('Elegir color de relleno…');self.stroke=QPushButton('Elegir color de trazo…')
        controls.addWidget(self.fill);controls.addWidget(self.stroke)
        self.fill.clicked.connect(lambda:self.pick_colour('fill_color',self.fill))
        self.stroke.clicked.connect(lambda:self.pick_colour('stroke_color',self.stroke))
        self.message=QLabel('El giro y la escala se aplican desde el centro del objeto. Los desplazamientos se expresan en coordenadas de la página.');self.message.setWordWrap(True)
        controls.addWidget(self.message);controls.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel)
        self.preview=buttons.addButton('Previsualizar',QDialogButtonBox.AcceptRole)
        self.preview.setObjectName('nativeObjectPreviewV300')
        self.preview.clicked.connect(self.choose);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.tree.currentItemChanged.connect(self.refresh)
        self.operation.currentIndexChanged.connect(self.refresh)
        if self.tree.topLevelItemCount():self.tree.setCurrentItem(self.tree.topLevelItem(0))

    @staticmethod
    def spin(low,high,value):
        field=QDoubleSpinBox();field.setRange(low,high);field.setDecimals(3);field.setValue(value);return field

    def selected_object(self):
        row=self.tree.currentItem()
        return row.data(0,Qt.UserRole) if row else None

    def refresh(self,*unused):
        obj=self.selected_object()
        if not obj:return
        caps=obj['capabilities'];op=self.operation.currentData()
        r=obj.get('rect')
        location=(f'Área: {mm(r[0]):.1f}, {mm(r[1]):.1f} mm · {mm(r[2]-r[0]):.1f} × {mm(r[3]-r[1]):.1f} mm.' if r else 'Área no disponible.')
        self.description.setText(obj['label']+'\n'+location+('\nRecurso compartido: se modifica esta aparición.' if obj['properties'].get('occurrences_on_page',1)>1 else ''))
        self.dx.setEnabled(op in ('move','duplicate','scale','rotate'));self.dy.setEnabled(self.dx.isEnabled())
        self.sx.setEnabled(op=='scale');self.sy.setEnabled(op=='scale');self.angle.setEnabled(op=='rotate')
        self.opacity_enabled.setEnabled(bool(caps.get('opacity')))
        self.width_enabled.setEnabled(bool(caps.get('line_width')))
        self.fill.setEnabled(bool(caps.get('fill_color')));self.stroke.setEnabled(bool(caps.get('stroke_color')))
        enabled=any(caps.get(key) for key in ('opacity','fill_color','stroke_color','line_width')) if op=='properties' else caps.get(op,False)
        self.preview.setEnabled(bool(enabled))
        self.message.setText(caps['reason'] or (caps.get('transform_reason') if op!='properties' else '') or (caps.get('duplicate_reason') if op=='duplicate' and not enabled else '') or
            'Previsualiza el resultado y acéptalo para incorporarlo al historial. Las áreas activas de campos, enlaces y anotaciones se comprueban antes de transformar.')
        if self._selected_id!=obj['id']:
            self._selected_id=obj['id'];self.colours={}
            self.fill.setText('Elegir color de relleno…');self.stroke.setText('Elegir color de trazo…')
            self.opacity_enabled.setChecked(False);self.width_enabled.setChecked(False)
        if self.page_preview:
            scene=self.page_preview.scene()
            if self.highlight is not None:scene.removeItem(self.highlight);self.highlight=None
            if r:
                x0,y0,x1,y1=transform_rect(r,self.preview_matrix)
                z=self.preview_zoom
                pen=QPen(QColor('#e431ab'));pen.setWidthF(2);pen.setCosmetic(True)
                self.highlight=scene.addRect(QRectF(x0*z,y0*z,(x1-x0)*z,(y1-y0)*z),pen)
            self.page_preview.fitInView(scene.sceneRect(),Qt.KeepAspectRatio)
        if not caps.get('opacity'):self.opacity_enabled.setChecked(False)
        if not caps.get('line_width'):self.width_enabled.setChecked(False)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.page_preview:
            self.page_preview.fitInView(self.page_preview.sceneRect(),Qt.KeepAspectRatio)

    def pick_colour(self,key,button):
        colour=QColorDialog.getColor(parent=self,title='Color del objeto PDF')
        if colour.isValid():
            self.colours[key]=[colour.redF(),colour.greenF(),colour.blueF()]
            button.setText('Color elegido: '+colour.name())

    def choose(self):
        obj=self.selected_object()
        if not obj:return
        props=dict(self.colours)
        if self.opacity_enabled.isEnabled() and self.opacity_enabled.isChecked():props['opacity']=self.opacity.value()/100
        if self.width_enabled.isEnabled() and self.width_enabled.isChecked():props['line_width']=self.width.value()
        operation=self.operation.currentData()
        if operation=='properties' and not props:
            self.message.setText('Elige una propiedad que quieras cambiar.');return
        self.result_request={'page':self.info['page'],'revision':self.info['revision'],
            'object_id':obj['id'],'operation':operation,'dx':pt(self.dx.value()),'dy':pt(self.dy.value()),
            'scale_x':self.sx.value()/100,'scale_y':self.sy.value()/100,'angle':self.angle.value(),
            'properties':props}
        self.accept()


class ObjectEditorV300Mixin:
    def _init_object_editor_v300(self):
        self.native_objects_action=self._action('Editar objetos PDF…',self.open_native_objects_v300,'Ctrl+Shift+G')
        self.native_objects_action.setObjectName('nativeObjectsActionV300')
        self._tool_button_v150(self.content_tools_section.body,self.native_objects_action,'toolNativeObjectsV300')

    def open_native_objects_v300(self):
        if self.busy or not self.model or self.state.get('preview') or self.canvas.editor.isVisible():return
        def received(info):
            dialog=NativeObjectsDialog(info,self)
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:
                self._submit('object_edit_v300',dialog.result_request,self._previewed)
        self._submit('object_graph_v300',{'page':self.page_number},received)


ObjectEditorMixin=ObjectEditorV300Mixin
