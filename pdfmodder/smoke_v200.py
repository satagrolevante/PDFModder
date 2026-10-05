"""Frozen-capable workspace acceptance through the actual GUI/PDF process.

Two legal corpus copies are created beside the report. No PDF engine enters
the GUI process; normal buttons, tab actions and worker replies drive the flow.
"""
from io import BytesIO
from pathlib import Path
import shutil

from pypdf import PdfReader
from PySide6.QtCore import QTimer

from .smoke import VerticalSmoke, _digest


class SmokeV200(VerticalSmoke):
    def __init__(self,window,source,report_path):
        target=Path(report_path).resolve()
        target.parent.mkdir(parents=True,exist_ok=True)
        corpus=Path(source).resolve()
        first=target.parent/(target.stem+'-documento-1.pdf')
        self.second=target.parent/(target.stem+'-documento-2.pdf')
        if corpus in (first,self.second):
            raise ValueError('El corpus debe ser distinto de las réplicas de prueba.')
        shutil.copyfile(corpus,first);shutil.copyfile(corpus,self.second)
        self.second_hash=_digest(self.second.read_bytes())
        super().__init__(window,first,target)
        self.output=target.parent/(target.stem+'-guardado.pdf')
        self.stage='bootstrap';self.initial_render=None;self.accepted_render=None
        self.first_session=None;self.second_session=None
        # A smoke run must never offer recovery of the user's unrelated work.
        window._offer_recovery_v200=lambda:None
        window._workspace_timer_v200.stop()
        self.tick=QTimer(self);self.tick.setInterval(50);self.tick.timeout.connect(self._tick)
        self.tick.start();self.timeout.setInterval(90000);self.timeout.start()

    def _advance(self,command,result):
        # Poll the visible/committed state after asynchronous callbacks have
        # finished. Merely receiving a worker result is not acceptance evidence.
        pass

    def _idle(self):
        w=self.window
        return (not w.busy and not w._rich_loading and w._rich_pending is None
                and not w._rich_timer.isActive() and w._pending_text_preview is None)

    def _tick(self):
        if self.finished or not self._idle():return
        try:self._next()
        except Exception as exc:self.fail(str(exc))

    def _next(self):
        w=self.window
        if self.stage=='bootstrap':
            if w.document_tabs_v200.count():
                self._require(not w.state.get('dirty') and not w.state.get('preview'),
                              'La prueba exige una ventana nueva sin cambios previos.')
                w._close_tab_v200(0);return
            self.stage='first_open';self._require(w.open_document(self.source),'No se abrió la réplica 1.');return
        if self.stage=='first_open':
            if not w.model or not w.reader.has_page(0):return
            self._require(w.application_mode=='reading' and w.document_tabs_v200.count()==1,
                          'La primera pestaña no se abrió en lectura.')
            self.page_count=w.state['page_count'];self.first_session=w.state['session_id']
            self._step('abrir_replica_en_lectura',session_id=self.first_session)
            self.stage='prepare_first';w.tools_action.setChecked(True);return
        if self.stage=='prepare_first':
            if w.application_mode!='editing' or not w.model:return
            chosen=self._select('10/09/2026')
            self.original_origin=chosen[0].origin;self.original_font=chosen[0].font;self.original_size=chosen[0].size
            self.initial_render=_digest(w._page_png)
            self.stage='preflight';return
        if self.stage=='preflight':
            if w._preflight_result_v200 is None:return
            result=w._preflight_result_v200
            self._require(result['status']=='available','El texto digital compatible no supera la comprobación previa.')
            self._require('Editable' in w.capability_label_v200.text(),'No se muestra la compatibilidad en la interfaz.')
            self._step('preflight_visible',status=result['status'],font_certainty=result['fonts'][0]['certainty'])
            w.canvas.start_editor('10/09/2026')
            self._require(w.canvas.editor.isVisible() and not w.canvas.editor.rich_mode,'No se abrió el editor legado.')
            self._require(not w.canvas.editor.textCursor().hasSelection(),'Se seleccionó todo el texto al entrar.')
            w.canvas.editor.setPlainText('11/09/2026')
            self.stage='accepted';w.canvas.editor.toolbar.accept.click();return
        if self.stage=='accepted':
            if not w.model or w.model.revision!=w.state.get('document_revision') or '11/09/2026' not in self._text(w.model):return
            self._require(w.state['history_index']==1 and not w.state['preview'],'Aceptar no produjo una operación única.')
            self._require(not w.canvas.editor.isVisible(),'Aceptar dejó abierto el editor.')
            self._assert_date(moved=False);self.accepted_render=_digest(w._page_png)
            self.edit_reports.append(w.last_report)
            self._step('aceptar_una_accion',history_index=1,preview_pending=False)
            self.stage='second_open';self._require(w.open_document(self.second),'No se abrió la segunda pestaña.');return
        if self.stage=='second_open':
            if not w.model or not w.reader.has_page(0) or Path(w.state.get('path',''))!=self.second:return
            self._require(w.document_tabs_v200.count()==2,'No hay dos pestañas independientes.')
            self._require(w.state['history_index']==0 and '10/09/2026' in self._text(w.model),
                          'La segunda pestaña heredó cambios de la primera.')
            self.second_session=w.state['session_id']
            self._require(self.second_session!=self.first_session,'Las pestañas comparten sesión.')
            self._step('segunda_pestana_independiente',session_id=self.second_session)
            self.stage='prepare_second';w.tools_action.setChecked(True);return
        if self.stage=='prepare_second':
            if w.application_mode!='editing' or not w.model:return
            self._select('10/09/2026');self.stage='cancel_second';return
        if self.stage=='cancel_second':
            if w._preflight_result_v200 is None:return
            before=w.state['document_revision']
            w.canvas.start_editor('10/09/2026');w.canvas.editor.setPlainText('CANCELADO')
            w.canvas.editor.toolbar.cancel.click()
            self._require(not w.canvas.editor.isVisible() and w.state['history_index']==0
                          and w.state['document_revision']==before and not w.state['dirty'],
                          'Cancelar alteró el segundo documento.')
            self._require('CANCELADO' not in self._text(w.model),'El borrador cancelado llegó al PDF.')
            self._step('cancelar_sin_modificar_segunda_pestana',history_index=0)
            self.stage='back_first';w.document_tabs_v200.setCurrentIndex(0);return
        if self.stage=='back_first':
            if not w.model or w.state.get('session_id')!=self.first_session or w.model.revision!=w.state.get('document_revision'):return
            self._require('11/09/2026' in self._text(w.model) and w.state['history_index']==1 and w.state['dirty'],
                          'Volver a la primera pestaña perdió el cambio o su historial.')
            self._require(_digest(w._page_png)==self.accepted_render,'Cambiar de pestaña alteró la apariencia.')
            self._step('volver_conserva_cambios_y_render',history_index=1)
            self.stage='undo';w.history('undo');return
        if self.stage=='undo':
            if not w.model or w.model.revision!=w.state.get('document_revision') or '10/09/2026' not in self._text(w.model):return
            self._require(w.state['history_index']==0 and _digest(w._page_png)==self.initial_render,
                          'Deshacer no restauró exactamente texto y apariencia.')
            self._step('deshacer_exacto',history_index=0)
            self.stage='redo';w.history('redo');return
        if self.stage=='redo':
            if not w.model or w.model.revision!=w.state.get('document_revision') or '11/09/2026' not in self._text(w.model):return
            self._require(w.state['history_index']==1 and _digest(w._page_png)==self.accepted_render,
                          'Rehacer no recuperó la edición exacta.')
            self._step('rehacer_exacto',history_index=1)
            self.stage='save';self._require(w.save_as(self.output),'No se inició guardar copia.');return
        if self.stage=='save':
            if not self.output.is_file() or w.state['dirty']:return
            independent=PdfReader(BytesIO(self.output.read_bytes()))
            self._require('11/09/2026' in independent.pages[0].extract_text(),'El PDF guardado no contiene el cambio real.')
            self._require('10/09/2026' in independent.pages[1].extract_text(),'Se cambió otra aparición legítima de la fecha.')
            self._require(_digest(self.second.read_bytes())==self.second_hash,'Se modificó la segunda réplica de origen.')
            self._step('guardar_y_extraer_independientemente',other_page_original_date_retained=True,
                       source_copies_unchanged=True,output_sha256=_digest(self.output.read_bytes()))
            self.stage='complete';self.finish()

    def finish(self,error=None,terminate=False):
        if hasattr(self,'tick'):self.tick.stop()
        if error:
            w=self.window
            details={'busy':w.busy,'command':getattr(w,'_command',None),'rich_loading':w._rich_loading,
                'rich_pending':w._rich_pending is not None,'rich_timer':w._rich_timer.isActive(),
                'reader_pages':w.reader.loaded_page_numbers(),'reader_page0':w.reader.has_page(0),
                'model':bool(w.model),'mode':w.application_mode,'path':w.state.get('path'),
                'reader_queue':w._reader_queue_v180,'page_number':w.page_number}
            error=str(error)+'; diagnóstico='+str(details)
        if not error and hasattr(self,'second') and self.second.exists() and _digest(self.second.read_bytes())!=self.second_hash:
            error='La prueba alteró la réplica 2 de origen.'
        super().finish(error,terminate)
