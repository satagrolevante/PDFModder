"""Explorer printing uses fresh system defaults, with status in the main window."""
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from .printing_device_v314 import printer_defaults_v314


def system_default_printer_v320(document):
    info = QPrinterInfo.defaultPrinter()
    if info.isNull():
        raise ValueError('No hay una impresora predeterminada. Configúrala en Windows y vuelve a imprimir.')
    printer = QPrinter(info, QPrinter.HighResolution)
    name = info.printerName()
    if (not printer.isValid() or printer.printerName() != name
            or printer.outputFormat() != QPrinter.NativeFormat):
        raise ValueError('La impresora predeterminada no está disponible. Revisa su configuración en Windows.')
    # Read the new device; never apply a PDFModder profile or rewrite the native
    # layout, color, duplex, resolution, copies, tray or private driver settings.
    settings = printer_defaults_v314(name, printer)
    settings.update(copies=max(1, printer.copyCount()),
                    printer_device_v314=printer, preserve_driver_defaults_v320=True)
    printer.setDocName(Path(document).name)
    return settings


class _TextSinkV320:
    def __init__(self, callback):
        self.setText = callback


class DirectPrintStatusV320(QObject):
    """The shared print controller needs no option widgets or modal dialog."""
    def __init__(self, owner, settings, count):
        super().__init__(owner)
        self.owner = owner
        self._settings = settings
        self._pages = list(range(count))
        self.context = None
        self.preview_timer = QTimer(self)
        self.status = _TextSinkV320(lambda text: owner.statusBar().showMessage(text))
        self.error = _TextSinkV320(self._failed)

    def settings(self):
        return dict(self._settings)

    def selected_pages(self):
        return list(self._pages)

    def set_preparing(self, _value):
        pass

    def set_spooling(self, _value):
        pass

    def set_progress(self, current, total, phase):
        self.status.setText(f'{phase} · {current} de {total} · {self._settings["printer"]}')

    def accept(self):
        self.owner._close_print_context_v314(self.context)

    def finish_cancel(self):
        self.owner._close_print_context_v314(self.context)
        self.owner._notice('Envío de impresión detenido.')

    def _failed(self, message):
        # Disconnect this job's error listener before publishing the error.
        self.owner._close_print_context_v314(self.context)
        self.owner._error(message)
