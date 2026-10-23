"""One print dialog, a bounded inline preview and direct, explicit printing."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewWidget
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .printing_v201 import (
    PrintOptionsV200, configure_printer_v201, print_job_pages_v201,
    print_target_v200, printer_capabilities_v201, select_print_pages_v201,
    set_print_layout_v201,
)


class PrintDialogV309(PrintOptionsV200):
    preview_requested = Signal()
    preview_invalidated = Signal()
    print_requested = Signal()

    def __init__(self, count, current, parent=None):
        super().__init__(count, current, parent)
        self.setWindowTitle('Imprimir')
        self.setObjectName('printDialogV309')
        self.resize(1120, 760)
        self._preparing = self._spooling = False
        self._preview_image = None
        self._preview_page = None
        self._preview_settings = None
        self.buttons.hide()
        self.layout().removeWidget(self.buttons)
        self.buttons.deleteLater()
        self.note.setText('La vista preliminar se muestra aquí. Pulsa Imprimir para enviar '
                          'el trabajo con estas opciones. Tamaño real puede recortar contenido '
                          'si el papel es menor. Guardar como conserva el PDF vectorial.')
        self.error.setTextFormat(Qt.PlainText)
        options = QWidget()
        options.setLayout(self.layout())
        options.layout().addStretch(1)
        self.options_scroll = QScrollArea()
        self.options_scroll.setWidgetResizable(True)
        self.options_scroll.setMinimumWidth(320)
        self.options_scroll.setMaximumWidth(430)
        self.options_scroll.setWidget(options)
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(self.options_scroll, 0)
        right = QVBoxLayout()
        navigation = QHBoxLayout()
        self.previous = QPushButton('◀')
        self.previous.setFixedWidth(34)
        self.previous.setToolTip('Página anterior de la selección')
        self.previous.clicked.connect(lambda: self.page.setValue(self.page.value()-1))
        navigation.addWidget(self.previous)
        self.page = QSpinBox()
        self.page.setObjectName('printPreviewPageV309')
        self.page.setRange(1, count)
        navigation.addWidget(self.page)
        self.total = QLabel()
        navigation.addWidget(self.total)
        self.following = QPushButton('▶')
        self.following.setFixedWidth(34)
        self.following.setToolTip('Página siguiente de la selección')
        self.following.clicked.connect(lambda: self.page.setValue(self.page.value()+1))
        navigation.addWidget(self.following)
        self.preview_printer = QPrinter(QPrinter.HighResolution)
        if not self.printer.currentData():
            self.preview_printer.setOutputFormat(QPrinter.PdfFormat)
        self.preview = QPrintPreviewWidget(self.preview_printer, self)
        self.preview.setObjectName('inlinePrintPreviewV309')
        self.preview.paintRequested.connect(self._paint_preview)
        for label, callback in (('−', self.preview.zoomOut), ('+', self.preview.zoomIn),
                                ('Ajustar página', self.preview.fitInView)):
            button = QPushButton(label)
            if label in ('−', '+'):
                button.setFixedWidth(34)
            button.clicked.connect(lambda _=False, slot=callback: slot())
            navigation.addWidget(button)
        right.addLayout(navigation)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        self.preview_stack = QStackedWidget()
        self.placeholder = QLabel('Preparando vista preliminar…')
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.preview_stack.addWidget(self.placeholder)
        self.preview_stack.addWidget(self.preview)
        right.addWidget(self.preview_stack, 1)
        row.addLayout(right, 1)
        root.addLayout(row, 1)
        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        footer.addWidget(self.status, 1)
        self.print_button = QPushButton('Imprimir')
        self.print_button.setObjectName('printDirectV309')
        self.print_button.setDefault(True)
        self.print_button.clicked.connect(self.validate)
        footer.addWidget(self.print_button)
        self.cancel_button = QPushButton('Cancelar')
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(180)
        self.preview_timer.timeout.connect(self.preview_requested)
        for control in (self.printer, self.color, self.duplex, self.scope,
                        self.scale, self.orientation, self.paper):
            control.currentIndexChanged.connect(self._changed)
        for control in (self.copies, self.dpi, self.page):
            control.valueChanged.connect(self._changed)
        self.collate.toggled.connect(self._changed)
        self.pages.textChanged.connect(self._changed)
        self._changed()

    def selected_pages(self):
        numbers = select_print_pages_v201(self.scope.currentData(), self.count,
                                         self.current, self.pages.text())
        if len(numbers) > 1000:
            raise ValueError('Selecciona un intervalo de hasta 1000 páginas para imprimir.')
        return numbers

    def _changed(self, *_):
        if self._preparing:
            return
        self.preview_invalidated.emit()
        try:
            numbers = self.selected_pages()
            self.error.clear()
            self.page.setMaximum(len(numbers))
            self.total.setText(f'/ {len(numbers)}')
            self.summary.setText(f'Página original {numbers[self.page.value()-1]+1} · '
                                 f'{self.copies.value()} copia(s)')
            self.previous.setEnabled(self.page.value() > 1)
            self.following.setEnabled(self.page.value() < len(numbers))
            self.print_button.setEnabled(bool(self.printer.currentData()))
            self.preview_timer.start()
        except Exception as exc:
            self.error.setText(str(exc))
            self.preview_timer.stop()
            self.print_button.setEnabled(False)
            self.placeholder.setText('Revisa el intervalo de páginas.')
            self.preview_stack.setCurrentWidget(self.placeholder)

    def validate(self):
        if self._preparing or not self.print_button.isEnabled():
            return
        try:
            self.numbers = self.selected_pages()
        except Exception as exc:
            self.error.setText(str(exc))
            return
        self.preview_timer.stop()
        self.print_requested.emit()

    def set_preparing(self, preparing):
        self._preparing = preparing
        self.options_scroll.setEnabled(not preparing)
        self.page.setEnabled(not preparing)
        self.previous.setEnabled(not preparing and self.page.value() > 1)
        self.following.setEnabled(not preparing and self.page.value() < self.page.maximum())
        self.print_button.setEnabled(not preparing and bool(self.printer.currentData()))
        if preparing:
            self.preview_timer.stop()
        else:
            error = self.error.text()
            self._changed()
            # Unlocking after a failed job must retain its explanation and
            # must not automatically start another PDF preparation.
            self.preview_timer.stop()
            if error:
                self.error.setText(error)

    def set_spooling(self, spooling):
        self._spooling = spooling
        self.cancel_button.setEnabled(not spooling)

    def reject(self):
        if not self._spooling:
            self.preview_timer.stop()
            super().reject()

    def closeEvent(self, event):
        if self._spooling:
            event.ignore()
        else:
            super().closeEvent(event)

    def show_preview(self, page, settings):
        image = QImage(page['path'])
        if image.isNull():
            raise ValueError('No se pudo leer la página de vista preliminar.')
        # The worker clears its prior print folder on its next request. Own the
        # decoded image so option changes never reread a deleted temporary file.
        self._preview_image = image
        self._preview_page = {key: page[key] for key in ('page', 'width', 'height', 'dpi')}
        self.redraw_preview(settings)

    def redraw_preview(self, settings):
        if self._preview_image is None:
            return
        self._preview_settings = dict(settings, preview=True, copies=1, dpi=120)
        configure_printer_v201(self.preview_printer, self._preview_settings,
                              printer_capabilities_v201(settings['printer']))
        self.preview_stack.setCurrentWidget(self.preview)
        self.preview.updatePreview()
        self.preview.fitInView()

    def _paint_preview(self, printer):
        if self._preview_image is None:
            return
        painter = QPainter()
        try:
            page, settings = self._preview_page, self._preview_settings
            set_print_layout_v201(printer, page, settings)
            if not painter.begin(printer):
                raise ValueError('No se pudo dibujar la vista preliminar.')
            image = self._preview_image
            if settings['color'] == QPrinter.GrayScale:
                image = image.convertToFormat(QImage.Format_Grayscale8)
            rect = printer.pageLayout().paintRectPixels(printer.resolution())
            area = QRectF(0, 0, rect.width(), rect.height())
            target = print_target_v200(page['width'], page['height'], area,
                                      printer.resolution(), settings['fit'])
            painter.drawImage(target, image)
        except Exception as exc:
            self.error.setText(str(exc))
        finally:
            if painter.isActive():
                painter.end()


class PrintingV309Mixin:
    def _init_printing_v200(self):
        super()._init_printing_v200()
        self.print_action_v200.setText('Imprimir…')

    def choose_print_v200(self):
        if not self.state or self.busy or self.state.get('preview'):
            return
        if (self.canvas.editor.isVisible() or getattr(self, '_rich_active', False)
                or getattr(self, '_rich_loading', False)):
            self._error('Acepta o cancela el texto que estás escribiendo antes de imprimir.')
            return
        if getattr(self, '_print_context_v309', None) is not None:
            return
        dialog = PrintDialogV309(self.state['page_count'], self.page_number, self)
        context = {'dialog': dialog, 'session': self._active_session_v200,
                   'revision': self.state['document_revision'], 'closed': False,
                   'serial': 0, 'pending': None, 'inflight': None, 'job': None}
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.setInterval(40)
        timer.timeout.connect(lambda: self._pump_print_v309(context))
        context['timer'] = timer
        self._print_context_v309 = context
        self._print_dialog_v200 = dialog
        dialog.preview_requested.connect(lambda: self._request_preview_v309(context))
        dialog.preview_invalidated.connect(lambda: self._invalidate_print_preview_v309(context))
        dialog.print_requested.connect(lambda: self._request_print_v309(context))
        failed = lambda message: self._print_failed_v309(context, message)
        self.error_raised.connect(failed)
        try:
            self._exec_edit_dialog(dialog)
        finally:
            context['closed'] = True
            timer.stop()
            dialog.preview_timer.stop()
            self.error_raised.disconnect(failed)
            self._print_context_v309 = None
            self._print_dialog_v200 = None
            dialog.deleteLater()

    def _print_context_current_v309(self, context):
        return (not context['closed'] and not self._closed
                and self._active_session_v200 == context['session']
                and self.state.get('document_revision') == context['revision'])

    def _request_preview_v309(self, context):
        if not self._print_context_current_v309(context) or context['job'] is not None:
            return
        dialog = context['dialog']
        try:
            numbers = dialog.selected_pages()
            number = numbers[dialog.page.value()-1]
            settings = dialog.settings()
            context['serial'] += 1
            if dialog._preview_page and dialog._preview_page['page'] == number:
                context['pending'] = None
                dialog.redraw_preview(settings)
                return
            context['pending'] = (context['serial'], number, settings)
            context['timer'].start(0)
        except Exception as exc:
            dialog.error.setText(str(exc))

    def _invalidate_print_preview_v309(self, context):
        if not context['closed'] and context['job'] is None:
            context['serial'] += 1
            context['pending'] = None

    def _make_print_printer_v309(self, settings):
        if not settings['printer']:
            raise ValueError('Selecciona una impresora disponible.')
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.NativeFormat)
        configure_printer_v201(printer, settings, printer_capabilities_v201(settings['printer']))
        if not printer.isValid() or printer.printerName() != settings['printer']:
            raise ValueError('La impresora seleccionada no está disponible.')
        printer.setPrintRange(QPrinter.AllPages)
        printer.setPageOrder(QPrinter.FirstPageFirst)
        printer.setDocName(Path(self.state.get('path', 'PDF Modder')).name)
        # Check the driver's copies/duplex contract before rendering a long job.
        print_job_pages_v201(printer, [None])
        return printer

    def _request_print_v309(self, context):
        if not self._print_context_current_v309(context) or context['job'] is not None:
            return
        dialog = context['dialog']
        try:
            numbers, settings = dialog.selected_pages(), dialog.settings()
            printer = self._make_print_printer_v309(settings)
            context['job'] = (numbers, settings, printer)
            context['pending'] = None
            context['serial'] += 1
            dialog.set_preparing(True)
            dialog.status.setText(f'Preparando {len(numbers)} página(s) para imprimir…')
            context['timer'].start(0)
        except Exception as exc:
            dialog.error.setText(str(exc))

    def _pump_print_v309(self, context):
        if not self._print_context_current_v309(context):
            return
        if context['dialog']._spooling:
            return
        if context['inflight'] is not None or self.busy:
            context['timer'].start()
            return
        dialog = context['dialog']
        if context['job'] is not None:
            numbers, settings, printer = context['job']
            kind, serial = 'print', context['serial']
            dpi = settings['dpi']
        elif context['pending'] is not None:
            serial, number, settings = context['pending']
            context['pending'] = None
            kind, numbers, dpi = 'preview', [number], 120
        else:
            return
        context['inflight'] = kind

        def prepared(result):
            context['inflight'] = None
            if not self._print_context_current_v309(context):
                return
            pages = result['pages']
            if (result.get('revision') != context['revision']
                    or [page['page'] for page in pages] != numbers):
                self._print_failed_v309(context, 'El documento o las páginas cambiaron durante la preparación.', force=True)
                return
            if kind == 'preview':
                if serial == context['serial'] and context['job'] is None:
                    try:
                        dialog.show_preview(pages[0], dialog.settings())
                    except Exception as exc:
                        dialog.error.setText(str(exc))
                context['timer'].start(0)
                return
            # No preview request may now delete the prepared print images.
            dialog.set_spooling(True)
            dialog.status.setText('Enviando el trabajo a la impresora…')
            try:
                actual = min(page['dpi'] for page in pages)
                if actual < dpi-.1:
                    self._notice(f'Resolución efectiva limitada a {actual:.1f} ppp por memoria o permisos del documento.')
                if self._paint_print_v200(printer, pages, dict(settings, preview=False)):
                    self.statusBar().showMessage('Trabajo enviado a la impresora.')
                    dialog.accept()
                else:
                    dialog.error.setText(self.last_error or 'No se pudo finalizar la impresión.')
            finally:
                dialog.set_spooling(False)
                context['job'] = None
                dialog.set_preparing(False)

        if not self._submit('print_pages_v200', {'pages': numbers, 'dpi': dpi}, prepared):
            self._print_failed_v309(context, 'No se pudo iniciar la preparación de impresión.', force=True)

    def _print_failed_v309(self, context, message, *, force=False):
        if context['closed'] or (context['inflight'] is None and not force):
            return
        kind, context['inflight'] = context['inflight'], None
        dialog = context['dialog']
        dialog.error.setText(str(message))
        dialog.status.clear()
        if kind == 'print' or force:
            context['job'] = None
            dialog.set_preparing(False)
        if context['job'] is not None or context['pending'] is not None:
            context['timer'].start(0)
