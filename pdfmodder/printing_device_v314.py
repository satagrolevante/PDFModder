"""Negotiated printer options and incremental pages on one native print job."""
from __future__ import annotations

from math import isfinite
import os
import uuid

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter

from .printing_v201 import print_image_v201, print_target_v200, set_print_layout_v201
from .windows_print_job_v314 import WindowsPrintJobV314


def printer_defaults_v314(name, printer=None):
    """Read queue defaults without changing Windows' global printer preferences."""
    device = printer
    if device is None:
        device = QPrinter(QPrinter.HighResolution)
        device.setOutputFormat(QPrinter.NativeFormat)
        if device.printerName() != name:
            device.setPrinterName(name)
    if name and (not device.isValid() or device.printerName() != name):
        raise ValueError('La impresora seleccionada no está disponible.')
    layout = QPageLayout(device.pageLayout())
    paper = {QPageSize.A4: 1, QPageSize.A3: 2, QPageSize.Letter: 3}.get(layout.pageSize().id(), 0)
    return {'printer': name, 'color': device.colorMode(), 'duplex': device.duplex(),
            'dpi': max(72, min(600, device.resolution())), 'copies': 1,
            'collate': device.collateCopies(), 'fit': True,
            'orientation': 2 if layout.orientation() == QPageLayout.Landscape else 1,
            'paper': paper, 'driver_layout': True, 'page_layout_v314': layout}


def default_printer_settings_v314(name, printer=None):
    return printer_defaults_v314(name, printer=printer)


def validate_printer_settings_v314(printer, settings, capabilities=None):
    """Reject a silent simplex/color/copy fallback; getters are not paper proof."""
    if printer.outputFormat() != QPrinter.NativeFormat:
        return
    expected_name = settings.get('printer')
    if not printer.isValid() or (expected_name and printer.printerName() != expected_name):
        raise ValueError('La impresora seleccionada no está disponible.')
    requested_duplex = settings.get('duplex', QPrinter.DuplexNone)
    allowed = (capabilities or {}).get('duplex_modes')
    if allowed is not None and requested_duplex not in allowed:
        raise ValueError('El controlador no admite la opción de caras elegida.')
    effective = printer.duplex()
    if requested_duplex != QPrinter.DuplexAuto and effective != requested_duplex:
        raise ValueError('El controlador no ha aceptado la opción de caras elegida; '
                         'revisa las propiedades de la impresora.')
    requested_color = settings.get('color', QPrinter.Color)
    if printer.colorMode() != requested_color:
        raise ValueError('El controlador no ha aceptado la opción de color elegida.')
    if printer.copyCount() != int(settings.get('copies', 1)):
        raise ValueError('El controlador no ha aceptado el número de copias elegido.')
    if int(settings.get('copies', 1)) > 1 and printer.collateCopies() != bool(settings.get('collate', True)):
        raise ValueError('El controlador no ha aceptado la agrupación de copias elegida.')


def configure_printer_v314(printer, settings, capabilities=None):
    """Apply changes only, retaining private settings from optional properties."""
    modes = (capabilities or {}).get('duplex_modes')
    duplex = settings.get('duplex', QPrinter.DuplexNone)
    if modes is not None and duplex not in modes:
        raise ValueError('La impresora no admite la opción de caras elegida.')
    colors = (capabilities or {}).get('color_modes')
    color = settings.get('color', QPrinter.Color)
    if colors is not None and color not in colors:
        raise ValueError('La impresora no admite la opción de color elegida.')
    if settings.get('printer') and printer.printerName() != settings['printer']:
        printer.setPrinterName(settings['printer'])
    layout = settings.get('page_layout_v314')
    if settings.get('driver_layout') and isinstance(layout, QPageLayout):
        if not printer.pageLayout().isEquivalentTo(layout) and not printer.setPageLayout(layout):
            raise ValueError('El controlador no ha aceptado el papel y los márgenes elegidos.')
    for getter, setter, value in (
        ('resolution', 'setResolution', int(settings['dpi'])),
        ('fullPage', 'setFullPage', False),
        ('colorMode', 'setColorMode', color),
        ('duplex', 'setDuplex', duplex),
        ('copyCount', 'setCopyCount', int(settings.get('copies', 1))),
        ('collateCopies', 'setCollateCopies', bool(settings.get('collate', True))),
    ):
        if getattr(printer, getter)() != value:
            getattr(printer, setter)(value)
    validate_printer_settings_v314(printer, settings, capabilities)
    if (printer.outputFormat() == QPrinter.NativeFormat and os.name == 'nt'
            and not settings.get('properties_validated_v314')):
        from .windows_print_job_v314 import check_windows_driver_settings_v314
        check_windows_driver_settings_v314(printer.printerName(), settings)
    return printer


def apply_sheet_layout_v314(printer, page, settings):
    """Use the first selected page as the common native/preview sheet anchor."""
    if settings.get('driver_layout') and isinstance(settings.get('page_layout_v314'), QPageLayout):
        if not printer.pageLayout().isEquivalentTo(settings['page_layout_v314']):
            if not printer.setPageLayout(settings['page_layout_v314']):
                raise ValueError('El controlador no ha aceptado la disposición de la hoja.')
    else:
        set_print_layout_v201(printer, settings.get('sheet_page_v314') or page, settings)


