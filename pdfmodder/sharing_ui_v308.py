"""Share an explicitly saved PDF through the clipboard or its folder."""
from hashlib import sha256
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QLabel,
    QPushButton, QVBoxLayout,
)

from .saving_ui_v300 import default_save_path_v300


def _file_stamp_v308(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def verified_share_file_v308(path, revision):
    """Check bytes only; sharing never reparses or reconstructs a PDF."""
    if not path or not revision:
        return None
    try:
        path = Path(path).resolve()
        before = _file_stamp_v308(path)
        digest = sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if _file_stamp_v308(path) == before and digest.hexdigest() == revision:
            return path, before
    except OSError:
        pass
    return None


class ShareDialogV308(QDialog):
    def __init__(self, path, stamp, parent=None):
        super().__init__(parent)
        self.path, self.stamp = Path(path), stamp
        self.setWindowTitle('Compartir PDF')
        self.setObjectName('sharePdfDialogV308')
        self.resize(520, 220)
        layout = QVBoxLayout(self)
        name = QLabel(str(self.path))
        name.setTextFormat(Qt.PlainText)
        name.setWordWrap(True)
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(name)
        note = QLabel('Copia el archivo para pegarlo como adjunto en tu correo u otra aplicación, o abre su carpeta para seleccionarlo.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.copy_button = QPushButton('Copiar archivo')
        self.copy_button.setObjectName('shareCopyFileV308')
        self.copy_button.clicked.connect(self.copy_file)
        layout.addWidget(self.copy_button)
        self.folder_button = QPushButton('Abrir carpeta')
        self.folder_button.setObjectName('shareOpenFolderV308')
        self.folder_button.clicked.connect(self.open_folder)
        layout.addWidget(self.folder_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('Cerrar')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _available(self):
        try:
            if _file_stamp_v308(self.path) == self.stamp:
                return True
        except OSError:
            pass
        self.status.setText('El archivo ha cambiado o ya no está disponible. Cierra este cuadro y vuelve a pulsar Compartir.')
        self.copy_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        return False

    def copy_file(self):
        if not self._available():
            return
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(self.path))])
        QApplication.clipboard().setMimeData(data)
        self.status.setText('Archivo copiado. Pégalo en la aplicación donde quieras compartirlo.')

    def open_folder(self):
        if self._available() and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent))):
            self.status.setText('No se ha podido abrir la carpeta.')


class SharingUiV308Mixin:
    def _show_share_v308(self, verified):
        if getattr(self, '_closed', False):
            return False
        path, stamp = verified
        dialog = ShareDialogV308(path, stamp, self)
        self._exec_edit_dialog(dialog)
        dialog.deleteLater()
        return True

    def choose_share_v308(self):
        if not self.state or self.busy or self._save_transaction_v300 is not None:
            return False
        sid = self._active_session_v200
        entry = self._entry_v300(sid)
        pending = any(entry.get(key) for key in ('dirty', 'preview', 'draft_pending', 'recovered_draft'))
        destination = entry.get('last_save_path')
        if not pending:
            for candidate in (destination, entry.get('path')):
                verified = verified_share_file_v308(candidate, entry.get('document_revision'))
                if verified:
                    return self._show_share_v308(verified)
            # A clean session can outlive a moved or externally changed file.
            # Save its actual snapshot instead of handing out stale bytes.
            destination = None
        if not destination:
            destination, _ = QFileDialog.getSaveFileName(
                self, 'Guardar PDF para compartir',
                default_save_path_v300(entry['path']), 'Documento PDF (*.pdf)')
            if not destination:
                return False
        if not self._begin_save_flow_v300():
            return False
        transaction = self._save_transaction_v300

        def saved(_approved):
            if sid not in transaction['saved'] or transaction['error'] or getattr(self, '_closed', False):
                return
            state = self._session_views_v200.get(sid, {}).get('state', {})
            verified = verified_share_file_v308(destination, state.get('document_revision'))
            if verified:
                self._show_share_v308(verified)
            else:
                self._error('El archivo guardado ha cambiado o no está disponible. Vuelve a pulsar Compartir.')

        transaction['after'] = saved
        return self._start_save_entries_v300([entry], {sid: str(destination)})
