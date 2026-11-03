"""Reusable handwritten marks, placed through the validated image worker."""
from contextlib import contextmanager
import math

from PySide6.QtCore import QEvent, QMimeData, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QDrag, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QInputDialog, QLabel, QListView,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
)

from .action_state_v310 import set_ui_enabled_v310, ui_enabled_v310
from .manual_signatures_v317 import SignatureLibraryV317
from .signature_draw_ui_v317 import SignatureDrawingDialogV317
from .tools_ui_v150 import ToolSection
from .workspace_ui_v170 import local_data_directory


SIGNATURE_MIME_V317 = 'application/x-pdfmodder-manual-signature-v317'


def signature_thumbnail_v317(data):
    """White thumbnail backing keeps black ink readable in either UI theme."""
    source = QPixmap()
    if not source.loadFromData(data, 'PNG'):
        raise ValueError('No se puede mostrar la firma guardada.')
    thumbnail = QPixmap(210, 64)
    thumbnail.fill(Qt.white)
    artwork = source.scaled(202, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(thumbnail)
    painter.drawPixmap((210-artwork.width())//2, (64-artwork.height())//2, artwork)
    painter.end()
    return thumbnail


class SignatureListV317(QListWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName('manualSignatureLibraryV317')
        self.setAccessibleName('Firmas manuscritas guardadas')
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setIconSize(QSize(210, 64))
        self.setGridSize(QSize(238, 94))
        self.setMinimumHeight(110)
        self.setMaximumHeight(260)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def signature_mime(self):
        item = self.currentItem()
        if item is None:
            return None
        mime = QMimeData()
        mime.setData(SIGNATURE_MIME_V317, item.data(Qt.UserRole).encode('ascii'))
        return mime

    def startDrag(self, supported_actions):
        if not self.owner._manual_signature_ready_v317():
            return
        mime = self.signature_mime()
        if mime is None:
            return
        try:
            entry = self.owner.signature_library_v317.get(self.currentItem().data(Qt.UserRole))
            pixmap = QPixmap()
            if not pixmap.loadFromData(entry['png'], 'PNG'):
                raise ValueError('No se puede mostrar la firma guardada.')
            pixmap = pixmap.scaled(170, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
            with self.owner._pause_signature_background_v317():
                drag.exec(Qt.CopyAction)
        except (OSError, ValueError) as exc:
            self.owner._error(str(exc))


class _SignatureDropV317(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._validated = None

    def eventFilter(self, watched, event):
        if event.type() == QEvent.DragLeave:
            self._validated = None
            return False
        if event.type() not in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            return False
        if not event.mimeData().hasFormat(SIGNATURE_MIME_V317):
            return False
        owner = self.owner
        if watched is not owner.canvas.viewport() or not owner._manual_signature_ready_v317():
            event.ignore()
            return True
        point = owner.canvas.pdf_point(event.position().toPoint())
        if not owner._signature_point_inside_v317(*point):
            event.ignore()
            return True
        try:
            identifier = bytes(event.mimeData().data(SIGNATURE_MIME_V317)).decode('ascii')
            context = owner._signature_context_v317()
            if self._validated != (identifier, context):
                owner.signature_library_v317.get(identifier)
                self._validated = identifier, context
        except (UnicodeError, OSError, ValueError):
            event.ignore()
            return True
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if event.type() == QEvent.Drop:
            self._validated = None
            QTimer.singleShot(0, lambda: owner._drop_signature_v317(identifier, point, context))
        return True


class SignaturesUiV317Mixin:
    def _create_ui(self):
        super()._create_ui()
        self.signature_library_v317 = SignatureLibraryV317(local_data_directory(self.config_path)/'firmas')
        self._placing_signature_v317 = None
        section = self.signature_tools_section_v317 = ToolSection('Firmas', 'signatureToolsSectionV317')
        layout = self.tools_scroll.widget().layout()
        layout.insertWidget(layout.indexOf(self.advanced_tools_section), section)
        self.create_signature_action_v317 = QAction('Crear firma manual…', self)
        self.create_signature_action_v317.triggered.connect(self._create_signature_v317)
        self._tool_button_v150(section.body, self.create_signature_action_v317, 'createManualSignatureV317', 'edit')
        self.signature_list_v317 = SignatureListV317(self)
        section.body.addWidget(self.signature_list_v317)
        self.signature_hint_v317 = QLabel('Crea una firma y arrástrala a la página. No necesita certificado.')
        self.signature_hint_v317.setWordWrap(True)
        section.body.addWidget(self.signature_hint_v317)
        self.place_signature_action_v317 = QAction('Colocar firma manual', self)
        self.place_signature_action_v317.triggered.connect(self._begin_manual_signature_v317)
        self._tool_button_v150(section.body, self.place_signature_action_v317, 'placeManualSignatureV317', 'image')
        row = QHBoxLayout()
        self.rename_signature_button_v317 = QPushButton('Renombrar…')
        self.rename_signature_button_v317.setObjectName('renameManualSignatureV317')
        self.rename_signature_button_v317.clicked.connect(self._rename_signature_v317)
        self.remove_signature_button_v317 = QPushButton('Eliminar…')
        self.remove_signature_button_v317.setObjectName('removeManualSignatureV317')
        self.remove_signature_button_v317.clicked.connect(self._remove_signature_v317)
        row.addWidget(self.rename_signature_button_v317)
        row.addWidget(self.remove_signature_button_v317)
        section.body.addLayout(row)
        self.visible_signature_action_v317 = QAction('Firmar con certificado visible…', self)
        self.visible_signature_action_v317.triggered.connect(lambda: self.choose_sign_document(visible=True))
        self.invisible_signature_action_v317 = QAction('Firmar con certificado invisible…', self)
        self.invisible_signature_action_v317.triggered.connect(lambda: self.choose_sign_document(visible=False))
        for action, name in ((self.visible_signature_action_v317, 'visibleCertificateSignatureV317'),
                             (self.invisible_signature_action_v317, 'invisibleCertificateSignatureV317')):
            self._tool_button_v150(section.body, action, name)
        self.signature_list_v317.currentItemChanged.connect(lambda *_: self._refresh_signatures_v317())
        self.signature_list_v317.itemDoubleClicked.connect(lambda *_: self._begin_manual_signature_v317())
        self._signature_drop_filter_v317 = _SignatureDropV317(self)
        self.canvas.viewport().setAcceptDrops(True)
        self.canvas.viewport().installEventFilter(self._signature_drop_filter_v317)
        self._reload_signatures_v317()

    @contextmanager
    def _pause_signature_background_v317(self):
        timers = [getattr(self, name, None) for name in ('thumbnail_timer', 'reader_timer_v180',
                  '_workspace_timer_v200', '_preflight_timer_v200')]
        active = [timer for timer in timers if timer and timer.isActive()]
        for timer in active:
            timer.stop()
        try:
            yield
        finally:
            if not self._closed:
                for timer in active:
                    timer.start()

    def _manual_signature_ready_v317(self, *, placing=False):
        model = getattr(self, 'model', None)
        return bool(model and self.application_mode == 'editing' and not self._closed
                    and not self.busy and not self.state.get('preview') and not self.state.get('issues')
                    and not self.compare_action.isChecked() and not self.canvas.editor.isVisible()
                    and not getattr(self, '_rich_active', False) and not getattr(self, '_rich_loading', False)
                    and not getattr(self, '_save_transaction_v300', None)
                    and not getattr(self, '_signature_placement_dialog', None)
                    and not getattr(self, '_cell_draw_v200', False)
                    and not getattr(self, '_mode_preparing_v171', False)
                    and (not self._placement or (placing and self._placement == 'manual_signature_v317'))
                    and not self._navigation_pending_v310()
                    and model.number == self.page_number and self.canvas.model is model
                    and abs(self.canvas.zoom-self.zoom) < 1e-8)

    def _signature_context_v317(self):
        return self._active_session_v200, self.page_number, self.model.revision

    def _signature_point_inside_v317(self, x, y):
        if not self.model or not all(math.isfinite(v) for v in (x, y)):
            return False
        bounds = self.model.cropbox
        return 0 <= x < bounds[2]-bounds[0] and 0 <= y < bounds[3]-bounds[1]

    def _reload_signatures_v317(self, selected_id=None):
        current = self.signature_list_v317.currentItem()
        selected_id = selected_id or (current.data(Qt.UserRole) if current else None)
        self.signature_list_v317.clear()
        try:
            entries = self.signature_library_v317.entries()
            for entry in entries:
                item = QListWidgetItem(QIcon(signature_thumbnail_v317(entry['png'])), entry['name'])
                item.setData(Qt.UserRole, entry['id'])
                item.setToolTip(entry['name']+' · Arrastra a la página o pulsa Colocar firma manual')
                self.signature_list_v317.addItem(item)
                if entry['id'] == selected_id:
                    self.signature_list_v317.setCurrentItem(item)
            if self.signature_list_v317.currentRow() < 0 and entries:
                self.signature_list_v317.setCurrentRow(0)
            self.signature_hint_v317.setText('Arrastra una firma a la página o pulsa Colocar firma manual. '
                'Después puedes moverla, cambiar su tamaño, girarla o borrarla.' if entries else
                'Crea una firma y arrástrala a la página. No necesita certificado.')
        except (OSError, ValueError) as exc:
            self.signature_hint_v317.setText(str(exc))
        self._refresh_signatures_v317()

    def _refresh_actions(self):
        super()._refresh_actions()
        self._refresh_signatures_v317()

    def _finalize_action_states_v310(self):
        super()._finalize_action_states_v310()
        self._refresh_signatures_v317()

    def _refresh_signatures_v317(self):
        if not hasattr(self, 'signature_list_v317'):
            return
        available = not self._closed and not self.busy and not getattr(self, '_signature_placement_dialog', None)
        selected = self.signature_list_v317.currentItem() is not None
        set_ui_enabled_v310(self, self.create_signature_action_v317, available)
        for button in (self.rename_signature_button_v317, self.remove_signature_button_v317):
            set_ui_enabled_v310(self, button, available and selected)
        set_ui_enabled_v310(self, self.place_signature_action_v317, selected and self._manual_signature_ready_v317())
        for action in (self.visible_signature_action_v317, self.invisible_signature_action_v317):
            set_ui_enabled_v310(self, action, ui_enabled_v310(self, self.sign_action))

    def _create_signature_v317(self):
        dialog = SignatureDrawingDialogV317(self)
        try:
            if self._exec_edit_dialog(dialog) != QDialog.Accepted:
                return
            name, png = dialog.signature_data()
            entry = self.signature_library_v317.add(name, png)
            self._reload_signatures_v317(entry['id'])
            self._notice('Firma guardada en este equipo. Arrástrala a la página para colocarla sin certificado.')
        except (OSError, ValueError) as exc:
            self._error(str(exc))
        finally:
            dialog.deleteLater()

    def _rename_signature_v317(self):
        item = self.signature_list_v317.currentItem()
        if item is None:
            return
        dialog = QInputDialog(self)
        dialog.setWindowTitle('Renombrar firma')
        dialog.setLabelText('Nombre de la firma:')
        dialog.setTextValue(item.text())
        try:
            if self._exec_edit_dialog(dialog) == QDialog.Accepted:
                identifier = item.data(Qt.UserRole)
                self.signature_library_v317.rename(identifier, dialog.textValue())
                self._reload_signatures_v317(identifier)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
        finally:
            dialog.deleteLater()

    def _remove_signature_v317(self):
        item = self.signature_list_v317.currentItem()
        if item is None:
            return
        question = QMessageBox(QMessageBox.Question, 'Eliminar firma guardada',
            '¿Eliminar «'+item.text()+'» de la biblioteca? Las firmas ya colocadas en documentos se conservan.',
            QMessageBox.Yes | QMessageBox.No, self)
        question.setDefaultButton(QMessageBox.No)
        question.button(QMessageBox.Yes).setText('Eliminar')
        question.button(QMessageBox.No).setText('Cancelar')
        try:
            if self._exec_edit_dialog(question) == QMessageBox.Yes:
                self.signature_library_v317.remove(item.data(Qt.UserRole))
                self._reload_signatures_v317()
        except (OSError, ValueError) as exc:
            self._error(str(exc))
        finally:
            question.deleteLater()

    def _begin_manual_signature_v317(self):
        if not self._manual_signature_ready_v317():
            return
        item = self.signature_list_v317.currentItem()
        if item is None:
            return
        try:
            self.signature_library_v317.get(item.data(Qt.UserRole))
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return
        self._set_hand_v311(False)
        self._placing_signature_v317 = (item.data(Qt.UserRole), self._signature_context_v317())
        self._placement = 'manual_signature_v317'
        self.canvas.placement_mode = True
        self.canvas.setCursor(Qt.CrossCursor)
        self.canvas.setFocus()
        self._notice('Pulsa en la página para colocar la firma. Escape cancela. No se necesita certificado.')
        self._refresh_actions()

    def _cancel_placement(self):
        self._placing_signature_v317 = None
        return super()._cancel_placement()

    def placed(self, x, y):
        if self._placement != 'manual_signature_v317':
            return super().placed(x, y)
        if not self._manual_signature_ready_v317(placing=True) or not self._signature_point_inside_v317(x, y):
            return
        identifier, context = self._placing_signature_v317
        self._cancel_placement()
        self._drop_signature_v317(identifier, (x, y), context)

    def _drop_signature_v317(self, identifier, point, context):
        if not self._manual_signature_ready_v317() or context != self._signature_context_v317():
            self._notice('La página cambió. Vuelve a colocar la firma en la página deseada.')
            return False
        if not self._signature_point_inside_v317(*point):
            return False
        try:
            entry = self.signature_library_v317.get(identifier)
            page_width = self.model.cropbox[2]-self.model.cropbox[0]
            page_height = self.model.cropbox[3]-self.model.cropbox[1]
            ratio = entry['width_px']/entry['height_px']
            width = min(142., page_width, 72.*ratio, page_height*ratio)
            height = width/ratio
            x = max(0., min(point[0]-width/2, page_width-width))
            y = max(0., min(point[1]-height/2, page_height-height))
            self._set_hand_v311(False)
            self.image_mode_action.setChecked(True)
            self.toggle_image_mode(True)
            self._explicit_image_mode_v150(True)
            payload = {'operation': 'add', 'page': self.page_number, 'image_bytes': entry['png'],
                       'rect': (x, y, x+width, y+height), 'revision': self.model.revision}
            if self.state.get('tagged'):
                payload.update(accessibility_order='page_end', alt_text='Firma manuscrita: '+entry['name'])
            return self._submit('image_apply', payload, self._edited)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return False