def paint_page_v314(painter, printer, image, page, settings, *, fixed_sheet=True):
    """Share scaling and rotation between native output and its preview."""
    width, height = float(page['width']), float(page['height'])
    rect = printer.pageLayout().paintRectPixels(printer.resolution())
    area = QRectF(0, 0, rect.width(), rect.height())
    rotate = False
    if fixed_sheet and settings.get('orientation', 0) == 0 and settings.get('fit', True):
        straight = min(area.width()/width, area.height()/height)
        turned = min(area.width()/height, area.height()/width)
        rotate = turned > straight + .000001
    target = print_target_v200(height if rotate else width, width if rotate else height,
                               area, printer.resolution(), settings.get('fit', True))
    if rotate:
        painter.save()
        painter.translate(target.center())
        painter.rotate(90.)
        painter.drawImage(QRectF(-target.height()/2., -target.width()/2.,
                                 target.height(), target.width()), image)
        painter.restore()
    else:
        painter.drawImage(target, image)
    return 90 if rotate else 0


class PrintSpoolV314:
    """Paint successive prepared pages without reconfiguring active native paper.

    The GUI calls push once per prepared page, returning to its event loop
    between calls. Copies/order have already been planned by the controller.
    Software PDF output can retain each source page's layout for compatibility.
    """

    def __init__(self, printer, settings, error_callback=None, *, native=None,
                 tracker_factory=None):
        self.printer = printer
        self.settings = dict(settings)
        self.error_callback = error_callback
        self.native = printer.outputFormat() == QPrinter.NativeFormat if native is None else bool(native)
        self.painter = QPainter()
        self.pages_sent = 0
        self.rotations = []
        self.error = ''
        self.finished = False
        self.cancelled = False
        self.cancel_status = ''
        self.cancel_error = ''
        self._tracker = None
        self._tracker_factory = tracker_factory or WindowsPrintJobV314
        self._original_doc_name = printer.docName()
        self._document_token = 'PDFModder-' + uuid.uuid4().hex + ' ' + self._original_doc_name[:100]
        if self.native:
            # The token is first so a driver's truncated job name still cannot
            # accidentally match another user's document title.
            self.printer.setDocName(self._document_token)

    def _fail(self, message):
        self.error = str(message)
        self.cancel()
        if self.error_callback is not None:
            self.error_callback(self.error)
        return False

    def _start(self, page):
        apply_sheet_layout_v314(self.printer, page, self.settings)
        if self.native and self.settings.get('duplex') == QPrinter.DuplexAuto:
            self.printer.setDuplex(QPrinter.DuplexAuto)
        validate_printer_settings_v314(self.printer, self.settings)
        if self.native and (os.name == 'nt' or self._tracker_factory is not WindowsPrintJobV314):
            try:
                self._tracker = self._tracker_factory(self.printer.printerName(), self._document_token)
            except OSError as exc:
                self.cancel_error = 'No se pudo consultar la cola de Windows: ' + str(exc)
        if not self.painter.begin(self.printer):
            raise RuntimeError('La impresora no permite iniciar el trabajo.')
        if self._tracker is not None:
            try:
                self._tracker.observe()
            except OSError as exc:
                self.cancel_error = 'No se pudo identificar el trabajo en la cola: ' + str(exc)

    def push(self, page):
        if self.finished or self.cancelled or self.error:
            return False
        try:
            width, height = float(page['width']), float(page['height'])
            if not all(isfinite(v) and v > 0 for v in (width, height)):
                raise ValueError('La página preparada tiene dimensiones no válidas.')
            # Decode before opening/advancing the job so a missing image cannot
            # create a blank front or back page.
            image = print_image_v201(page['path'], self.printer.colorMode())
            if not self.painter.isActive():
                self._start(page)
            else:
                if not self.native:
                    set_print_layout_v201(self.printer, page, self.settings)
                if not self.printer.newPage():
                    raise RuntimeError('La impresora no aceptó la siguiente página.')
            rotation = paint_page_v314(self.painter, self.printer, image, page,
                                       self.settings, fixed_sheet=self.native)
            self.pages_sent += 1
            self.rotations.append(rotation)
            if self._tracker is not None:
                try:
                    self._tracker.observe()
                except OSError as exc:
                    self.cancel_error = 'No se pudo consultar el trabajo en la cola: ' + str(exc)
            return True
        except Exception as exc:
            return self._fail('No se pudo imprimir: ' + str(exc))

    def finish(self):
        if self.finished:
            return not self.cancelled and not self.error and self.pages_sent > 0
        if self.cancelled or self.error:
            return False
        if not self.painter.isActive() or not self.pages_sent:
            self.finished = True
            return False
        ok = self.painter.end()
        self.finished = True
        if not ok or self.printer.printerState() in (QPrinter.Error, QPrinter.Aborted):
            self.error = 'La impresora no pudo finalizar el trabajo.'
            if self.error_callback is not None:
                self.error_callback(self.error)
            return False
        return True

    def cancel(self):
        if self.finished and not self.cancelled and not self.error:
            self.cancel_status = 'finished'
            return False
        self.cancelled = True
        active = self.painter.isActive()
        queue_cancelled = False
        native_job = self.native and (active or self.pages_sent > 0)
        if native_job and self._tracker is not None:
            queue_cancelled = self._tracker.cancel()
        if active:
            self.printer.abort()
            # Qt Windows abort is not implemented. Finalize resources and then
            # repeat the exact-job cancellation in case the job appeared late.
            self.painter.end()
        if native_job and self._tracker is not None and not queue_cancelled:
            queue_cancelled = self._tracker.cancel()
        self.finished = True
        if not native_job:
            self.cancel_status = 'cancelled'
            return True
        if queue_cancelled:
            self.cancel_status = 'cancelled'
            return True
        self.cancel_status = 'unverified'
        if self._tracker is not None:
            self.cancel_error = self._tracker.error
        if not self.cancel_error:
            self.cancel_error = 'No se pudo confirmar la retirada del trabajo de la cola de Windows.'
        return False
