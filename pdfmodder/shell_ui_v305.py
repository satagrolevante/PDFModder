"""Qt entry points for Explorer actions; conversion stays in the PDF worker."""
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QProgressDialog, QPushButton, QVBoxLayout,
)

from .draft_control_v305 import DraftControl
from .editing_ui import MergeDialog


class ConversionResultsDialog(QDialog):
    """Keep batch results available without opening every converted document."""

    open_requested = Signal(str)

    def __init__(self, results, errors, cancelled=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Conversión a PDF')
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        summary = f'PDF creados: {len(results)}.'
        if cancelled:
            summary += ' Conversión cancelada; se conservan los PDF ya creados.'
        if errors:
            summary += f' Archivos sin convertir: {len(errors)}.'
        label = QLabel(summary)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.files = QListWidget()
        self.files.setObjectName('officeConvertedFiles')
        for result in results:
            path = str(result['path'])
            item = QListWidgetItem(path)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.files.addItem(item)
        layout.addWidget(self.files)
        if errors:
            details = QPlainTextEdit()
            details.setObjectName('officeConversionErrors')
            details.setReadOnly(True)
            details.setPlainText(_conversion_errors(errors))
            layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('Cerrar')
        self.open_button = QPushButton('Abrir seleccionado')
        self.open_button.setObjectName('officeOpenResult')
        buttons.addButton(self.open_button, QDialogButtonBox.ActionRole)
        self.open_button.clicked.connect(self._open_selected)
        self.files.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.files.currentRowChanged.connect(lambda row: self.open_button.setEnabled(row >= 0))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.open_button.setEnabled(bool(results))
        if results:
            self.files.setCurrentRow(0)

    def _open_selected(self):
        item = self.files.currentItem()
        if item is not None:
            self.open_requested.emit(item.data(Qt.UserRole))


def _conversion_errors(errors):
    return '\n\n'.join(
        f"{error.get('source', '')}\n{error.get('error', 'No se pudo convertir el archivo.')}".strip()
        for error in errors
    )


class ShellActionsUiMixin:
    def start_shell_action_v305(self, action, paths, *, destination_dir=None):
        """Run one explicit shell request after the main window is ready."""
        if getattr(self, '_closed', False):
            return False
        if self.busy or getattr(self, '_office_conversion_v305', None) is not None:
            self._notice('Espera a que termine la operación actual.')
            return False
        if action not in ('convert', 'combine'):
            self._error('La acción del menú contextual no es válida.')
            return False
        try:
            selected = self._shell_paths_v305(paths, action)
        except (OSError, ValueError, TypeError) as exc:
            self._error(str(exc))
            return False
        if action == 'combine':
            dialog = MergeDialog(self, has_document=False)
            dialog.files.addItems(selected)
            dialog.files.setCurrentRow(0)
            accepted = self._exec_edit_dialog(dialog) == QDialog.Accepted
            if accepted:
                self.combine_pdfs(dialog.paths())
            dialog.deleteLater()
            return accepted
        return self._start_office_conversion_v305(selected, destination_dir)

    @staticmethod
    def _shell_paths_v305(paths, action):
        if isinstance(paths, (str, bytes)) or not paths:
            raise ValueError('Selecciona los archivos que quieres procesar.')
        if len(paths) > 2000:
            raise ValueError('Selecciona como máximo 2000 archivos cada vez.')
        extensions = {'.pdf'} if action == 'combine' else {'.doc', '.docx'}
        selected, seen = [], set()
        for value in paths:
            path = Path(value).expanduser().resolve()
            if path.suffix.lower() not in extensions:
                if action == 'combine':
                    raise ValueError('Combinar archivos PDF admite archivos PDF. Convierte antes los DOC o DOCX a PDF.')
                raise ValueError('Convertir a PDF admite archivos DOC y DOCX.')
            if not path.is_file():
                raise ValueError(f'No se encuentra el archivo: {path}')
            key = os.path.normcase(str(path))
            if key not in seen:
                selected.append(str(path))
                seen.add(key)
        if not selected:
            raise ValueError('Selecciona los archivos que quieres procesar.')
        return selected

    def _start_office_conversion_v305(self, paths, destination_dir):
        channel = DraftControl()
        label = (f'Convirtiendo {Path(paths[0]).name}…' if len(paths) == 1
                 else f'Convirtiendo {len(paths)} documentos a PDF…')
        label += '\nLos PDF se guardan junto al original sin sobrescribir archivos existentes.'
        if destination_dir is not None:
            label = label.split('\n', 1)[0] + f'\nCarpeta de destino: {destination_dir}'
        progress = QProgressDialog(label, 'Cancelar', 0, 0, self)
        progress_label = QLabel(label)
        progress_label.setTextFormat(Qt.PlainText)
        progress_label.setWordWrap(True)
        progress.setLabel(progress_label)
        progress.setObjectName('officeConversionProgress')
        progress.setWindowTitle('Convertir a PDF')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        job = {'channel': channel, 'progress': progress, 'cancelled': False}
        self._office_conversion_v305 = job

        def cancel():
            if getattr(self, '_office_conversion_v305', None) is job:
                channel.invalidate()
                job['cancelled'] = True
                self._notice('Cancelando la conversión… Los PDF ya creados se conservan.')

        def failed(_message):
            if (getattr(self, '_office_conversion_v305', None) is job
                    and getattr(self, '_command', None) == 'convert_office'):
                self._finish_office_conversion_v305(job)

        job['failed'] = failed
        progress.canceled.connect(cancel)
        self.error_raised.connect(failed)
        payload = {'paths': paths, '_office_ticket': channel.ticket()}
        if destination_dir is not None:
            payload['destination_dir'] = str(destination_dir)

        def completed(result):
            if getattr(self, '_office_conversion_v305', None) is not job:
                return
            self._finish_office_conversion_v305(job)
            if getattr(self, '_closed', False):
                return
            results = result.get('results', [])
            errors = result.get('errors', [])
            cancelled = bool(result.get('cancelled') or job['cancelled'])
            if getattr(self, '_close_waiting_v300', False):
                self._notice(f'Conversión detenida para cerrar. PDF creados y conservados: {len(results)}.')
                return
            if len(results) == 1 and not errors and not cancelled:
                path = str(results[0]['path'])
                self._notice(f'PDF creado: {path}')
                self.open_document(path)
            elif results:
                self._show_office_results_v305(results, errors, cancelled)
            elif errors:
                if len(errors) > 1:
                    self._show_office_results_v305(results, errors, cancelled)
                else:
                    self._error(_conversion_errors(errors))
            elif cancelled:
                self._notice('Conversión cancelada. No se ha creado ningún PDF.')
            else:
                self._error('No se ha generado ningún PDF.')

        try:
            submitted = self._submit('convert_office', payload, completed)
        except Exception as exc:
            self._finish_office_conversion_v305(job)
            self._error(str(exc))
            return False
        if not submitted:
            self._finish_office_conversion_v305(job)
            self._notice('No se pudo iniciar la conversión. Espera a que termine la operación actual.')
            return False
        progress.show()
        return True

    def _finish_office_conversion_v305(self, job):
        if getattr(self, '_office_conversion_v305', None) is job:
            self._office_conversion_v305 = None
        self.error_raised.disconnect(job['failed'])
        job['channel'].close()
        job['progress'].close()
        job['progress'].deleteLater()

    def _show_office_results_v305(self, results, errors, cancelled):
        previous = getattr(self, '_office_results_v305', None)
        if previous is not None:
            previous.close()
            previous.deleteLater()
        dialog = ConversionResultsDialog(results, errors, cancelled, self)
        dialog.open_requested.connect(self._open_office_result_v305)
        self._office_results_v305 = dialog
        dialog.show()
        status = 'Conversión cancelada.' if cancelled else 'Conversión terminada.'
        self._notice(f'{status} PDF creados: {len(results)}. Archivos sin convertir: {len(errors)}.')

    def _open_office_result_v305(self, path):
        if self.busy:
            self._notice('Espera a que termine la operación actual para abrir otro PDF.')
        else:
            self.open_document(path)

    def close_shell_actions_v305(self):
        """Cancel Office work before the window shuts down its worker pool."""
        job = getattr(self, '_office_conversion_v305', None)
        if job is not None:
            self._finish_office_conversion_v305(job)
        dialog = getattr(self, '_office_results_v305', None)
        if dialog is not None:
            self._office_results_v305 = None
            dialog.close()
            dialog.deleteLater()
