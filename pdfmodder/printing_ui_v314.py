"""Progressive, cancellable printing against one immutable document revision."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtPrintSupport import QPrinter

from .draft_control_v305 import DraftControl
from .printing_v201 import print_job_pages_v201, printer_capabilities_v201


class PrintingUiV314Mixin:
    @staticmethod
    def _release_print_images_v314(pages):
        from .printing_background_v318 import release_print_pages_v318
        release_print_pages_v318(pages)

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
        context = self._new_print_context_v314(dialog)
        self._print_dialog_v200 = dialog
        dialog.preview_invalidated.connect(lambda: self._preview_changed_v314(context))
        dialog.preview_requested.connect(lambda: self._request_preview_v314(context))
        dialog.print_requested.connect(lambda: self._request_print_v314(context))
        dialog.cancel_requested.connect(lambda: self._cancel_print_v314(context))
        try:
            self._exec_edit_dialog(dialog)
        finally:
            self._close_print_context_v314(context)

    def print_to_default_v320(self):
        if (not self.state or self.busy or self.state.get('preview') or self._closed
                or getattr(self, '_print_context_v314', None) is not None):
            return False
        if (self.canvas.editor.isVisible() or getattr(self, '_rich_active', False)
                or getattr(self, '_rich_loading', False)):
            self._error('Acepta o cancela el texto que estás escribiendo antes de imprimir.')
            return False
        from .printing_direct_v320 import DirectPrintStatusV320, system_default_printer_v320
        try:
            settings = system_default_printer_v320(self.state.get('path', 'Documento.pdf'))
        except (OSError, ValueError, RuntimeError) as exc:
            self._error(str(exc))
            return False
        status = DirectPrintStatusV320(self, settings, self.state['page_count'])
        context = self._new_print_context_v314(status, direct=True)
        status.context = context
        self._refresh_actions()
        self._request_print_v314(context)
        return not context['closed']

    def _new_print_context_v314(self, dialog, *, direct=False):
        context = {'dialog': dialog, 'session': self._active_session_v200,
                   'revision': self.state['document_revision'], 'closed': False,
                   'cancelled': False, 'inflight': None, 'job': None, 'spool': None,
                   'preview_wanted': None, 'preview_inflight': None,
                   'preview_control': DraftControl(), 'print_control': DraftControl(),
                   'ticket': None, 'index': 0, 'geometries': {}, 'quality_noted': None,
                   'direct_v320': direct}
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.setInterval(25)
        timer.timeout.connect(lambda: self._pump_print_v314(context))
        context['timer'] = timer
        self._print_context_v314 = context
        failed = lambda message: self._print_error_v314(context, message)
        context['error_handler_v320'] = failed
        self.error_raised.connect(failed)
        return context

    def _close_print_context_v314(self, context):
        if context['closed']:
            return
        context['closed'] = True
        context['timer'].stop()
        context['preview_control'].close()
        context['print_control'].close()
        if context['spool'] is not None:
            context['spool'].cancel()
        self.error_raised.disconnect(context['error_handler_v320'])
        if getattr(self, '_print_context_v314', None) is context:
            self._print_context_v314 = None
        if getattr(self, '_print_dialog_v200', None) is context['dialog']:
            self._print_dialog_v200 = None
        context['dialog'].deleteLater()
        if context.get('direct_v320'):
            self._refresh_actions()
            if getattr(self, '_close_after_print_v320', False):
                self._close_after_print_v320 = False
                QTimer.singleShot(0, self.close)

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
        if settings.get('preserve_driver_defaults_v320'):
            from .printing_device_v314 import validate_printer_settings_v314
            validate_printer_settings_v314(printer, settings)
        else:
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
            from .printing_background_v318 import BackgroundPrintSpoolV318
            spool = BackgroundPrintSpoolV318(printer, settings)
            context.update(job=(numbers, settings, printer), spool=spool, index=0,
                           preview_wanted=None, quality_noted=None, finishing_v318=False,
                           spool_error_v318=None, ticket=context['print_control'].ticket())
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
        self._drain_print_spool_v318(context)
        if context['closed']:
            return
        if not self._print_current_v314(context) and not context['cancelled']:
            self._cancel_print_v314(context)
            return
        if context['cancelled']:
            if context['inflight'] is None and context['spool'] is None:
                self._finish_cancel_v314(context)
            else:
                context['timer'].start()
            return
        if context.get('spool_error_v318'):
            context['timer'].start()
            return
        if context['spool'] is not None and context['spool'].busy:
            context['timer'].start()
            return
        if context['inflight'] is not None or self.busy:
            context['timer'].start()
            return
        job = context['job']
        if job is not None:
            numbers, settings, _printer = job
            if context['index'] >= len(numbers):
                if not context.get('finishing_v318'):
                    context['finishing_v318'] = True
                    context['dialog'].status.setText('Finalizando el envío a la impresora…')
                    if not context['spool'].finish():
                        self._print_error_v314(context, 'No se pudo finalizar la impresión.')
                context['timer'].start()
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
                anchor = context['geometries'][numbers[0]] if context['index'] == 0 else None
                dialog.set_progress(context['index'], len(numbers), 'Enviando')
                if not context['spool'].push(pages[0], sheet_page=anchor):
                    self._release_print_images_v314(pages)
                    raise RuntimeError('No se pudo iniciar el envío de la página.')
                # The spool thread owns the prepared file until painting ends.
                context['timer'].start(0)
            except Exception as exc:
                self._print_error_v314(context, str(exc))

        first = context['job'][0][0] if context['job'] is not None else context['dialog'].selected_pages()[0]
        payload = {'pages': [number], 'dpi': dpi, 'revision': context['revision'], 'control': ticket,
                   'layout_page': first, 'raw_rgb': True}
        if not self._submit('print_pages_v200', payload, prepared):
            context['inflight'] = None
            if kind == 'preview':
                context['preview_inflight'] = None
                context['preview_wanted'] = number
            context['timer'].start()

    def _complete_print_v314(self, context):
        dialog = context['dialog']
        try:
            settings = context['job'][1]
            context['spool'] = None
            context['job'] = None
            self.statusBar().showMessage('Trabajo enviado a la impresora.')
            if not context.get('direct_v320'):
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
        if context['cancelled']:
            context['timer'].start()
            return
        context['cancelled'] = True
        context['preview_control'].invalidate()
        context['print_control'].invalidate()
        context['preview_wanted'] = None
        spool = context['spool']
        if spool is not None:
            spool.cancel()
        context['dialog'].status.setText('Cancelando la impresión…')
        if context['inflight'] is None and context['spool'] is None:
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
            if context['spool'] is None:
                self._finish_cancel_v314(context)
            else:
                context['spool'].cancel()
                context['timer'].start()
            return
        context['print_control'].invalidate()
        if context['spool'] is not None:
            context['spool_error_v318'] = message
            context['spool'].cancel()
            context['dialog'].status.setText('Deteniendo el envío…')
            context['timer'].start()
            return
        self._show_print_error_v318(context, message)

    def _show_print_error_v318(self, context, message):
        context['job'] = None
        context['spool_error_v318'] = None
        context['timer'].stop()
        dialog = context['dialog']
        dialog.set_spooling(False)
        dialog.set_preparing(False)
        dialog.error.setText(message)

    def _drain_print_spool_v318(self, context):
        spool = context['spool']
        if spool is None:
            return
        for record in spool.poll():
            kind = record['kind']
            if kind == 'push' and record['ok']:
                if not context['cancelled'] and not context.get('spool_error_v318'):
                    context['index'] += 1
                    numbers, settings, _ = context['job']
                    context['dialog'].set_progress(context['index'], len(numbers), 'Enviado')
                    dpi = record.get('dpi')
                    if (dpi is not None and dpi < settings['dpi']-.1 and
                            (context['quality_noted'] is None or dpi < context['quality_noted']-.1)):
                        self._notice(f'Resolución efectiva limitada a {dpi:.1f} ppp por memoria o permisos del documento.')
                        context['quality_noted'] = dpi
                continue
            if kind == 'finish' and record['ok'] and not context['cancelled']:
                context['spool'] = None
                self._complete_print_v314(context)
                return
            if kind == 'cancel':
                context['spool'] = None
                if not record['ok']:
                    self._notice('Preparación detenida. No se pudo confirmar la retirada del trabajo; comprueba la cola de impresión de Windows.')
                if context.get('spool_error_v318'):
                    self._show_print_error_v318(context, context['spool_error_v318'])
                elif context['cancelled'] and context['inflight'] is None:
                    self._finish_cancel_v314(context)
                return
            context['spool'] = None
            if context['cancelled']:
                if kind == 'finish' and record['ok']:
                    self._notice('El trabajo ya se había enviado; comprueba la cola de impresión si necesitas retirarlo.')
                if context['inflight'] is None:
                    self._finish_cancel_v314(context)
            else:
                self._show_print_error_v318(context, record.get('error') or 'No se pudo imprimir.')
            return
