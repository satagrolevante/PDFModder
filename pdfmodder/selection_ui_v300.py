"""Correctable selection scopes and visible draft area controls for version 3."""
from copy import deepcopy

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QPushButton,
    QTextEdit, QVBoxLayout)

from .model import EditError, mm, pt, union
from .selection_v300 import draft_overflow, enlarged_area, selection_index
from .action_state_v310 import set_ui_enabled_v310


class DraftAreaDialogV300(QDialog):
    def __init__(self, rect, page_rect, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Modificar área de texto')
        self.setObjectName('draftAreaDialogV300')
        self.rect = rect
        layout = QVBoxLayout(self)
        note = QLabel('El texto conserva sus tamaños y formatos. Al aceptar el borrador se comprueban los límites y los elementos vecinos.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.width = QDoubleSpinBox(); self.height = QDoubleSpinBox()
        self.width.setObjectName('draftWidthV300'); self.height.setObjectName('draftHeightV300')
        for box, value, maximum in ((self.width,rect[2]-rect[0],page_rect[2]-rect[0]),
                                    (self.height,rect[3]-rect[1],page_rect[3]-rect[1])):
            box.setDecimals(2); box.setRange(.01,max(.01,mm(maximum)))
            box.setSuffix(' mm'); box.setValue(mm(value))
        form.addRow('Anchura',self.width); form.addRow('Altura',self.height)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def area(self):
        return (self.rect[0],self.rect[1],self.rect[0]+pt(self.width.value()),self.rect[1]+pt(self.height.value()))


class NeighborLayoutDialogV303(QDialog):
    """Choose the parent scope before extending the active draft."""
    def __init__(self,payload,model,mode,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Redistribuir texto vecino')
        self.setObjectName('neighborLayoutDialogV303')
        self.payload=payload;self.model=model
        layout=QVBoxLayout(self)
        note=QLabel('Los textos vecinos compatibles se incorporarán a este mismo borrador. '
                    'Podrás revisar la vista PDF antes de aceptar una sola operación o cancelar todo.')
        note.setWordWrap(True);layout.addWidget(note)
        self.scope_box=QComboBox();self.scope_box.setObjectName('neighborLayoutScopeV303')
        for label,scope in (('Párrafo','paragraph'),('Celda delimitada','cell'),('Área actual del borrador','area')):
            self.scope_box.addItem(label,scope)
        default='area' if not payload.get('ids') else ('cell' if mode=='cell' else 'paragraph')
        self.scope_box.setCurrentIndex(self.scope_box.findData(default))
        layout.addWidget(self.scope_box)
        self.preview=QLabel();self.preview.setWordWrap(True);self.preview.setObjectName('neighborLayoutPreviewV303')
        layout.addWidget(self.preview)
        self.scope_box.currentIndexChanged.connect(self._update_preview)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Preparar borrador')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self._update_preview()

    def scope(self):return self.scope_box.currentData()

    def _update_preview(self):
        descriptions={
            'paragraph':'Usa el párrafo que contiene la selección, respetando sus límites y columnas.',
            'cell':'Usa la celda delimitada que contiene la selección; sus bordes limitan la redistribución.',
            'area':'Usa el cuadro actual del borrador y conserva los textos situados fuera de ese cuadro.',
        }
        message=descriptions[self.scope()]
        selected=self.model.selected(self.payload.get('ids',[])) if self.model else []
        if selected and self.scope() in ('paragraph','cell'):
            scope=selection_index(self.model).scope(selected[0],self.scope())
            text=self.model.text(scope.ids)
            if text:message+='\n\nTexto del ámbito sugerido:\n'+text[:400]+('…' if len(text)>400 else '')
        rect=self.payload.get('rect')
        if self.scope()=='area' and rect and len(rect)==4:
            message+=f'\n\nÁrea: {mm(rect[2]-rect[0]):.2f} × {mm(rect[3]-rect[1]):.2f} mm.'
        message+='\n\nEl análisis del PDF comprobará qué vecinos pueden incorporarse sin alterar otros elementos.'
        self.preview.setText(message)


class SelectionUiV300Mixin:
    def _init_selection_v300(self):
        # Keep the original extraction block available as an explicit scope.
        index = self.mode_box.findData('block')
        if index >= 0:self.mode_box.setItemText(index,'Grupo del PDF')
        for label,value in (('Párrafo','paragraph'),('Celda delimitada','cell')):
            if self.mode_box.findData(value)<0:self.mode_box.addItem(label,value)
        self.mode_box.setToolTip('Palabra, línea y párrafo respetan espacios, columnas y bordes gráficos. Celda utiliza un recinto cerrado; puedes corregir el área manualmente.')
        self.mode_box.currentIndexChanged.connect(self._selection_mode_changed_v300)
        self.selection_scope_note_v300 = QLabel('Elige el alcance y pulsa el texto. Ctrl+clic añade o quita fragmentos.')
        self.selection_scope_note_v300.setObjectName('selectionScopeNoteV300')
        self.selection_scope_note_v300.setWordWrap(True)
        row = QFrame(); layout = QVBoxLayout(row); layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.selection_scope_note_v300)
        buttons = QHBoxLayout()
        self.selection_shrink_v300 = QPushButton('Reducir alcance')
        self.selection_expand_v300 = QPushButton('Ampliar alcance')
        self.selection_shrink_v300.setObjectName('selectionShrinkV300')
        self.selection_expand_v300.setObjectName('selectionExpandV300')
        self.selection_shrink_v300.clicked.connect(lambda:self._step_selection_v300(-1))
        self.selection_expand_v300.clicked.connect(lambda:self._step_selection_v300(1))
        buttons.addWidget(self.selection_shrink_v300); buttons.addWidget(self.selection_expand_v300)
        layout.addLayout(buttons)
        self.property_box.layout().insertRow(2,row)
        self.canvas.selection_changed.connect(self._selection_note_v300)
        self._draft_area_error_v300 = ''
        self._neighbor_request_v303=None
        self._neighbor_layout_info_v303=None
        self.draft_area_tools_v300 = QFrame()
        self.draft_area_tools_v300.setObjectName('draftAreaToolsV300')
        draft_layout = QVBoxLayout(self.draft_area_tools_v300); draft_layout.setContentsMargins(0,0,0,0)
        self.draft_area_status_v300 = QLabel(); self.draft_area_status_v300.setWordWrap(True)
        self.draft_area_status_v300.setObjectName('draftAreaStatusV300')
        draft_layout.addWidget(self.draft_area_status_v300)
        self.draft_overlap_box_v303=QCheckBox('Permitir solapamiento automáticamente')
        self.draft_overlap_box_v303.setObjectName('draftTextOverlapV303')
        self.draft_overlap_box_v303.setToolTip('Si este borrador alcanza texto vecino, permite la superposición sin borrar ni mover los vecinos. '
            'Revisa la legibilidad en la vista PDF o usa «Redistribuir texto vecino». '
            'Desmarca esta opción si prefieres impedir nuevas superposiciones.')
        self.draft_overlap_box_v303.toggled.connect(self._set_draft_overlap_v303)
        draft_layout.addWidget(self.draft_overlap_box_v303)
        self.draft_neighbors_button_v303=QPushButton('Redistribuir texto vecino…')
        self.draft_neighbors_button_v303.setObjectName('draftNeighborsV303')
        self._neighbor_tooltip_v303=('Elige el párrafo, la celda o el área cuyos textos '
            'compatibles se incorporarán al borrador. Aceptar aplicará el conjunto en una sola operación.')
        self.draft_neighbors_button_v303.setToolTip(self._neighbor_tooltip_v303)
        self.draft_neighbors_button_v303.clicked.connect(lambda:self._redistribute_neighbors_draft_v303())
        draft_layout.addWidget(self.draft_neighbors_button_v303)
        self.draft_area_button_v300 = QPushButton('Ampliar área…')
        self.draft_reflow_button_v300 = QPushButton('Redistribuir líneas')
        self.draft_size_button_v300 = QPushButton('Cambiar tamaño…')
        self.draft_area_button_v300.setObjectName('draftAreaV300')
        self.draft_reflow_button_v300.setObjectName('draftReflowV300')
        self.draft_size_button_v300.setObjectName('draftSizeV300')
        self.draft_area_button_v300.setToolTip('Elige las dimensiones del cuadro manteniendo su posición, tamaño de letra y formatos.')
        self.draft_reflow_button_v300.setToolTip('Une los saltos suaves para repartir las líneas dentro del cuadro. Conserva los párrafos y los formatos.')
        self.draft_size_button_v300.setToolTip('Elige expresamente un tamaño de letra para todo el borrador.')
        for button in (self.draft_area_button_v300,self.draft_reflow_button_v300,self.draft_size_button_v300):
            draft_layout.addWidget(button)
        self.draft_area_button_v300.clicked.connect(self._modify_draft_area_v300)
        self.draft_reflow_button_v300.clicked.connect(self._reflow_draft_v300)
        self.draft_size_button_v300.clicked.connect(self._resize_draft_font_v300)
        self.rich_result.layout().addWidget(self.draft_area_tools_v300)
        self.draft_area_tools_v300.hide()
        self.canvas.editor.document().documentLayout().documentSizeChanged.connect(lambda _:self._update_draft_area_v300())
        self.canvas.editor.visibility_changed.connect(lambda _:QTimer.singleShot(0,self._update_draft_area_v300))
        self.canvas.editor.toolbar.pdf_button.toggled.connect(lambda _:self._update_draft_area_v300())

    def _selection_mode_changed_v300(self):
        if not self.model or not self.canvas.ids or self.canvas.editor.isVisible() or self.busy:
            return
        anchor_id = self.canvas._anchor_id
        anchor = next((g for g in self.model.glyphs if g.id==anchor_id),None)
        if anchor is None:
            anchor = self.model.selected(self.canvas.ids)[0]
        self.canvas.set_selection(self.model.group(anchor,self.mode_box.currentData()))

    def _step_selection_v300(self, step):
        modes = ('character','word','line','paragraph','cell')
        mode = self.mode_box.currentData()
        index = modes.index(mode) if mode in modes else 3
        self.mode_box.setCurrentIndex(self.mode_box.findData(modes[max(0,min(len(modes)-1,index+step))]))

    def _selection_note_v300(self, ids):
        enabled = bool(ids and self.model and self.application_mode=='editing' and not self.canvas.editor.isVisible())
        set_ui_enabled_v310(self, self.selection_shrink_v300, enabled)
        set_ui_enabled_v310(self, self.selection_expand_v300, enabled)
        if not ids or not self.model:
            self.selection_scope_note_v300.setText('Elige el alcance y pulsa el texto. Ctrl+clic añade o quita fragmentos.')
            return
        first = self.model.selected(ids)[0]
        mode = self.mode_box.currentData()
        scope = selection_index(self.model).scope(first,mode)
        if mode=='cell' and selection_index(self.model).cell_rect(first):
            description = 'Celda detectada por sus bordes. «Delimitar párrafo / celda» permite corregir el recinto.'
        elif mode=='cell':
            description = 'Sin recinto cerrado: se ha sugerido un párrafo. Puedes delimitar el área manualmente.'
        elif set(ids)!=set(scope.ids):
            description = 'Selección manual. Cambiar el alcance toma como referencia el punto inicial.'
        else:
            description = 'Alcance sugerido. Reduce, amplía o usa Ctrl+clic para corregirlo.'
        self.selection_scope_note_v300.setText(description)

    def _open_rich_payload(self, payload):
        payload = deepcopy(payload)
        payload.pop('neighbor_layout_info',None)
        natural = union(g.bbox for g in self.model.selected(payload.get('ids', []))) if self.model else None
        # An explicit resize, delimited area or restored draft already carries
        # its chosen rectangle. Apply the cell suggestion only to a fresh
        # selection payload whose area is still the extracted text bounds.
        fresh_area = (not payload.pop('_explicit_area_v300', False) and natural
                      and len(payload.get('rect', ())) == 4
                      and all(abs(a-b) < .05 for a,b in zip(payload['rect'], natural)))
        if fresh_area and self.canvas.selection_rect_v300 and set(payload.get('ids',[]))==set(self.canvas.ids):
            rect = self.canvas.selection_rect_v300
            inner = (rect[0]+2,rect[1]+2,rect[2]-2,rect[3]-2)
            if inner[2]>inner[0] and inner[3]>inner[1]:
                payload.update(rect=list(inner),width=inner[2]-inner[0],height=inner[3]-inner[1],auto_width=False,auto_height=False)
        ids=payload.get('ids',[])
        if self.model and set(ids)!=set(self.canvas.ids):self.canvas.set_selection(ids,notify=False)
        result = super()._open_rich_payload(payload)
        self._neighbor_layout_info_v303=None
        self._draft_area_error_v300 = ''
        if hasattr(self,'draft_area_tools_v300'):
            with QSignalBlocker(self.draft_overlap_box_v303):
                self.draft_overlap_box_v303.setChecked(bool(self.canvas.editor._payload.get('allow_overlap',False)))
            self.draft_area_tools_v300.show()
            self.selection_shrink_v300.setEnabled(False);self.selection_expand_v300.setEnabled(False)
            section=getattr(self,'format_tools_section',None)
            if section is not None:section.set_expanded(True)
            tools=getattr(self,'tools_scroll',None)
            if tools is not None:
                tools.show();QTimer.singleShot(0,lambda:tools.ensureWidgetVisible(self.draft_area_tools_v300))
            QTimer.singleShot(0,self._update_draft_area_v300)
        return result

    def _refresh_actions(self):
        result=super()._refresh_actions()
        self._update_draft_area_v300()
        return result

    def _rich_accept(self,payload):
        if getattr(self,'_neighbor_request_v303',None):return
        result=super()._rich_accept(payload)
        self._update_draft_area_v300()
        return result

    def _rich_pump(self):
        if getattr(self,'_neighbor_request_v303',None):
            if self._rich_active and self._rich_pending is not None:self._rich_timer.start(50)
            return
        return super()._rich_pump()

    def _rich_changed(self, payload):
        self._draft_area_error_v300 = ''
        result = super()._rich_changed(payload)
        self._update_draft_area_v300()
        return result

    def _rich_failed(self, command, message):
        if command=='rich_redistribute':
            request=self._neighbor_request_v303
            if request is None:return
            self._neighbor_request_v303=None
            if not self._neighbor_request_current_v303(request):
                self._update_draft_area_v300();return
        result = super()._rich_failed(command,message)
        if self._rich_active and command in ('rich_preview','rich_apply','rich_prepare','rich_commit','rich_redistribute'):
            self._draft_area_error_v300 = message
            self._update_draft_area_v300()
        return result

    def _end_rich(self):
        result = super()._end_rich()
        self._draft_area_error_v300 = ''
        self._neighbor_request_v303=None;self._neighbor_layout_info_v303=None
        self.canvas.draft_overflow_rect_v300 = None
        if hasattr(self,'draft_area_tools_v300'):self.draft_area_tools_v300.hide()
        self.canvas._draw_overlays()
        return result

    def _draft_dimensions_v300(self):
        editor = self.canvas.editor
        scale = max(.01,self.canvas.zoom)
        return max(0.,editor.document().idealWidth()/scale),max(0.,editor.document().size().height()/scale)

    def _update_draft_area_v300(self):
        if not hasattr(self,'draft_area_status_v300') or not self._rich_active or not self.canvas.editor.isVisible():return
        payload = self.canvas.editor._payload
        rect = payload.get('rect') or self.canvas._editor_bounds
        if not rect:return
        required_width,required_height = self._draft_dimensions_v300()
        overflow = draft_overflow(rect,required_width,required_height,tolerance=2.)
        # A validation failure is authoritative; the local draft measurement
        # merely highlights likely overflow before the PDF worker replies.
        size_error = any(word in self._draft_area_error_v300.lower() for word in ('altura','anchura','cuadro','espacio disponible','área','borde'))
        overlap_error=any(word in self._draft_area_error_v300.lower() for word in ('solap','superpon','overlap'))
        active_overflow = size_error or (not payload.get('auto_adapt') and
            ((overflow[0] and not payload.get('auto_width')) or (overflow[1] and not payload.get('auto_height'))))
        if active_overflow:
            self.canvas.draft_overflow_rect_v300 = (rect[0],rect[1],max(rect[2],rect[0]+required_width),max(rect[3],rect[1]+required_height))
            message = ('El borrador supera el área disponible. ' if not self._draft_area_error_v300 else self._draft_area_error_v300+' ')
            message += 'Puedes ampliar el área, redistribuir líneas o elegir el tamaño. Tu texto sigue en el borrador.'
            self.draft_area_status_v300.setStyleSheet('color: #a32b22;')
        else:
            self.canvas.draft_overflow_rect_v300 = None
            message = 'Área del borrador: puedes ajustar el cuadro y redistribuir líneas conservando el formato. Aceptar comprueba el resultado.'
            if self._draft_area_error_v300:message = 'El borrador se conserva: '+self._draft_area_error_v300
            self.draft_area_status_v300.setStyleSheet('')
        if overlap_error:
            message+=' Puedes permitir el solapamiento con texto vecino.'
            message+=(' También puedes redistribuir esos textos en el mismo borrador.' if payload.get('ids') else
                      ' Para redistribuir vecinos, abre el borrador desde una selección de texto existente.')
            self.draft_area_status_v300.setStyleSheet('color: #a32b22;')
        info=getattr(self,'_neighbor_layout_info_v303',None)
        if info:
            count=info.get('neighbor_count')
            message+=('\nSe han incorporado '+str(count)+' caracteres vecinos al borrador.' if count is not None
                      else '\nLos textos vecinos compatibles forman parte del borrador.')
            message+=' Revisa el conjunto antes de aceptar; Cancelar conserva el PDF anterior.'
        self.draft_area_status_v300.setText(message)
        enabled = (not self._rich_accept_pending and not self.canvas.editor.pdf_view
                   and not getattr(self,'_save_transaction_v300',None))
        for button in (self.draft_area_button_v300,self.draft_reflow_button_v300,self.draft_size_button_v300):set_ui_enabled_v310(self, button, enabled)
        set_ui_enabled_v310(self, self.draft_overlap_box_v303, enabled)
        set_ui_enabled_v310(self, self.draft_neighbors_button_v303, enabled and bool(payload.get('ids'))
            and not self.busy and not self._neighbor_request_v303)
        self.draft_neighbors_button_v303.setToolTip(self._neighbor_tooltip_v303 if payload.get('ids') else
            'Redistribuir vecinos requiere seleccionar texto existente antes de abrir el borrador.')
        set_ui_enabled_v310(self, self.canvas.editor.toolbar.accept, not self._rich_accept_pending and not self._neighbor_request_v303
            and not getattr(self,'_save_transaction_v300',None))
        self.canvas._draw_overlays()

    def _schedule_draft_persistence_v303(self):
        timer=getattr(self,'_workspace_timer_v200',None)
        if timer is not None:timer.start(750)

    def _set_draft_overlap_v303(self,checked):
        editor=self.canvas.editor
        if not self._rich_active or self._rich_accept_pending or editor.pdf_view:return
        editor._payload['allow_overlap']=bool(checked)
        editor._draft_changed=True
        self._rich_changed(editor.payload())
        self._schedule_draft_persistence_v303()

    def _neighbor_context_v303(self):
        return (getattr(self,'_active_session_v200',None),self.page_number,self.model.revision,
                tuple(self.canvas.ids)) if self.model else None

    def _neighbor_request_current_v303(self,request):
        return (self._rich_active and self._rich_generation==request['generation']
                and self._rich_serial==request['serial'] and self._neighbor_context_v303()==request['context']
                and self.canvas.editor.payload()==request['payload'])

    def _redistribute_neighbors_draft_v303(self,scope=None):
        editor=self.canvas.editor
        if (not self._rich_active or self._rich_accept_pending or editor.pdf_view or self.busy
                or self._neighbor_request_v303 or not self.model or not editor._payload.get('ids')):return False
        was_active=self._rich_timer.isActive();remaining=self._rich_timer.remainingTime()
        self._rich_timer.stop()
        if scope is None:
            dialog=NeighborLayoutDialogV303(editor.payload(),self.model,self.mode_box.currentData(),self)
            if self._exec_edit_dialog(dialog)!=QDialog.Accepted:
                if was_active and self._rich_pending is not None:self._rich_timer.start(max(0,remaining))
                return False
            scope=dialog.scope()
        if scope not in ('paragraph','cell','area'):
            if was_active and self._rich_pending is not None:self._rich_timer.start(max(0,remaining))
            return False
        self._rich_timer.stop()
        self._rich_serial+=1;self._rich_pending=None
        context=self._neighbor_context_v303()
        request={'generation':self._rich_generation,'serial':self._rich_serial,'context':context,
                 'payload':deepcopy(editor.payload())}
        self._neighbor_request_v303=request
        self._update_draft_area_v300()
        def ready(result):
            if self._neighbor_request_v303 is not request:return
            self._neighbor_request_v303=None
            if not self._neighbor_request_current_v303(request):
                self._update_draft_area_v300()
                return
            payload=deepcopy(result)
            info=payload.pop('neighbor_layout_info',None)
            if payload.get('revision')!=self.model.revision or payload.get('page')!=self.page_number:
                self._update_draft_area_v300();return
            valid_ids={glyph.id for glyph in self.model.glyphs}
            if not set(payload.get('ids',[])).issubset(valid_ids):
                self._draft_area_error_v300='La propuesta no corresponde a los caracteres del documento actual.'
                self._update_draft_area_v300()
                return
            payload['_explicit_area_v300']=True
            self._rich_generation+=1
            self._open_rich_payload(payload)
            self._neighbor_layout_info_v303=info or {'scope':scope}
            self._editing_context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
            self._rich_changed(editor.payload())
            self._schedule_draft_persistence_v303()
            editor.setFocus()
        try:accepted=self._submit('rich_redistribute',{'request':request['payload'],'scope':scope},ready)
        except Exception as exc:
            self._rich_failed('rich_redistribute',str(exc));return False
        if not accepted:
            self._rich_failed('rich_redistribute','No se pudo preparar la redistribución. El texto sigue en el borrador.')
        return bool(accepted)

    def _modify_draft_area_v300(self):
        if not self._rich_active or self._rich_accept_pending or not self.model:return
        editor = self.canvas.editor
        rect = tuple(editor._payload.get('rect') or self.canvas._editor_bounds)
        page_rect = (0.,0.,self.model.cropbox[2]-self.model.cropbox[0],self.model.cropbox[3]-self.model.cropbox[1])
        width,height = self._draft_dimensions_v300()
        try:suggested = enlarged_area(rect,width,height,page_rect)
        except EditError:suggested = rect
        dialog = DraftAreaDialogV300(suggested,page_rect,self)
        if self._exec_edit_dialog(dialog)!=QDialog.Accepted:return
        self._apply_draft_area_v300(dialog.area())

    def _apply_draft_area_v300(self, rect):
        if not self._rich_active or self._rich_accept_pending:return
        editor = self.canvas.editor
        editor._payload.update(rect=list(rect),width=rect[2]-rect[0],height=rect[3]-rect[1],auto_width=False,auto_height=False)
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        self.canvas._editor_bounds=tuple(rect);self.canvas._place_editor()
        self._rich_changed(editor.payload())
        editor.setFocus()

    def _reflow_draft_v300(self):
        if not self._rich_active or self._rich_accept_pending:return
        editor = self.canvas.editor
        # Replace soft breaks only, working backwards to preserve offsets and
        # each run's stored font/style. Explicit paragraphs remain paragraphs.
        positions = []
        block = editor.document().begin()
        while block.isValid():
            text = block.text()
            for index,char in enumerate(text):
                if char=='\u2028':
                    replacement = '' if index>0 and text[index-1].isspace() or index+1<len(text) and text[index+1].isspace() else ' '
                    positions.append((block.position()+index,replacement))
            block = block.next()
        cursor = QTextCursor(editor.document());cursor.beginEditBlock()
        for position,replacement in reversed(positions):
            cursor.setPosition(position);cursor.setPosition(position+1,QTextCursor.KeepAnchor)
            cursor.insertText(replacement)
        cursor.endEditBlock()
        editor._payload.update(auto_width=False,auto_height=False)
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        self._rich_changed(editor.payload());editor.setFocus()

    def _resize_draft_font_v300(self):
        if not self._rich_active or self._rich_accept_pending:return
        editor = self.canvas.editor
        value = float(editor.current_style().get('size',12.))
        size,accepted = QInputDialog.getDouble(self,'Tamaño de todo el borrador','Tamaño de letra (pt)',value,.1,1000.,2)
        if not accepted:return
        saved = editor.textCursor()
        cursor = QTextCursor(editor.document());cursor.select(QTextCursor.Document);editor.setTextCursor(cursor)
        editor.merge_style(size=size)
        editor.setTextCursor(saved)
        self._rich_changed(editor.payload())
