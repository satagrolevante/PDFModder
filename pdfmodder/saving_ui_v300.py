"""Per-document destinations and serial, asynchronous Save/close workflows.

    Integration: place SavingV300Mixin before WorkspaceV200Mixin and call
    _init_saving_v300() after _init_workspace_v200().  The PDF worker continues
    to own all snapshots; the UI only sequences its existing validated edits.
"""
from copy import deepcopy
from pathlib import Path
import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHBoxLayout, QHeaderView, QToolBar)


def default_save_path_v300(source):
    source = Path(source or 'documento.pdf')
    return str(source.with_name(source.stem + '_editado.pdf'))


def same_destination_v300(first, second):
    if Path(first).resolve() == Path(second).resolve():
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


class SaveDocumentsDialogV300(QDialog):
    """Review every destination before any draft or file is modified."""
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.entries = entries
        self.setWindowTitle('Guardar documentos modificados')
        self.setObjectName('saveDocumentsDialogV300')
        self.resize(840, min(600, 230 + len(entries) * 55))
        layout = QVBoxLayout(self)
        note = QLabel('Revisa los destinos. Los borradores se validarán y aplicarán antes de guardar cada documento.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(entries), 2)
        self.table.setObjectName('saveDestinationsV300')
        self.table.setHorizontalHeaderLabels(['Documento', 'Guardar en'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.paths = {}
        for row, entry in enumerate(entries):
            item = QTableWidgetItem(Path(entry['path']).name)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setToolTip(entry['path'])
            self.table.setItem(row, 0, item)
            container = QWidget()
            controls = QHBoxLayout(container)
            controls.setContentsMargins(3, 3, 3, 3)
            field = QLineEdit(entry.get('last_save_path') or default_save_path_v300(entry['path']))
            field.setObjectName('savePathV300_' + entry['session_id'])
            browse = QPushButton('Elegir…')
            browse.clicked.connect(lambda _, edit=field: self._choose(edit))
            controls.addWidget(field, 1)
            controls.addWidget(browse)
            self.table.setCellWidget(row, 1, container)
            self.paths[entry['session_id']] = field
        layout.addWidget(self.table)
        self.error = QLabel('')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Guardar todo')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self._accept_paths)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose(self, field):
        path, _ = QFileDialog.getSaveFileName(self, 'Guardar copia PDF', field.text(), 'Documento PDF (*.pdf)')
        if path:
            field.setText(path)

    def _accept_paths(self):
        if any(not field.text().strip() for field in self.paths.values()):
            self.error.setText('Elige un destino para cada documento.')
            return
        self.accept()

    def destinations(self):
        return {sid: field.text().strip() for sid, field in self.paths.items()}


class CloseDocumentsDialogV300(QDialog):
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.choice = 'cancel'
        self.setWindowTitle('Cerrar PDF Modder')
        self.setObjectName('closeDocumentsDialogV300')
        self.resize(650, min(520, 200 + 35 * len(entries)))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Estos documentos tienen cambios o borradores pendientes:'))
        listing = QListWidget()
        for entry in entries:
            listing.addItem(Path(entry['path']).name + (' · borrador pendiente' if entry.get('draft_pending') else ''))
        layout.addWidget(listing)
        note = QLabel('Guardar valida los borradores y conserva las copias. Si un documento falla, la aplicación permanece abierta.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox()
        save = buttons.addButton('Guardar todo', QDialogButtonBox.AcceptRole)
        discard = buttons.addButton('Descartar todo', QDialogButtonBox.DestructiveRole)
        cancel = buttons.addButton('Cancelar', QDialogButtonBox.RejectRole)
        save.clicked.connect(lambda: self._choose('save'))
        discard.clicked.connect(lambda: self._choose('discard'))
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _choose(self, choice):
        self.choice = choice
        self.accept()


class SavingV300Mixin:
    def _init_saving_v300(self):
        self._save_paths_v300 = {}
        self._save_transaction_v300 = None
        self._close_waiting_v300 = False
        self.save_action.triggered.disconnect()
        self.save_action.setText('Guardar')
        self.save_action.setObjectName('saveDocumentActionV300')
        self.save_action.setShortcut(QKeySequence('Ctrl+S'))
        self.save_action.triggered.connect(self.save_document_v300)
        self.save_as_action_v300 = QAction('Guardar como…', self)
        self.save_as_action_v300.setObjectName('saveAsActionV300')
        self.save_as_action_v300.setShortcut(QKeySequence('Ctrl+Shift+S'))
        self.save_as_action_v300.triggered.connect(self.choose_save)
        self.save_all_action_v300 = QAction('Guardar todo', self)
        self.save_all_action_v300.setObjectName('saveAllActionV300')
        self.save_all_action_v300.setShortcut(QKeySequence('Ctrl+Alt+S'))
        self.save_all_action_v300.triggered.connect(lambda: self.save_all_v300())
        toolbar_actions = self.toolbar.actions()
        save_index = toolbar_actions.index(self.save_action)
        anchor = toolbar_actions[save_index + 1] if save_index + 1 < len(toolbar_actions) else None
        self.toolbar.insertAction(anchor, self.save_as_action_v300)
        self.toolbar.insertAction(anchor, self.save_all_action_v300)
        self.error_raised.connect(self._save_failed_v300)
        self.operation_finished.connect(self._save_state_changed_v300)
        self._refresh_actions()

    def _reading_command_allowed_v171(self, command):
        if command in ('save', 'apply_stored_draft_v300'):
            return True
        return super()._reading_command_allowed_v171(command)

    def _submit(self, command, payload=None, callback=None):
        if getattr(self, '_save_transaction_v300', None) is not None:
            # Timers and editor callbacks must not interleave document changes
            # with Save all. Internal submissions bypass this single gate.
            return False
        return super()._submit(command, payload, callback)

    def _saving_submit_v300(self, command, payload, callback):
        transaction = self._save_transaction_v300
        if transaction is None:
            return False
        transaction['command'] = command
        def completed(result):
            if self._save_transaction_v300 is not transaction:
                return
            self._remember_state_v300(result.get('state'))
            # Wait for _poll's operation_finished signal before changing the
            # global background flag or sending another worker operation.
            def advance():
                if self._save_transaction_v300 is not transaction:
                    return
                try:
                    callback(result)
                except Exception as exc:
                    # Qt timer callbacks have no worker future to carry an
                    # exception. Release the transaction through the same
                    # recovery path as a failed worker command.
                    self._error(str(exc))
            QTimer.singleShot(0, advance)
        try:
            accepted = super()._submit(command, payload, completed)
        except Exception as exc:
            self._error(str(exc))
            return False
        if not accepted:
            self._abort_save_v300('No se pudo iniciar la operación. El documento y su borrador permanecen abiertos.')
        return accepted

    def _remember_state_v300(self, state):
        if not state:
            return
        sid = state.get('session_id')
        if not sid:
            return
        if state.get('last_save_path'):
            self._save_paths_v300[sid] = state['last_save_path']
        self._session_views_v200.setdefault(sid, {})['state'] = deepcopy(state)
        for index in range(self.document_tabs_v200.count()):
            if self.document_tabs_v200.tabData(index) == sid:
                source = self._session_paths_v200.get(sid, state.get('path', 'Documento'))
                self.document_tabs_v200.setTabText(index, Path(source).name + (' *' if state.get('dirty') else ''))
                destination = self._save_paths_v300.get(sid)
                self.document_tabs_v200.setTabToolTip(index, source + ('\nGuardar en: ' + destination if destination else ''))

    def _save_state_changed_v300(self, command, result):
        if self._save_transaction_v300 is not None:
            for timer, _, _, _ in self._save_transaction_v300['timers']:
                timer.stop()
        if not getattr(self, '_background_ui_v200', False):
            self._remember_state_v300(result.get('state') if isinstance(result, dict) else None)

    def _refresh_actions(self):
        super()._refresh_actions()
        if not hasattr(self, 'save_all_action_v300'):
            return
        locked = self._save_transaction_v300 is not None
        prepared = self.state.get('editing_prepared', self.application_mode == 'editing')
        permitted = not self.state.get('issues') or self.state.get('metadata_only_save') or self.state.get('special_only_save')
        clean_reading = self._clean_reading_copy_v300()
        ready = (bool(self.state) and not self.busy and not locked and not getattr(self, '_cell_draw_v200', False)
                 and not getattr(self, '_mode_preparing_v171', False))
        enabled = bool(ready and ((prepared and permitted) or clean_reading) and not getattr(self, '_rich_loading', False)
                       and not getattr(self, '_signature_placement_dialog', None))
        self.save_action.setEnabled(enabled)
        self.save_as_action_v300.setEnabled(enabled)
        self.save_all_action_v300.setEnabled(bool(self._session_paths_v200) and not self.busy and not locked)
        destination = self.state.get('last_save_path') or self._save_paths_v300.get(self._active_session_v200)
        self.save_action.setToolTip('Guardar en: ' + destination if destination else 'Elegir una copia de salida y guardar · Ctrl+S')
        if locked:
            for toolbar in self.findChildren(QToolBar):
                toolbar.setEnabled(False)
            self.centralWidget().setEnabled(False)
            # Window shortcuts remain active even when their toolbar or
            # button is disabled. They must not cancel a draft mid-save.
            for action in self.findChildren(QAction):
                action.setEnabled(False)

    def _begin_save_flow_v300(self, closing=None):
        if self._save_transaction_v300 is not None or self._closed:
            return False
        if self.busy:
            self._notice('Espera a que termine la operación actual antes de guardar.')
            return False
        if getattr(self, '_rich_loading', False) or getattr(self, '_rich_accept_pending', False):
            self._notice('Espera a que termine la preparación del texto antes de guardar.')
            return False
        if getattr(self, '_signature_placement_dialog', None) is not None or getattr(self, '_cell_draw_v200', False):
            self._notice('Termina o cancela la selección del área antes de guardar.')
            return False
        self._stash_view_v200()
        timers = []
        for name in ('thumbnail_timer', 'reader_timer_v180', '_workspace_timer_v200', '_preflight_timer_v200', '_rich_timer', 'arrow_timer'):
            timer = getattr(self, name, None)
            if timer:
                timers.append((timer, timer.isActive(), timer.remainingTime(), timer.interval()))
                timer.stop()
        self._save_transaction_v300 = {'active': self._active_session_v200, 'closing': closing,
            'remaining': [], 'entries': [], 'saved': [], 'timers': timers, 'refresh': False,
            'command': None, 'restoring': False, 'aborting': False, 'error': '', 'warnings': [],
            'central_enabled': self.centralWidget().isEnabled(),
            'toolbars': [(toolbar, toolbar.isEnabled()) for toolbar in self.findChildren(QToolBar)],
            'action_enabled': [(action, action.isEnabled()) for action in self.findChildren(QAction)]}
        self._refresh_actions()
        return True

    def _entry_v300(self, sid, live=None):
        state = self.state if sid == self._active_session_v200 else self._session_views_v200.get(sid, {}).get('state', {})
        entry = dict(state)
        entry.update(live or {})
        entry['session_id'] = sid
        entry['path'] = entry.get('path') or self._session_paths_v200.get(sid, 'documento.pdf')
        entry['last_save_path'] = entry.get('last_save_path') or self._save_paths_v300.get(sid)
        entry['draft_pending'] = bool(entry.get('draft_pending') or entry.get('recovered_draft'))
        if sid == self._active_session_v200:
            entry['draft_pending'] |= bool(self.canvas.editor.isVisible() or getattr(self, '_rich_active', False)
                                          or getattr(self, '_rich_loading', False))
            entry['reading_copy_v300'] = self._clean_reading_copy_v300()
        return entry

    def _clean_reading_copy_v300(self):
        return bool(self.state and self.application_mode == 'reading'
                    and not self.state.get('dirty') and not self.state.get('preview')
                    and not self.state.get('draft_pending') and not self.state.get('recovered_draft')
                    and not self.canvas.editor.isVisible() and not getattr(self, '_rich_active', False)
                    and not getattr(self, '_rich_loading', False))

    def _collect_entries_v300(self, callback):
        def collected(result):
            entries = [self._entry_v300(row['session_id'], row) for row in result.get('sessions', [])]
            # Stable visible tab order makes partial saves understandable.
            order = [self.document_tabs_v200.tabData(i) for i in range(self.document_tabs_v200.count())]
            entries.sort(key=lambda item: order.index(item['session_id']) if item['session_id'] in order else len(order))
            callback(entries)
        return self._saving_submit_v300('list_sessions', {'_background_ui': True}, collected)

    def _choose_destinations_v300(self, entries):
        dialog = SaveDocumentsDialogV300(entries, self)
        if self._exec_edit_dialog(dialog) != QDialog.Accepted:
            return None
        return dialog.destinations()

    def _confirm_overwrites_v300(self, entries, destinations):
        replacements = []
        for entry in entries:
            path = str(destinations[entry['session_id']])
            previous = entry.get('last_save_path')
            if Path(path).is_file() and (not previous or not same_destination_v300(path, previous)):
                replacements.append(path)
        if not replacements:
            return True
        box = QMessageBox(self)
        box.setWindowTitle('Reemplazar copias existentes')
        box.setText('Se reemplazarán estos archivos:')
        box.setInformativeText('\n'.join(replacements))
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Save).setText('Reemplazar')
        box.button(QMessageBox.Cancel).setText('Cancelar')
        return self._exec_edit_dialog(box) == QMessageBox.Save

    def _validate_destinations_v300(self, entries, destinations):
        originals = list(self._session_paths_v200.values())
        seen = []
        for entry in entries:
            path = destinations.get(entry['session_id'])
            if not path or not str(path).strip():
                raise ValueError('Elige un destino para ' + Path(entry['path']).name + '.')
            path = str(path)
            if any(same_destination_v300(path, source) for source in originals):
                raise ValueError('El destino no puede sobrescribir un PDF original usado en este trabajo.')
            if any(same_destination_v300(path, previous) for previous in seen):
                raise ValueError('Cada documento debe tener un destino diferente.')
            if not Path(path).parent.is_dir():
                raise ValueError('La carpeta de destino no existe: ' + str(Path(path).parent))
            seen.append(path)

    def save_document_v300(self):
        if not self.state or self._save_transaction_v300 is not None:
            return False
        sid = self._active_session_v200
        path = self.state.get('last_save_path') or self._save_paths_v300.get(sid)
        if path:
            return self.save_as(path)
        return self.choose_save()

    def choose_save(self):
        if not self.state or self.busy or self._save_transaction_v300 is not None:
            return False
        entry = self._entry_v300(self._active_session_v200)
        suggestion = entry.get('last_save_path') or default_save_path_v300(entry['path'])
        path, _ = QFileDialog.getSaveFileName(self, 'Guardar copia PDF', suggestion, 'Documento PDF (*.pdf)')
        return self.save_as(path, overwrite_confirmed=True) if path else False

    def save_as(self, path, *, overwrite_confirmed=False):
        if not self.state or not path or not self._begin_save_flow_v300():
            return False
        entry = self._entry_v300(self._active_session_v200)
        return self._start_save_entries_v300([entry], {entry['session_id']: str(path)}, overwrite_confirmed=overwrite_confirmed)

    def save_all_v300(self, destinations=None):
        if not self._begin_save_flow_v300():
            return False
        def collected(entries):
            pending = [entry for entry in entries if entry.get('dirty') or entry.get('preview') or entry.get('draft_pending')]
            if not pending:
                self._finish_save_flow_v300('Todos los documentos están guardados.')
                return
            chosen = destinations if destinations is not None else self._choose_destinations_v300(pending)
            if chosen is None:
                self._finish_save_flow_v300('Guardado cancelado. Los documentos y borradores se conservan.')
                return
            self._start_save_entries_v300(pending, chosen)
        return self._collect_entries_v300(collected)

    def _start_save_entries_v300(self, entries, destinations, *, overwrite_confirmed=False):
        try:
            self._validate_destinations_v300(entries, destinations)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return False
        if not overwrite_confirmed and not self._confirm_overwrites_v300(entries, destinations):
            self._finish_save_flow_v300('Guardado cancelado. Los documentos y borradores se conservan.')
            return False
        transaction = self._save_transaction_v300
        transaction['entries'] = list(entries)
        transaction['remaining'] = [dict(entry, destination=str(destinations[entry['session_id']])) for entry in entries]
        try:
            self._next_save_v300()
        except Exception as exc:
            self._error(str(exc))
            return False
        return True

    def _next_save_v300(self):
        transaction = self._save_transaction_v300
        if transaction is None:
            return
        if not transaction['remaining']:
            if transaction['closing']:
                self._perform_close_v300()
            else:
                count = len(transaction['saved'])
                self._restore_save_session_v300(f'{count} documento(s) guardado(s).')
            return
        entry = transaction['remaining'][0]
        sid = entry['session_id']
        active = sid == self._active_session_v200
        if active and (self.canvas.editor.isVisible() or getattr(self, '_rich_active', False)):
            self._apply_active_draft_v300(entry)
        elif entry.get('draft_pending'):
            self._saving_submit_v300('apply_stored_draft_v300', {'session_id': sid, '_background_ui': not active},
                lambda result: self._draft_applied_v300(entry, result))
        elif entry.get('preview'):
            self._saving_submit_v300('commit', {'session_id': sid, '_background_ui': not active},
                lambda result: self._draft_applied_v300(entry, result))
        else:
            self._write_entry_v300(entry)

    def _apply_active_draft_v300(self, entry):
        context = getattr(self, '_editing_context', None)
        if context and (not self.model or context != (self.page_number, self.model.revision, tuple(self.canvas.ids))):
            self._error('La selección cambió durante la escritura. El borrador se conserva para revisarlo.')
            return
        if getattr(self, '_rich_active', False):
            payload = deepcopy(self.canvas.editor.payload())
            self._rich_pending = None
            self._rich_timer.stop()
            self._rich_accept_pending = True
            self.canvas.editor.set_accepting(True)
            def prepared(result):
                self._saving_submit_v300('rich_commit', {'token': result['token'], 'session_id': entry['session_id']},
                    lambda value: self._draft_applied_v300(entry, value, rich=True))
            self._saving_submit_v300('rich_prepare', {'request': payload, 'zoom': self.zoom, 'session_id': entry['session_id']}, prepared)
        else:
            try:
                request = self._request(text=self.canvas.editor.toPlainText(), formatting=True, adjust_line=True)
            except ValueError as exc:
                self._error(str(exc))
                return
            self.canvas.editor.setReadOnly(True)
            def prepared(result):
                self._saving_submit_v300('commit', {'session_id': entry['session_id']},
                    lambda value: self._draft_applied_v300(entry, value, legacy=True))
            self._saving_submit_v300('preview', {'request': request, 'session_id': entry['session_id']}, prepared)

    def _draft_applied_v300(self, entry, result, rich=False, legacy=False):
        entry['draft_pending'] = entry['preview'] = False
        if entry['session_id'] == self._active_session_v200:
            if rich:
                self._end_rich()
            elif legacy:
                self.canvas.editor.hide()
                self.canvas.editor.setReadOnly(False)
                self._editing_context = None
            self.last_report = result.get('report')
            self._save_transaction_v300['refresh'] = True
        self._write_entry_v300(entry)

    def _write_entry_v300(self, entry):
        sid = entry['session_id']
        def saved(result):
            destination = result.get('path', entry['destination'])
            self._save_paths_v300[sid] = destination
            state = dict(result.get('state', {}), last_save_path=destination)
            self._remember_state_v300(state)
            if sid == self._active_session_v200:
                self.state['last_save_path'] = destination
            transaction = self._save_transaction_v300
            if result.get('notice'):
                transaction['warnings'].append(Path(entry['path']).name + ': ' + result['notice'])
            transaction['saved'].append(sid)
            transaction['remaining'].pop(0)
            self._next_save_v300()
        self.statusBar().showMessage('Guardando ' + Path(entry['path']).name + '…')
        self._saving_submit_v300('save', {'path': entry['destination'], 'session_id': sid,
            'reading_copy': bool(entry.get('reading_copy_v300')),
            '_background_ui': sid != self._active_session_v200}, saved)

    def _save_failed_v300(self, message):
        if self._save_transaction_v300 is not None:
            self._abort_save_v300(message)

    def _abort_save_v300(self, message):
        transaction = self._save_transaction_v300
        if transaction is None:
            return
        if transaction['restoring']:
            detail = transaction.get('error', '')
            transaction['error'] = (detail + ' ' if detail else '') + 'No se pudo restaurar la sesión: ' + str(message)
            self._finish_save_flow_v300(transaction['error'])
            return
        if transaction['aborting']:
            return
        transaction['aborting'] = True
        transaction['error'] = str(message)
        self._rich_accept_pending = False
        if self.canvas.editor.isVisible() or getattr(self, '_rich_active', False):
            self.canvas.editor.setReadOnly(False)
            if getattr(self, '_rich_active', False):
                self.canvas.editor.set_accepting(False)
        done = len(transaction['saved'])
        pending = len(transaction['remaining'])
        detail = (f'Guardados: {done}. Pendientes: {pending}. ' if done or pending else '') + str(message)
        QTimer.singleShot(0, lambda: self._restore_save_session_v300(detail))

    def _restore_save_session_v300(self, notice):
        transaction = self._save_transaction_v300
        if transaction is None:
            return
        transaction['restoring'] = True
        sid = transaction['active']
        if sid and sid in self._session_paths_v200:
            self._saving_submit_v300('activate_session', {'session_id': sid, '_background_ui': True},
                lambda _: self._finish_save_flow_v300(notice))
        else:
            self._finish_save_flow_v300(notice)

    def _finish_save_flow_v300(self, notice=''):
        transaction, self._save_transaction_v300 = self._save_transaction_v300, None
        if transaction is None:
            return
        for toolbar, was_enabled in transaction['toolbars']:
            toolbar.setEnabled(was_enabled)
        self.centralWidget().setEnabled(transaction['central_enabled'])
        for action, was_enabled in transaction['action_enabled']:
            action.setEnabled(was_enabled)
        for timer, was_active, remaining, interval in transaction['timers']:
            if was_active and not self._closed:
                timer.start(max(50, remaining) if timer.isSingleShot() else interval)
        if notice:
            if transaction['warnings']:
                notice += '\n' + '\n'.join(transaction['warnings'])
            self._notice(notice)
            self.statusBar().showMessage(notice)
        self._refresh_actions()
        if transaction['refresh'] and self.state and not self.canvas.editor.isVisible():
            self.load_page()
        if transaction['error']:
            self.last_error = transaction['error']
        after = transaction.get('after')
        if after is not None:
            approved = bool(transaction.get('close_approved') and not transaction['error'])
            QTimer.singleShot(0, lambda: after(approved))

    def _ask_close_v300(self, entries, app=False):
        if not entries:
            return 'discard'
        if app and len(entries) > 1:
            dialog = CloseDocumentsDialogV300(entries, self)
            return dialog.choice if self._exec_edit_dialog(dialog) == QDialog.Accepted else 'cancel'
        entry = entries[0]
        box = QMessageBox(self)
        box.setWindowTitle('Cerrar documento' if not app else 'Cerrar PDF Modder')
        box.setText('Guardar los cambios de ' + Path(entry['path']).name + ' antes de cerrar?')
        box.setInformativeText('El borrador se validará antes de guardar.' if entry.get('draft_pending') else 'Hay cambios sin guardar.')
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        box.button(QMessageBox.Save).setText('Guardar')
        box.button(QMessageBox.Discard).setText('Descartar')
        box.button(QMessageBox.Cancel).setText('Cancelar')
        answer = self._exec_edit_dialog(box)
        return {QMessageBox.Save: 'save', QMessageBox.Discard: 'discard'}.get(answer, 'cancel')

    def _request_close_v300(self, closing, *, after=None):
        if not self._begin_save_flow_v300(closing):
            if after is not None:
                QTimer.singleShot(0, lambda: after(False))
            return False
        self._save_transaction_v300['after'] = after
        def collected(entries):
            all_documents = closing in ('app', 'update')
            relevant = entries if all_documents else [entry for entry in entries if entry['session_id'] == closing]
            pending = [entry for entry in relevant if entry.get('dirty') or entry.get('preview') or entry.get('draft_pending')]
            answer = self._ask_close_v300(pending, app=all_documents)
            if answer == 'cancel':
                self._finish_save_flow_v300('Cierre cancelado. Los documentos y borradores se conservan.')
            elif answer == 'discard' or not pending:
                self._perform_close_v300()
            else:
                # Keep the remembered destination; choose all missing ones in
                # one reviewable dialog before applying the first draft.
                destinations = {entry['session_id']: entry['last_save_path'] for entry in pending if entry.get('last_save_path')}
                if len(destinations) != len(pending):
                    destinations = self._choose_destinations_v300(pending)
                if destinations is None:
                    self._finish_save_flow_v300('Cierre cancelado. Los documentos y borradores se conservan.')
                else:
                    self._start_save_entries_v300(pending, destinations)
        return self._collect_entries_v300(collected)

    def _perform_close_v300(self):
        transaction = self._save_transaction_v300
        closing = transaction['closing']
        if closing == 'update':
            # Keep the sessions and drafts available until the updater has
            # verified the installer and successfully started its handoff.
            transaction['close_approved'] = True
            self._restore_save_session_v300('Documentos preparados para actualizar.')
            return
        if closing == 'app':
            def closed(_):
                self._session_paths_v200.clear()
                self._session_views_v200.clear()
                self._active_session_v200 = None
                self.state = {}
                transaction['refresh'] = False
                self._finish_save_flow_v300()
                self._allow_close = True
                self.close()
            self._saving_submit_v300('close_all', {'_background_ui': True}, closed)
            return
        sid = closing
        def closed(_):
            bar = self.document_tabs_v200
            bar.blockSignals(True)
            for index in range(bar.count()):
                if bar.tabData(index) == sid:
                    bar.removeTab(index)
                    break
            bar.blockSignals(False)
            self._session_paths_v200.pop(sid, None)
            self._session_views_v200.pop(sid, None)
            self._save_paths_v300.pop(sid, None)
            if sid == self._active_session_v200:
                transaction['active'] = None
                transaction['refresh'] = False
                self._active_session_v200 = None
                self.state = {}
                self._reset_view_v200()
                self.pages.clear()
                self._finish_save_flow_v300()
                if bar.count():
                    self._switch_tab_v200(bar.currentIndex())
            else:
                self._restore_save_session_v300('Documento cerrado.')
        self._saving_submit_v300('close_session', {'session_id': sid, '_background_ui': True}, closed)

    def _close_tab_v200(self, index):
        if index < 0 or index >= self.document_tabs_v200.count() or self._save_transaction_v300 is not None:
            return False
        if self.busy:
            self._notice('Espera a que termine la operación actual antes de cerrar la pestaña.')
            return False
        return self._request_close_v300(self.document_tabs_v200.tabData(index))

    def _load_visible_thumbnail(self):
        if getattr(self, '_close_waiting_v300', False) or getattr(self, '_save_transaction_v300', None) is not None:
            return
        return super()._load_visible_thumbnail()

    def _pump_reader_v180(self):
        if getattr(self, '_close_waiting_v300', False) or getattr(self, '_save_transaction_v300', None) is not None:
            return
        return super()._pump_reader_v180()

    def closeEvent(self, event):
        if self._allow_close or self._closed:
            return super().closeEvent(event)
        event.ignore()
        if self._save_transaction_v300 is not None or self._close_waiting_v300:
            return
        if self.busy:
            self._close_waiting_v300 = True
            def idle():
                if self._closed:
                    return
                if self.busy or getattr(self, '_rich_accept_pending', False) or getattr(self, '_rich_loading', False):
                    QTimer.singleShot(50, idle)
                    return
                self._close_waiting_v300 = False
                self._request_close_v300('app')
            QTimer.singleShot(50, idle)
        else:
            self._request_close_v300('app')
