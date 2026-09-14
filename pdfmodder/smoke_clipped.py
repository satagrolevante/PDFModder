"""Aceptación congelable de campos recortados a través de MainWindow/worker.

Sólo Qt normal: no importa el motor PDF, pypdf ni QtTest en la interfaz.
"""
from __future__ import annotations

import os
from PySide6.QtCore import QTimer

from .model import mm
from .smoke import VerticalSmoke, _digest, _signature


class ClippedSmoke(VerticalSmoke):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output = self.report_path.parent / 'smoke-recortado-editado.pdf'
        self.final_output = self.report_path.parent / 'smoke-recortado-segunda-edicion.pdf'
        self.timeout.start(30000)
        try:
            for target in (self.output, self.final_output):
                self._require(target.resolve() != self.source and not (
                    target.exists() and os.path.samefile(target, self.source)),
                    'La prueba recortada no puede guardar sobre el PDF original.')
        except Exception as exc:
            QTimer.singleShot(0, lambda error=str(exc): self.fail(error))

    def _timed_out(self):
        self.finish(error=f'Tiempo límite de 30 segundos excedido en el paso {self.stage}.', terminate=True)

    def _begin_edit(self, old, new, stage):
        self._select(old)
        self.window.line_reflow_box.setChecked(False)
        self.window.width_box.setValue(mm(80.))
        self.window.start_edit()
        self._require(self.window.canvas.editor.isVisible(), 'No se abrió el editor de texto en la página.')
        self.window.canvas.editor.setPlainText(new)
        self._require(self.window.preview_step_button.isEnabled(), 'El botón Ver vista previa no está habilitado.')
        self.stage = stage
        self.window.preview_step_button.click()
        self._require(self.window.busy, 'Ver vista previa no inició el trabajo en el proceso PDF.')

    def _verify_word(self, word):
        model = self.window.model
        text = self._text(model)
        self._require(text.count(word) == 1, f'El PDF no contiene exactamente una aparición de {word}.')
        other = 'ESTRELLA' if word == 'SOL' else 'SOL'
        self._require(other not in text, f'Quedó texto anterior: {other}.')
        start = text.index(word)
        glyphs = model.glyphs[start:start + len(word)]
        self._require(all(g.reliable and g.mode == 0 and g.font == self.font and
                          abs(g.size - self.size) < .001 for g in glyphs),
                      'El campo perdió su texto real, recurso o tamaño original.')
        remaining = model.glyphs[:start] + model.glyphs[start + len(word):]
        self._require(len(remaining) == len(self.neighbours), 'Cambió la cantidad de caracteres vecinos.')
        for old, new in zip(self.neighbours, remaining):
            self._require(old.text == new.text and old.font == new.font and
                          abs(old.size - new.size) < .001 and old.color == new.color and
                          abs(old.opacity - new.opacity) < .001 and
                          all(abs(a-b) < .035 for a, b in zip(old.origin, new.origin)),
                          'La sustitución alteró el contenido, la posición o el estilo de un vecino.')

    def _advance(self, command, result):
        page = command == 'page' and result.get('model') is not None
        main = page and result['number'] == 0
        if self.stage == 'opening' and main:
            self.page_count = self.window.state['page_count']
            self._require(self.page_count == 2, 'La prueba requiere recortado.pdf con una página de control.')
            selected = self._select('SOL')
            self.font, self.size = selected[0].font, selected[0].size
            ids = {g.id for g in selected}
            self.neighbours = [g for g in self.window.model.glyphs if g.id not in ids]
            self._require('10/09/2026' in self._text(self.window.model), 'Falta la fecha de control.')
            self._step('abrir_seleccionar_campo_recortado', characters=len(selected), font=self.font, size=self.size)
            self.stage = 'control_original'
            self._request_control(True)
        elif self.stage == 'control_original' and page and result['number'] == 1:
            self.control_signature, self.control_render_hash = _signature(result['model']), _digest(result['png'])
            self._step('registrar_pagina_control', render_sha256=self.control_render_hash)
            self._begin_edit('SOL', 'ESTRELLA', 'preview_first')
        elif self.stage in ('preview_first', 'preview_second') and main:
            first = self.stage == 'preview_first'
            self._require(self.window.state['preview'] and self.window.state['history_index'] == 0,
                          'La vista previa se aplicó antes de pulsar Aplicar cambio.')
            report = self.window.last_report or {}
            self._require(report.get('verified') and report.get('operators_preserved') and
                          report.get('font_resources_unchanged') and report.get('clipped_text_mode'),
                          'Falta la validación del campo, los operadores o la fuente originales.')
            self._require(report.get('line_reflow_requested') is False and abs(report['cursor_residual']) < 1e-8,
                          'La edición no conservó el cursor o ignoró la opción elegida.')
            self.edit_reports.append(report)
            self.preview_hash, self.preview_revision = _digest(result['png']), self.window.model.revision
            self._verify_word('ESTRELLA' if first else 'SOL')
            self._step('previsualizar_campo_largo' if first else 'previsualizar_campo_corto',
                       render_sha256=self.preview_hash, neighbours_unchanged=True)
            self.stage = 'commit_first' if first else 'commit_second'
            self._require(self.window.apply_step_button.isEnabled(), 'Aplicar cambio no está habilitado.')
            self.window.apply_step_button.click()
        elif self.stage in ('commit_first', 'commit_second') and main:
            first = self.stage == 'commit_first'
            self._require(not self.window.state['preview'] and self.window.state['history_index'] == 1 and
                          _digest(result['png']) == self.preview_hash,
                          'Aplicar no conservó el render o la transacción única del historial.')
            self._verify_word('ESTRELLA' if first else 'SOL')
            self._step('aplicar_campo_largo' if first else 'aplicar_campo_corto', render_matches_preview=True)
            if first:
                self.long_hash = self.preview_hash
                self.stage = 'save_first'
                self._require(self.window.save_as(self.output), 'No se inició Guardar como.')
            else:
                self.short_revision, self.short_hash = self.preview_revision, self.preview_hash
                self.stage = 'undo'
                self.window.history('undo')
        elif self.stage == 'save_first' and command == 'save':
            self._require(self.output.is_file() and not self.window.state['dirty'], 'No se guardó la copia.')
            self._step('guardar_copia_recortada', path=str(self.output))
            self.stage = 'reopened'
            self._require(self.window.open_document(self.output), 'No se inició la reapertura.')
        elif self.stage == 'reopened' and main:
            self._verify_word('ESTRELLA')
            self._require(_digest(result['png']) == self.long_hash, 'La copia reabierta tiene otra apariencia.')
            self.long_revision = self.window.model.revision
            self._step('reabrir_texto_real_recortado', render_equal=True)
            self._begin_edit('ESTRELLA', 'SOL', 'preview_second')
        elif self.stage == 'undo' and main:
            self._verify_word('ESTRELLA')
            self._require(self.window.model.revision == self.long_revision and _digest(result['png']) == self.long_hash,
                          'Deshacer no recuperó exactamente los bytes y el render anteriores.')
            self._step('deshacer_segunda_edicion', exact_revision_and_render=True)
            self.stage = 'redo'
            self.window.history('redo')
        elif self.stage == 'redo' and main:
            self._verify_word('SOL')
            self._require(self.window.model.revision == self.short_revision and _digest(result['png']) == self.short_hash,
                          'Rehacer no recuperó exactamente la segunda edición.')
            self._step('rehacer_segunda_edicion', exact_revision_and_render=True)
            self.stage = 'save_final'
            self.output = self.final_output
            self._require(self.window.save_as(self.output), 'No se inició el guardado final.')
        elif self.stage == 'save_final' and command == 'save':
            self._step('guardar_segunda_edicion', source_unchanged=_digest(self.source.read_bytes()) == self.source_hash)
            self.stage = 'control_final'
            self._request_control(False)
        elif self.stage == 'control_final' and page and result['number'] == 1:
            self._require(_signature(result['model']) == self.control_signature and _digest(result['png']) == self.control_render_hash,
                          'La página no editada cambió de contenido, geometría o apariencia.')
            self._step('verificar_pagina_control', glyphs_geometry_pixels_equal=True)
            self.stage = 'complete'
            QTimer.singleShot(150, self.finish)
