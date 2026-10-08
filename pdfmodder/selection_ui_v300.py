"""Correctable selection scopes and visible draft area controls for version 3."""
from copy import deepcopy

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QPushButton,
    QTextEdit, QVBoxLayout)

from .model import EditError, mm, pt, union
from .selection_v300 import draft_overflow, enlarged_area, selection_index


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
        self.draft_area_tools_v300 = QFrame()
        self.draft_area_tools_v300.setObjectName('draftAreaToolsV300')
        draft_layout = QVBoxLayout(self.draft_area_tools_v300); draft_layout.setContentsMargins(0,0,0,0)
        self.draft_area_status_v300 = QLabel(); self.draft_area_status_v300.setWordWrap(True)
        self.draft_area_status_v300.setObjectName('draftAreaStatusV300')
        draft_layout.addWidget(self.draft_area_status_v300)
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
        self.selection_shrink_v300.setEnabled(enabled)
        self.selection_expand_v300.setEnabled(enabled)
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
        result = super()._open_rich_payload(payload)
        self._draft_area_error_v300 = ''
        if hasattr(self,'draft_area_tools_v300'):
            self.draft_area_tools_v300.show()
            self.selection_shrink_v300.setEnabled(False);self.selection_expand_v300.setEnabled(False)
            QTimer.singleShot(0,self._update_draft_area_v300)
        return result

    def _rich_changed(self, payload):
        self._draft_area_error_v300 = ''
        result = super()._rich_changed(payload)
        self._update_draft_area_v300()
        return result

    def _rich_failed(self, command, message):
        result = super()._rich_failed(command,message)
        if self._rich_active and command in ('rich_preview','rich_apply','rich_prepare','rich_commit'):
            self._draft_area_error_v300 = message
            self._update_draft_area_v300()
        return result

    def _end_rich(self):
        result = super()._end_rich()
        self._draft_area_error_v300 = ''
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
        active_overflow = size_error or (overflow[0] and not payload.get('auto_width')) or (overflow[1] and not payload.get('auto_height'))
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
        self.draft_area_status_v300.setText(message)
        enabled = not self._rich_accept_pending and not self.canvas.editor.pdf_view
        for button in (self.draft_area_button_v300,self.draft_reflow_button_v300,self.draft_size_button_v300):button.setEnabled(enabled)
        self.canvas._draw_overlays()

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
