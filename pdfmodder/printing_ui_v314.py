"""Progressive, cancellable printing against one immutable document revision."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtPrintSupport import QPrinter

from .draft_control_v305 import DraftControl
from .printing_v201 import print_job_pages_v201, printer_capabilities_v201


class PrintingUiV314Mixin:
    @staticmethod
    def _release_print_images_v314(pages):
        for page in pages:
            path = Path(page['path'])
            if path.parent.name.startswith('pdfmodder-print-') and path.suffix == '.png' and path.stem.isdigit():
                try:
                    path.unlink(missing_ok=True)
                    path.parent.rmdir()
                except OSError:
                    # The worker also owns this temporary directory and cleans
                    # it on its next request or when the document closes.
                    pass

    def choose_print_v200(self):
        if not self.state or self.busy or self.state.get('preview'):
            return
        if (self.canvas.editor.isVisible() or getattr(self, '_rich_active', False)
                or getattr(self, '_rich_loading', False)):
            self._error('Acepta o cancela el texto que estás escribiendo antes de imprimir.')
            return
        if getattr(self, '_print_context_v314', None) is not None:
            return
        from .printing_dialog_v314 import PrintDialogV314
        dialog = PrintDialogV314(self.state['page_count'], self.page_number, self,
                                preferences=self._printer_preferences_v311)
        context = {'dialog': dialog, 'session': self._active_session_v200,
                   'revision': self.state['document_revision'], 'closed': False,
                   'cancelled': False, 'inflight': None, 'job': None, 'spool': None,
                   'preview_wanted': None, 'preview_inflight': None,
                   'preview_control': DraftControl(), 'print_control': DraftControl(),
                   'ticket': None, 'index': 0, 'geometries': {}, 'quality_noted': None}
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.setInterval(25)
        timer.timeout.connect(lambda: self._pump_print_v314(context))
        context['timer'] = timer
        self._print_context_v314 = context
        # Retain the established reference used by other window safeguards.
        self._print_dialog_v200 = dialog
        dialog.preview_invalidated.connect(lambda: self._preview_changed_v314(context))
        dialog.preview_requested.connect(lambda: self._request_preview_v314(context))
        dialog.print_requested.connect(lambda: self._request_print_v314(context))
        dialog.cancel_requested.connect(lambda: self._cancel_print_v314(context))
        failed = lambda message: self._print_error_v314(context, message)
        self.error_raised.connect(failed)
        try:
            self._exec_edit_dialog(dialog)
        finally:
            context['closed'] = True
            timer.stop()
            context['preview_control'].close()
            context['print_control'].close()
            if context['spool'] is not None:
                context['spool'].cancel()
            self.error_raised.disconnect(failed)
            self._print_context_v314 = None
            self._print_dialog_v200 = None
            dialog.deleteLater()

    def _print_current_v314(self, context):
        return bool(not context['closed'] and not self._closed
                    and self._active_session_v200 == context['session']
                    and self.state.get('document_revision') == context['revision'])

    def _preview_number_v314(self, context):
        dialog = context['dialog']
        return dialog.selected_pages()[dialog.page.value()-1]

    def _preview_changed_v314(self, context):
        if context['closed'] or context['job'] is not None or context['cancelled']:
            return
        try:
            number = self._preview_number_v314(context)
        except Exception:
            return
        dialog = context['dialog']
        first = dialog.selected_pages()[0]
        anchor = context['geometries'].get(first)
        dialog.set_sheet_plan_v314(anchor)
        if dialog._preview_page is None or dialog._preview_page['page'] != number:
            dialog.mark_preview_pending(number)
        if context['preview_inflight'] is not None and context['preview_inflight'] != number:
            context['preview_control'].invalidate()
        cached = dialog._preview_page is not None and dialog._preview_page['page'] == number
        context['preview_wanted'] = None if cached and anchor is not None else number

    def _request_preview_v314(self, context):
        if not self._print_current_v314(context) or context['job'] is not None or context['cancelled']:
            return
        try:
            number = self._preview_number_v314(context)
            dialog = context['dialog']
            anchor = context['geometries'].get(dialog.selected_pages()[0])
            dialog.set_sheet_plan_v314(anchor)
            if dialog._preview_page is not None and dialog._preview_page['page'] == number and anchor is not None:
                context['preview_wanted'] = None
                dialog.redraw_preview(dialog.settings())
                return
            context['preview_wanted'] = number
            dialog.mark_preview_pending(number)
            context['timer'].start(0)
        except Exception as exc:
            context['dialog'].error.setText(str(exc))

    def _make_print_printer_v314(self, settings):
        from .printing_device_v314 import configure_printer_v314
        if not settings['printer']:
            raise ValueError('Selecciona una impresora disponible.')
        printer = settings.get('printer_device_v314')
        if printer is None:
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.NativeFormat)
        configure_printer_v314(printer, settings, printer_capabilities_v201(settings['printer']))
        printer.setPrintRange(QPrinter.AllPages)
        printer.setPageOrder(QPrinter.FirstPageFirst)
        printer.setDocName(Path(self.state.get('path', 'PDF Modder')).name)
        return printer

    def _request_print_v314(self, context):
        if not self._print_current_v314(context) or context['job'] is not None or context['cancelled']:
            return
        try:
            dialog = context['dialog']
            settings = dialog.settings()
            settings.pop('sheet_page_v314', None)
            printer = self._make_print_printer_v314(settings)
            numbers = print_job_pages_v201(printer, dialog.selected_pages())
            if not numbers:
                raise ValueError('Selecciona al menos una página.')
            from .printing_device_v314 import PrintSpoolV314
            spool = PrintSpoolV314(printer, settings)
            context.update(job=(numbers, settings, printer), spool=spool, index=0,
                           preview_wanted=None, quality_noted=None, ticket=context['print_control'].ticket())
            context['preview_control'].invalidate()
            dialog.preview_timer.stop()
            dialog.set_preparing(True)
            dialog.set_progress(0, len(numbers), 'Preparando')
            context['timer'].start(0)
        except Exception as exc:
            context['dialog'].error.setText(str(exc))

    def _pump_print_v314(self, context):
        if context['closed']:
            return
        if not self._print_current_v314(context):
            self._cancel_print_v314(context)
            return
        if context['inflight'] is not None or self.busy:
            context['timer'].start()
            return
        if context['cancelled']:
            self._finish_cancel_v314(context)
            return
        job = context['job']
        if job is not None:
            numbers, settings, _printer = job
            if context['index'] >= len(numbers):
                self._complete_print_v314(context)
                return
            kind, number, dpi = 'print', numbers[context['index']], settings['dpi']
            ticket = context['ticket']
            context['dialog'].set_progress(context['index'], len(numbers), 'Preparando')
        elif context['preview_wanted'] is not None:
            kind, number, dpi = 'preview', context['preview_wanted'], 120
            context['preview_wanted'] = None
            dialog = context['dialog']
            anchor = context['geometries'].get(dialog.selected_pages()[0])
            if dialog._preview_page is not None and dialog._preview_page['page'] == number and anchor is not None:
                dialog.set_sheet_plan_v314(anchor)
                dialog.redraw_preview(dialog.settings())
                return
            context['preview_inflight'] = number
            ticket = context['preview_control'].ticket()
        else:
            return
        context['inflight'] = kind

        def prepared(result):
            context['inflight'] = None
            if kind == 'preview':
                context['preview_inflight'] = None
            if context['closed']:
                self._release_print_images_v314(result.get('pages', []))
                return
            if context['cancelled'] or not self._print_current_v314(context):
                self._release_print_images_v314(result.get('pages', []))
                self._cancel_print_v314(context)
                return
            if result.get('print_cancelled_v314'):
                context['timer'].start(0)
                return
            pages = result.get('pages', [])
            if result.get('revision') != context['revision'] or [p['page'] for p in pages] != [number]:
                self._release_print_images_v314(pages)
                self._print_error_v314(context, 'La página preparada no corresponde a esta revisión del documento.')
                return
            dialog = context['dialog']
            context['geometries'][number] = {key: pages[0][key] for key in ('page', 'width', 'height')}
            anchor_result = result.get('layout_page_v314')
            if anchor_result is not None:
                context['geometries'][anchor_result['page']] = anchor_result
            if kind == 'preview':
                if context['job'] is None:
                    try:
                        wanted = self._preview_number_v314(context)
                        anchor = context['geometries'].get(dialog.selected_pages()[0])
                        if wanted == number and anchor is not None:
                            # Presentation changes never invalidate immutable pixels.
                            dialog.set_sheet_plan_v314(anchor)
                            dialog.show_preview(pages[0], dialog.settings())
                            if context['preview_wanted'] == number:
                                context['preview_wanted'] = None
                    except Exception as exc:
                        dialog.error.setText(str(exc))
                self._release_print_images_v314(pages)
                context['timer'].start(0)
                return
            try:
                dialog.set_spooling(True)
                numbers, settings, _ = context['job']
                if context['index'] == 0:
                    context['spool'].settings['sheet_page_v314'] = context['geometries'][numbers[0]]
                dialog.set_progress(context['index'], len(numbers), 'Enviando')
                if not context['spool'].push(pages[0]):
                    raise RuntimeError(context['spool'].error or 'No se pudo enviar la página.')
                context['index'] += 1
                dialog.set_progress(context['index'], len(numbers), 'Enviado')
                # Preserve the established quality limit/notice, without adding
                # new resolution controls or a different rendering path.
                if (pages[0]['dpi'] < settings['dpi']-.1 and
                        (context['quality_noted'] is None or pages[0]['dpi'] < context['quality_noted']-.1)):
                    self._notice(f"Resolución efectiva limitada a {pages[0]['dpi']:.1f} ppp por memoria o permisos del documento.")
                    context['quality_noted'] = pages[0]['dpi']
                context['timer'].start(0)
            except Exception as exc:
                self._print_error_v314(context, str(exc))
            finally:
                self._release_print_images_v314(pages)

        first = context['job'][0][0] if context['job'] is not None else context['dialog'].selected_pages()[0]
        payload = {'pages': [number], 'dpi': dpi, 'revision': context['revision'], 'control': ticket,
                   'layout_page': first}
        if not self._submit('print_pages_v200', payload, prepared):
            context['inflight'] = None
            if kind == 'preview':
                context['preview_inflight'] = None
                context['preview_wanted'] = number
            context['timer'].start()

    def _complete_print_v314(self, context):
        dialog = context['dialog']
        try:
            if not context['spool'].finish():
                raise RuntimeError(context['spool'].error or 'No se pudo finalizar la impresión.')
            settings = context['job'][1]
            context['spool'] = None
            context['job'] = None
            self.statusBar().showMessage('Trabajo enviado a la impresora.')
            try:
                self._printer_preferences_v311.remember(settings['printer'], settings)
            except OSError as exc:
                self._notice('Trabajo enviado. No se pudieron recordar las preferencias: '+str(exc))
            dialog.set_spooling(False)
            dialog.accept()
        except Exception as exc:
            self._print_error_v314(context, str(exc))

    def _cancel_print_v314(self, context):
        if context['closed']:
            return
        context['cancelled'] = True
        context['preview_control'].invalidate()
        context['print_control'].invalidate()
        context['preview_wanted'] = None
        spool = context['spool']
        if spool is not None:
            if not spool.cancel():
                self._notice('Preparación detenida. No se pudo confirmar la retirada del trabajo; comprueba la cola de impresión de Windows.')
            context['spool'] = None
        context['dialog'].status.setText('Cancelando la impresión…')
        if context['inflight'] is None:
            self._finish_cancel_v314(context)
        else:
            context['timer'].start()

    def _finish_cancel_v314(self, context):
        context['timer'].stop()
        context['job'] = None
        context['dialog'].set_spooling(False)
        context['dialog'].finish_cancel()

    def _print_error_v314(self, context, message):
        if context['closed']:
            return
        context['inflight'] = None
        context['preview_inflight'] = None
        if context['cancelled']:
            self._finish_cancel_v314(context)
            return
        context['print_control'].invalidate()
        if context['spool'] is not None:
            context['spool'].cancel()
            context['spool'] = None
        context['job'] = None
        context['timer'].stop()
        dialog = context['dialog']
        dialog.set_spooling(False)
        dialog.set_preparing(False)
        dialog.error.setText(message)
