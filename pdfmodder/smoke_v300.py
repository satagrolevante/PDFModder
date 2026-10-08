"""Acceptance of the 3.0.0 GUI, worker and packaged typography extensions.

The PDFs are legal corpus copies created beside the report. The PDF engines
remain in the application's worker. Source/frozen Qt evidence is recorded
separately from native Windows desktop evidence by the common smoke reporter.
"""
from pathlib import Path
import sys
from uuid import uuid4

from pypdf import PdfReader

from .selection_v300 import selection_index
from .smoke import _digest
from .smoke_v200 import SmokeV200


class SmokeV300(SmokeV200):
    def _text(self,model):
        if model.logical_text_runs:
            return model.text([glyph.id for glyph in model.glyphs])
        return super()._text(model)

    def __init__(self, window, source, report_path):
        self._v300_started = False
        self._v300_opening_checked = False
        self._v300_selection_checked = False
        self._v300_capability_checked = False
        self._v300_graph = None
        self._v300_typography = None
        super().__init__(window, source, report_path)
        self.output=self.output.with_name(self.output.stem+'-'+uuid4().hex[:8]+self.output.suffix)
        self.second_output = self.output.with_name(self.output.stem + "-documento-2.pdf")
        self.timeout.setInterval(150000)
        self.timeout.start()

    def _idle(self):
        return super()._idle() and getattr(self.window, "_save_transaction_v300", None) is None

    def _advance(self, command, result):
        if command == "reading_info" and not self._v300_opening_checked:
            self._require("geometries" in result and "page_geometries" not in result,
                          "La lectura inicial no utiliza geometrías progresivas.")
            self._require(result["geometry_ready_count"] <= 1,
                          "La apertura analizó geometrías ajenas a la primera página.")
            self._step("apertura_progresiva_v300", measured_pages=result["geometry_ready_count"],
                       total_pages=result["page_count"], complete=result["geometry_complete"],
                       first_render_prioritized=True)
            self._v300_opening_checked = True

    def _edit_date(self, old, new):
        w = self.window
        self._select(old)
        w.canvas.start_editor(old)
        self._require(w.canvas.editor.isVisible(), "No se abrió el editor de texto para la prueba.")
        w.canvas.editor.setPlainText(new)
        w.canvas.editor.toolbar.accept.click()

    def _date_ready(self, text):
        w = self.window
        return bool(w.model and w.model.revision == w.state.get("document_revision")
                    and text in self._text(w.model) and not w.canvas.editor.isVisible())

    def _tab_ready(self, sid):
        w = self.window
        return bool(w.model and w.state.get("session_id") == sid
                    and w.model.revision == w.state.get("document_revision"))

    def _next(self):
        w = self.window
        if not self._v300_started:
            if self.stage == "preflight" and not self._v300_selection_checked:
                chosen = self._select("10/09/2026")
                index = selection_index(w.model)
                word = index.group(chosen[0], "word")
                line = index.group(chosen[0], "line")
                paragraph = index.group(chosen[0], "paragraph")
                self._require(set(word).issubset(line) and set(line).issubset(paragraph),
                              "Los alcances de selección no conservan la inclusión geométrica.")
                old_mode = w.mode_box.currentIndex()
                w.mode_box.setCurrentIndex(w.mode_box.findData("paragraph"))
                self._require(w.mode_box.currentData() == "paragraph" and set(w.canvas.ids) == set(paragraph),
                              "El alcance de párrafo no se puede elegir desde la interfaz.")
                self._require(hasattr(w, "draft_area_button_v300") and hasattr(w, "draft_size_button_v300"),
                              "Faltan las opciones explícitas de área y tamaño del borrador.")
                w.mode_box.setCurrentIndex(old_mode)
                self._select("10/09/2026")
                self._step("seleccion_por_alcance_v300", word_glyphs=len(word), line_glyphs=len(line),
                           paragraph_glyphs=len(paragraph), date_selection_retained=True)
                self._v300_selection_checked = True
            if self.stage == "preflight" and w._preflight_result_v200 is not None and not self._v300_capability_checked:
                result = w._preflight_result_v200
                self._require(result["status"] == "available", "El texto compatible está bloqueado.")
                self._step("compatibilidad_por_operacion_v300", status=result["status"],
                           visible_label=w.capability_label_v200.text())
                self._v300_capability_checked = True
            return super()._next()

        if self.stage == "v300_second_activate":
            if not self._tab_ready(self.second_session):
                return
            if w.application_mode != "editing":
                w.tools_action.setChecked(True)
                return
            self._edit_date("10/09/2026", "12/09/2026")
            self.stage = "v300_second_edited"
            return
        if self.stage == "v300_second_edited":
            if not self._date_ready("12/09/2026"):
                return
            self._require(w.state["dirty"], "La segunda pestaña no conserva su cambio.")
            w.document_tabs_v200.setCurrentIndex(0)
            self.stage = "v300_first_activate"
            return
        if self.stage == "v300_first_activate":
            if not self._tab_ready(self.first_session):
                return
            self._edit_date("11/09/2026", "13/09/2026")
            self.stage = "v300_first_edited"
            return
        if self.stage == "v300_first_edited":
            if not self._date_ready("13/09/2026"):
                return
            self._require(w.state["dirty"], "La primera pestaña no conserva su cambio.")
            destinations = {self.first_session: str(self.output), self.second_session: str(self.second_output)}
            self._require(w.save_all_v300(destinations), "No se inició Guardar todo.")
            self.stage = "v300_all_saved"
            return
        if self.stage == "v300_all_saved":
            if not self.output.exists() or not self.second_output.exists() or not self._tab_ready(self.first_session):
                return
            self._require(not w.state["dirty"], "Guardar todo dejó cambios pendientes en la pestaña activa.")
            first = PdfReader(self.output)
            second = PdfReader(self.second_output)
            self._require("13/09/2026" in first.pages[0].extract_text()
                          and "12/09/2026" in second.pages[0].extract_text(),
                          "Guardar todo mezcló o perdió los cambios de las pestañas.")
            self._require("10/09/2026" in first.pages[1].extract_text()
                          and "10/09/2026" in second.pages[1].extract_text(),
                          "Guardar todo alteró las páginas de control.")
            self._step("guardar_todo_v300", documents=2, independently_extracted=True,
                       second_output=str(self.second_output), second_sha256=_digest(self.second_output.read_bytes()))
            self._edit_date("13/09/2026", "14/09/2026")
            self.stage = "v300_direct_ready"
            return
        if self.stage == "v300_direct_ready":
            if not self._date_ready("14/09/2026"):
                return
            self._require(w.state.get("last_save_path") == str(self.output), "No se recuerda el destino de esta pestaña.")
            self._require(w.save_action.shortcut().toString() == "Ctrl+S", "Guardar no tiene Ctrl+S.")
            w.save_action.trigger()
            self.stage = "v300_direct_saved"
            return
        if self.stage == "v300_direct_saved":
            if w.state["dirty"]:
                return
            self._require("14/09/2026" in PdfReader(self.output).pages[0].extract_text(),
                          "Guardar no actualizó el destino recordado.")
            self._step("guardar_destino_recordado_v300", destination=str(self.output), shortcut="Ctrl+S")
            self._edit_date("14/09/2026", "15/09/2026")
            self.stage = "v300_cancel_ready"
            return
        if self.stage == "v300_cancel_ready":
            if not self._date_ready("15/09/2026"):
                return
            w._ask_close_v300 = lambda entries, app=False: "cancel"
            self._require(w._close_tab_v200(0), "No se inició el cierre con cambios pendientes.")
            self.stage = "v300_cancelled"
            return
        if self.stage == "v300_cancelled":
            self._require(w.document_tabs_v200.count() == 2 and w.state["dirty"]
                          and self._date_ready("15/09/2026"), "Cancelar el cierre perdió la pestaña o su edición.")
            self._step("cancelar_cierre_v300", tabs_retained=2, dirty_retained=True)
            w._ask_close_v300 = lambda entries, app=False: "save"
            self._require(w._close_tab_v200(0), "No se inició Guardar al cerrar.")
            self.stage = "v300_closed_saved"
            return
        if self.stage == "v300_closed_saved":
            if w.document_tabs_v200.count() != 1 or not self._tab_ready(self.second_session):
                return
            self._require("15/09/2026" in PdfReader(self.output).pages[0].extract_text(),
                          "Guardar al cerrar retiró la pestaña antes de escribir sus cambios.")
            self._step("guardar_antes_de_cerrar_v300", closed_tabs=1, independently_extracted=True)
            self._check_typography_runtime()
            self._object_text_before = self._text(w.model)
            self._object_history_before = w.state["history_index"]
            self.stage = "v300_objects_graph"
            self._require(w._submit("object_graph_v300", {"page": 0},
                                  lambda info: setattr(self, "_v300_graph", info)),
                          "No se inició el inventario nativo en el proceso PDF.")
            return
        if self.stage == "v300_objects_graph":
            if self._v300_graph is None:
                return
            candidates = [item for item in self._v300_graph["items"]
                          if item["kind"] == "text" and item["capabilities"]["move"]
                          and item["rect"] and item["rect"][1] < 600]
            self._require(candidates, "El inventario no contiene una aparición de texto editable.")
            item = min(candidates, key=lambda value: (value["rect"][2]-value["rect"][0])
                       * (value["rect"][3]-value["rect"][1]))
            self._object_id = item["id"]
            self._object_rect = item["rect"]
            self.stage = "v300_object_preview"
            self._require(w._submit("object_edit_v300", {
                "page": 0, "object_id": item["id"], "operation": "move",
                "revision": self._v300_graph["revision"], "dx": 3., "dy": 2.,
            }, w._previewed), "No se inició el movimiento de la aparición PDF.")
            return
        if self.stage == "v300_object_preview":
            if not w.state.get("preview") or w.model.revision != w.state.get("document_revision"):
                return
            self._require(w.last_report["verified"] and w.last_report["validation"]["verified"],
                          "El movimiento no verificó la conservación del PDF.")
            self.stage = "v300_object_committed"
            w.commit()
            return
        if self.stage == "v300_object_committed":
            if w.state.get("preview") or w.model.revision != w.state.get("document_revision"):
                return
            self._require(w.state["history_index"] == self._object_history_before + 1
                          and self._text(w.model) == self._object_text_before,
                          "El movimiento cambió el texto o no creó una operación independiente.")
            self.edit_reports.append(w.last_report)
            self._step("motor_objetos_v300", operation="move", object_id=self._object_id,
                       text_retained=True, checked_outside_edit_regions=True,
                       single_history_operation=True)
            font_path = self._typography_font_path()
            self.stage = "v300_typography_prepare"
            self._require(w._submit("rich_prepare", {"request": {
                "page": 0, "ids": [], "rect": (40., 680., 320., 730.),
                "runs": [{"text": "office q\u0308", "font_name": "LiberationSans",
                          "font_file": str(font_path), "size": 12., "color": (0., 0., 0.),
                          "font_features": {"liga": 1}}],
                "paragraphs": [{"direction": "ltr"}],
            }, "zoom": w.zoom}, lambda result: setattr(self, "_v300_typography", result)),
                          "No se preparó la composición tipográfica en el proceso PDF.")
            return
        if self.stage == "v300_typography_prepare":
            if self._v300_typography is None:
                return
            report = self._v300_typography["report"]
            self._require(report.get("typography") and report.get("shaping_engine") == "HarfBuzz",
                          "La edición no utilizó la composición tipográfica OpenType.")
            self.stage = "v300_typography_committed"
            self._require(w._submit("rich_commit", {"token": self._v300_typography["token"]}, w._edited),
                          "No se aplicó el texto compuesto con HarfBuzz.")
            return
        if self.stage == "v300_typography_committed":
            if w.state.get("preview") or w.model.revision != w.state.get("document_revision"):
                return
            self._require("office q\u0308" in self._text(w.model),
                          "El modelo de selección perdió el texto lógico compuesto.")
            self.edit_reports.append(w.last_report)
            self.stage = "v300_typography_saved"
            w.save_action.trigger()
            return
        if self.stage == "v300_typography_saved":
            if w.state["dirty"]:
                return
            pdf = PdfReader(self.second_output)
            self._require("office q\u0308" in pdf.pages[0].extract_text(),
                          "El PDF tipográfico no permite extraer independientemente su texto lógico.")
            self._require("10/09/2026" in pdf.pages[1].extract_text(),
                          "La composición tipográfica cambió la página de control.")
            self._step("tipografia_pdf_v300", shaping_engine="HarfBuzz", combining_text_checked=True,
                       independently_extracted=True, control_page_retained=True)
            self.stage = "complete"
            self.finish()
            return

    @staticmethod
    def _typography_font_path():
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        return root / "assets/fonts/LiberationSans-Regular.ttf"

    def _check_typography_runtime(self):
        import uharfbuzz as hb
        from bidi.algorithm import get_display
        font_data = self._typography_font_path().read_bytes()
        font = hb.Font(hb.Face(font_data))
        buffer = hb.Buffer()
        buffer.add_str("office á")
        buffer.guess_segment_properties()
        hb.shape(font, buffer)
        self._require(buffer.glyph_infos and all(info.codepoint for info in buffer.glyph_infos),
                      "El motor tipográfico empaquetado no compone el texto de prueba.")
        self._require(get_display("אבג") == "גבא", "El motor bidireccional no está disponible.")
        self._step("tipografia_runtime_v300", harfbuzz_glyphs=len(buffer.glyph_infos),
                   bidirectional_checked=True, scope="Carga de extensiones; PDF tipográfico cubierto por pytest")

    def finish(self, error=None, terminate=False):
        if error is None and self.stage == "complete" and not self._v300_started:
            self._v300_started = True
            self.stage = "v300_second_activate"
            self.window.document_tabs_v200.setCurrentIndex(1)
            return
        super().finish(error, terminate)
