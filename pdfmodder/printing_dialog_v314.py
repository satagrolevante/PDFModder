"""Unified print options with truthful preview identity and cancellable progress."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtGui import QPageLayout, QPainter
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QProgressBar

from . import printing_v201 as legacy
from .printing_v309 import PrintDialogV309
from .printer_preferences_v311 import DEFAULT_PRINT_SETTINGS_V311, print_profile_v311


def _defaults_v314(name, printer):
    from .printing_device_v314 import printer_defaults_v314
    return printer_defaults_v314(name, printer=printer)


def _new_device_v314(name):
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.NativeFormat)
    printer.setPrinterName(name)
    return printer


class PrintDialogV314(PrintDialogV309):
    cancel_requested = Signal()

    def __init__(self, count, current, parent=None, *, preferences=None):
        self._printer_error_v314 = ''
        self._range_error_v314 = ''
        self._profile_warning_v314 = ''
        self._printer_available_v314 = False
        self._native_devices_v314 = {}
        self._driver_flags_v314 = {}
        self._native_printer_v314 = None
        self._driver_layout_v314 = False
        self._setting_profile_v314 = False
        self._cancel_pending_v314 = False
        self._cancel_finished_v314 = False
        self._sheet_anchor_v314 = None
        self._properties_validated_v314 = False
        super().__init__(count, current, parent, preferences=preferences)
        self.setObjectName('printDialogV314')
        self.orientation.setItemText(0, 'Automática para el documento')
        self.paper.setToolTip('Se utiliza una hoja común para el trabajo. La primera opción '
                             'toma el tamaño de la primera página seleccionada; Propiedades '
                             'permite conservar un papel específico del controlador.')
        self.paper.activated.connect(self._choose_paper_v314)
        self.properties_button_v314 = QPushButton('Propiedades de la impresora…')
        self.properties_button_v314.setObjectName('printerPropertiesV314')
        self.properties_button_v314.setToolTip(
            'Configurar el controlador y volver. El trabajo se envía únicamente '
            'al pulsar Imprimir en el cuadro principal de PDFModder.')
        self.properties_button_v314.clicked.connect(self._choose_properties_v314)
        form = self.options_scroll.widget().layout().itemAt(0).layout()
        form.insertRow(1, self.properties_button_v314)
        self.profile_notice_v314 = QLabel()
        self.profile_notice_v314.setWordWrap(True)
        self.profile_notice_v314.setTextFormat(Qt.PlainText)
        options = self.options_scroll.widget().layout()
        options.insertWidget(options.indexOf(self.error), self.profile_notice_v314)
        self.properties_note_v314 = QLabel(
            'Propiedades solo configura el controlador. Al volver, revisa las '
            'opciones y pulsa Imprimir aquí para enviar el trabajo.')
        self.properties_note_v314.setWordWrap(True)
        form.insertRow(2, self.properties_note_v314)
        self.progress_v314 = QProgressBar()
        self.progress_v314.setObjectName('printProgressV314')
        self.progress_v314.setFormat('%v / %m')
        self.progress_v314.hide()
        self.layout().insertWidget(self.layout().count()-1, self.progress_v314)
        self.printer.activated.connect(self._refresh_printer_v314)
        self._show_errors_v314()
        self._update_available_controls_v314()

    def _refresh_printer_v314(self, *_):
        self.update_capabilities()
        self._changed()

    def _choose_paper_v314(self, *_):
        self._driver_layout_v314 = False
        self._changed()

    def _show_errors_v314(self):
        self.error.setText(self._printer_error_v314 or self._range_error_v314)
        if hasattr(self, 'profile_notice_v314'):
            self.profile_notice_v314.setText(self._profile_warning_v314)
            self.profile_notice_v314.setVisible(bool(self._profile_warning_v314))

    def _update_available_controls_v314(self):
        if not hasattr(self, 'print_button'):
            return
        idle = not (self._preparing or self._spooling or self._cancel_pending_v314)
        self.print_button.setEnabled(idle and self._printer_available_v314 and not self._range_error_v314)
        if hasattr(self, 'properties_button_v314'):
            self.properties_button_v314.setEnabled(idle and self._printer_available_v314)

    def update_capabilities(self, *_):
        self._printer_error_v314 = ''
        name = self.printer.currentData()
        self._printer_available_v314 = bool(name)
        try:
            caps = legacy.printer_capabilities_v201(name)
            modes = caps.get('duplex_modes')
            wanted_duplex = self.duplex.currentData()
            for index in range(self.duplex.count()):
                value = self.duplex.itemData(index)
                self.duplex.model().item(index).setEnabled(
                    value == QPrinter.DuplexNone or modes is None or value in modes)
            warnings = []
            index = self.duplex.currentIndex()
            if index >= 0 and not self.duplex.model().item(index).isEnabled():
                self.duplex.setCurrentIndex(self.duplex.findData(QPrinter.DuplexNone))
                if wanted_duplex != QPrinter.DuplexNone:
                    warnings.append('La doble cara elegida ya no está disponible según el '
                                    'controlador. Se ha seleccionado Una cara; revisa esta opción.')
            colors = caps.get('color_modes')
            allowed_color = colors is None or QPrinter.Color in colors
            self.color.model().item(self.color.findData(QPrinter.Color)).setEnabled(allowed_color)
            if not allowed_color and self.color.currentData() == QPrinter.Color:
                self.color.setCurrentIndex(self.color.findData(QPrinter.GrayScale))
                warnings.append('El controlador no ofrece color. Se ha seleccionado Escala de grises.')
            self._profile_warning_v314 = '\n'.join(warnings)
            if modes is None:
                message = 'Las opciones de doble cara se comprobarán con el controlador al imprimir.'
            elif any(value in modes for value in (QPrinter.DuplexAuto, QPrinter.DuplexLongSide, QPrinter.DuplexShortSide)):
                message = 'Doble cara disponible según el controlador. Borde largo: libro; borde corto: calendario.'
            else:
                message = 'El controlador no ofrece doble cara automática para esta impresora.'
            self.capability.setText(message)
        except Exception as exc:
            self._printer_error_v314 = str(exc)
            self._printer_available_v314 = False
            self.capability.setText('No se pudieron comprobar las opciones de esta impresora.')
        self._show_errors_v314()
        self._update_available_controls_v314()

    def _printer_changed_v311(self, *_):
        if self._profile_printer_v311:
            self._printer_drafts_v311[self._profile_printer_v311] = print_profile_v311(self.settings())
            self._driver_flags_v314[self._profile_printer_v311] = self._driver_layout_v314
        name = self.printer.currentData()
        self._profile_printer_v311 = name
        if self.duplex.findData(QPrinter.DuplexAuto) < 0:
            with QSignalBlocker(self.duplex):
                self.duplex.addItem('Según el controlador', QPrinter.DuplexAuto)
        profile = dict(DEFAULT_PRINT_SETTINGS_V311)
        self._native_printer_v314 = None
        self._properties_validated_v314 = False
        if name:
            try:
                device = self._native_devices_v314.get(name)
                if device is None:
                    device = _new_device_v314(name)
                    self._native_devices_v314[name] = device
                self._native_printer_v314 = device
                defaults = _defaults_v314(name, device)
                # Keep the existing resolution default/profile: quality
                # changes were explicitly excluded from this revision.
                defaults.pop('dpi', None)
                profile.update(defaults)
            except Exception:
                # Availability is reported by the capability query below. A
                # driver without readable defaults can still expose valid options.
                pass
        saved = self._printer_drafts_v311.get(name)
        if saved is None and self._printer_preferences_v311 is not None:
            saved = self._printer_preferences_v311.settings_for(name)
        if saved:
            profile.update(saved)
        self._driver_layout_v314 = bool(profile.get('driver_layout')) and not (
            saved and any(key in saved for key in ('paper', 'orientation')))
        if name in self._driver_flags_v314:
            self._driver_layout_v314 = self._driver_flags_v314[name]
        controls = (self.color, self.duplex, self.collate, self.scale,
                    self.orientation, self.paper, self.dpi)
        blockers = [QSignalBlocker(control) for control in controls]
        self._setting_profile_v314 = True
        try:
            self._apply_values_v314(profile)
            self.update_capabilities()
        finally:
            self._setting_profile_v314 = False
            for blocker in blockers:
                blocker.unblock()
        self._changed()

    def _apply_values_v314(self, values):
        def select(control, value):
            index = control.findData(value)
            if index >= 0:
                control.setCurrentIndex(index)
        if 'color' in values:
            select(self.color, QPrinter.ColorMode(getattr(values['color'], 'value', values['color'])))
        if 'duplex' in values:
            select(self.duplex, QPrinter.DuplexMode(getattr(values['duplex'], 'value', values['duplex'])))
        if 'collate' in values:
            self.collate.setChecked(values['collate'])
        if 'fit' in values:
            self.scale.setCurrentIndex(0 if values['fit'] else 1)
        if 'orientation' in values:
            self.orientation.setCurrentIndex(values['orientation'])
        if 'paper' in values:
            self.paper.setCurrentIndex(values['paper'])
        if 'dpi' in values:
            self.dpi.setValue(values['dpi'])

    def _changed(self, *_):
        if not hasattr(self, 'preview_timer') or self._preparing:
            return
        if not self._setting_profile_v314 and self.sender() in (self.paper, self.orientation):
            self._driver_layout_v314 = False
        if not self._setting_profile_v314 and self.sender() in (
                self.paper, self.orientation, self.color, self.duplex, self.copies, self.collate):
            self._properties_validated_v314 = False
        self.paper.setItemText(0, 'Papel configurado en el controlador' if
                               self._driver_layout_v314 and self.paper.currentIndex() == 0 else
                               'Tamaño de la primera página seleccionada')
        self.preview_invalidated.emit()
        self._range_error_v314 = ''
        try:
            numbers = self.selected_pages()
            with QSignalBlocker(self.page):
                self.page.setMaximum(len(numbers))
            number = numbers[self.page.value()-1]
            self.total.setText(f'/ {len(numbers)}')
            self.summary.setText(f'Página original {number+1} · {self.copies.value()} copia(s)')
            self.previous.setEnabled(self.page.value() > 1)
            self.following.setEnabled(self.page.value() < len(numbers))
            if self._preview_page is None or self._preview_page['page'] != number:
                self.mark_preview_pending(number)
            elif not self._printer_error_v314:
                self.redraw_preview(self.settings())
            if not self._printer_error_v314:
                self.preview_timer.start()
        except Exception as exc:
            self._range_error_v314 = str(exc)
            self.preview_timer.stop()
            self.placeholder.setText('Revisa el intervalo de páginas.')
            self.preview_stack.setCurrentWidget(self.placeholder)
        self._show_errors_v314()
        self._update_available_controls_v314()

    def mark_preview_pending(self, number):
        self.placeholder.setText(f'Actualizando vista preliminar de la página {number+1}…')
        self.preview_stack.setCurrentWidget(self.placeholder)

    def settings(self):
        settings = super().settings()
        settings['driver_layout'] = self._driver_layout_v314
        settings['properties_validated_v314'] = self._properties_validated_v314
        if self._sheet_anchor_v314 is not None:
            settings['sheet_page_v314'] = dict(self._sheet_anchor_v314)
        if self._native_printer_v314 is not None:
            settings['printer_device_v314'] = self._native_printer_v314
            if self._driver_layout_v314:
                settings['page_layout_v314'] = QPageLayout(self._native_printer_v314.pageLayout())
        return settings

    def set_sheet_plan_v314(self, anchor):
        self._sheet_anchor_v314 = dict(anchor) if anchor is not None else None

    def show_preview(self, page, settings):
        if self._sheet_anchor_v314 is None and page['page'] == self.selected_pages()[0]:
            self.set_sheet_plan_v314(page)
        return super().show_preview(page, self.settings())

    def redraw_preview(self, settings):
        if self._preview_image is None:
            return
        first = self.selected_pages()[0]
        if self._sheet_anchor_v314 is None or self._sheet_anchor_v314['page'] != first:
            self.mark_preview_pending(self.selected_pages()[self.page.value()-1])
            return
        settings = dict(settings, sheet_page_v314=dict(self._sheet_anchor_v314))
        device = self._native_printer_v314
        if device is not None and device.isValid():
            from .printing_device_v314 import apply_sheet_layout_v314
            if device.printerState() != QPrinter.Active:
                if device.resolution() != settings['dpi']:
                    device.setResolution(settings['dpi'])
                apply_sheet_layout_v314(device, self._preview_page, settings)
                settings['preview_sheet_layout_v314'] = QPageLayout(device.pageLayout())
        self._preview_settings = dict(settings, preview=True, copies=1, dpi=120)
        self.preview_printer.setOutputFormat(QPrinter.PdfFormat)
        self.preview_printer.setResolution(120)
        self.preview_printer.setFullPage(False)
        self.preview_printer.setColorMode(settings['color'])
        self.preview_stack.setCurrentWidget(self.preview)
        self.preview.updatePreview()
        self.preview.fitInView()

    def _paint_preview(self, printer):
        if self._preview_image is None or self._preview_settings is None:
            return
        from .printing_device_v314 import apply_sheet_layout_v314, paint_page_v314
        painter = QPainter()
        try:
            planned = self._preview_settings.get('preview_sheet_layout_v314')
            if isinstance(planned, QPageLayout):
                if not printer.setPageLayout(planned):
                    raise ValueError('No se pudo preparar el papel de la vista preliminar.')
            else:
                apply_sheet_layout_v314(printer, self._preview_page, self._preview_settings)
            if not painter.begin(printer):
                raise ValueError('No se pudo dibujar la vista preliminar.')
            image = self._preview_image
            if self._preview_settings['color'] == QPrinter.GrayScale:
                from PySide6.QtGui import QImage
                image = image.convertToFormat(QImage.Format_Grayscale8)
            paint_page_v314(painter, printer, image, self._preview_page,
                            self._preview_settings, fixed_sheet=True)
        except Exception as exc:
            self.error.setText(str(exc))
        finally:
            if painter.isActive():
                painter.end()

    def validate(self):
        if self._preparing or self._spooling or self._cancel_pending_v314:
            return
        wanted_duplex = self.duplex.currentData()
        self.update_capabilities()
        if wanted_duplex != self.duplex.currentData():
            self.error.setText('El controlador ha cambiado la opción de doble cara. '
                               'Revisa Caras antes de imprimir.')
            return
        if not self._printer_available_v314:
            return
        super().validate()

    def set_preparing(self, preparing):
        super().set_preparing(preparing)
        if hasattr(self, 'progress_v314'):
            self.progress_v314.setVisible(bool(preparing))
            if preparing:
                self.progress_v314.setRange(0, 0)
        self.cancel_button.setEnabled(not self._cancel_pending_v314)
        self._update_available_controls_v314()

    def set_spooling(self, spooling):
        self._spooling = bool(spooling)
        self.cancel_button.setEnabled(not self._cancel_pending_v314)
        self._update_available_controls_v314()

    def set_progress(self, done, total, phase='Preparando'):
        self.progress_v314.show()
        self.progress_v314.setRange(0, max(1, int(total)))
        self.progress_v314.setValue(max(0, min(int(done), int(total))))
        self.status.setText(f'{phase}: {done} de {total} página(s)…')

    def reject(self):
        self.preview_timer.stop()
        if self._cancel_finished_v314:
            return QDialog.reject(self)
        if self._preparing or self._spooling:
            if not self._cancel_pending_v314:
                self._cancel_pending_v314 = True
                self.cancel_button.setText('Cancelando…')
                self.cancel_button.setEnabled(False)
                self.status.setText('Deteniendo el trabajo de impresión…')
                self.cancel_requested.emit()
            return
        self.cancel_requested.emit()
        if not self._cancel_finished_v314:
            QDialog.reject(self)

    def finish_cancel(self):
        self._cancel_finished_v314 = True
        self._preparing = self._spooling = False
        self.preview_timer.stop()
        QDialog.reject(self)

    def closeEvent(self, event):
        event.ignore()
        self.reject()

    def _properties_dialog_v314(self, device):
        dialog = QPrintDialog(device, self)
        dialog.setWindowTitle('Configurar impresora y volver a PDFModder')
        for option in (QAbstractPrintDialog.PrintPageRange, QAbstractPrintDialog.PrintSelection,
                       QAbstractPrintDialog.PrintCurrentPage, QAbstractPrintDialog.PrintToFile):
            dialog.setOption(option, False)
        return dialog

    def _choose_properties_v314(self):
        if not self._printer_available_v314 or self._preparing or self._spooling:
            return
        name = self.printer.currentData()
        device = self._native_printer_v314 or _new_device_v314(name)
        try:
            from .printing_device_v314 import configure_printer_v314
            before = dict(_defaults_v314(name, device), layout=QPageLayout(device.pageLayout()),
                          copies=device.copyCount())
            configure_printer_v314(device, self.settings(), legacy.printer_capabilities_v201(name))
            if not self._driver_layout_v314 and self._preview_page is not None:
                from .printing_device_v314 import apply_sheet_layout_v314
                apply_sheet_layout_v314(device, self._preview_page, self.settings())
            dialog = self._properties_dialog_v314(device)
            if dialog.exec() != QDialog.Accepted:
                configure_printer_v314(device, dict(before, printer=name), None)
                device.setPageLayout(before['layout'])
                return
            selected_name = device.printerName()
            self._printer_drafts_v311[name] = print_profile_v311(super().settings())
            if selected_name != name:
                self._native_devices_v314.pop(name, None)
            index = self.printer.findData(selected_name)
            if index < 0:
                self.printer.addItem(selected_name, selected_name)
                index = self.printer.findData(selected_name)
            with QSignalBlocker(self.printer):
                self.printer.setCurrentIndex(index)
            self._profile_printer_v311 = selected_name
            self._native_devices_v314[selected_name] = device
            self._native_printer_v314 = device
            values = dict(_defaults_v314(selected_name, device), copies=device.copyCount())
            self._driver_layout_v314 = True
            self._properties_validated_v314 = True
            controls = (self.color, self.duplex, self.collate, self.scale,
                        self.orientation, self.paper, self.dpi, self.copies)
            blockers = [QSignalBlocker(control) for control in controls]
            try:
                self._apply_values_v314(values)
                self.copies.setValue(values.get('copies', self.copies.value()))
                self.update_capabilities()
            finally:
                for blocker in blockers:
                    blocker.unblock()
            self._changed()
        except Exception as exc:
            self._printer_error_v314 = str(exc)
            self._printer_available_v314 = False
            self._show_errors_v314()
            self._update_available_controls_v314()
