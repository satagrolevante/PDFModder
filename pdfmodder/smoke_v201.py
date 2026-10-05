"""Native UI printing acceptance; never submits a physical print job."""
from pathlib import Path
from pypdf import PdfReader
from PIL import ImageChops
from PySide6.QtPrintSupport import QPrinter
from .smoke_v200 import SmokeV200
from .printing_v201 import PrintOptionsV200,PrintPreviewV201,configure_printer_v201


class SmokeV201(SmokeV200):
    def finish(self,error=None,terminate=False):
        if error is None and self.stage=='complete' and not getattr(self,'_printing_started',False):
            self._printing_started=True;self.stage='print_options'
            self.options=PrintOptionsV200(self.page_count,1,self.window);self.options.show()
            return
        super().finish(error,terminate)

    def _next(self):
        if self.stage=='print_options':
            options=self.options
            self._require(options.printer.count()>0 and options.color.count()==2 and options.duplex.count()==3,
                          'Faltan controles de impresora, color o doble cara.')
            options.scope.setCurrentIndex(options.scope.findData('current'));options.validate()
            self._require(options.numbers==[1],'Página actual no selecciona la página 2.')
            options.scope.setCurrentIndex(options.scope.findData('range'));options.pages.setText('2,1')
            options.color.setCurrentIndex(options.color.findData(QPrinter.GrayScale));options.dpi.setValue(144)
            options.show();self._require(options.grab().save(str(self.report_path.with_name(self.report_path.stem+'-opciones.png'))),'Falta captura de opciones.')
            options.validate();self._require(options.numbers==[1,0],'Se cambió el orden de las páginas elegidas.')
            self.print_settings=dict(options.settings(),printer='',duplex=QPrinter.DuplexNone,copies=1)
            self._step('opciones_impresion_visibles',current_page=2,selected_original_pages=[2,1],color='grayscale',physical_job=False)
            self.stage='print_prepare'
            self.window._submit('print_pages_v200',{'pages':options.numbers,'dpi':144},self.prepared_print)
            return
        if self.stage=='print_prepare':return
        if self.stage=='print_preview_first':
            if self.preview.preview.pageCount()!=1:return
            self._require(len(self.print_pages)==2 and self.preview.position==0,'La vista previa no está paginada.')
            self._step('vista_previa_una_pagina',original_page=2,cached_preview_pages=1)
            self.stage='print_preview_second';self.preview.page.setValue(2);return
        if self.stage=='print_preview_second':
            self._require(self.preview.position==1 and self.preview.preview.pageCount()==1,'Cambiar de página acumuló páginas de vista previa.')
            self._require('original 1' in self.preview.summary.text(),'La vista previa no identifica la página original.')
            self._require(self.preview.grab().save(str(self.report_path.with_name(self.report_path.stem+'-impresion.png'))),'Falta captura de vista previa.')
            self.preview.reject()
            self._require(self.window.state['history_index']==1 and not self.window.state['dirty'],'Cancelar impresión modificó el documento.')
            self._step('navegar_y_cancelar_impresion',original_page=1,document_unchanged=True)
            printer=QPrinter(QPrinter.HighResolution);printer.setOutputFormat(QPrinter.PdfFormat)
            target=self.report_path.with_name(self.report_path.stem+'-impresion.pdf');printer.setOutputFileName(str(target))
            configure_printer_v201(printer,self.print_settings)
            self._require(self.window._paint_print_v200(printer,self.print_pages,self.print_settings),'Falló el dispositivo PDF de impresión.')
            independent=PdfReader(target)
            self._require(len(independent.pages)==2,'Se imprimió otro número de páginas.')
            image_count=0
            for page in independent.pages:
                for image in page.images:
                    rgb=image.image.convert('RGB');r,g,b=rgb.split()
                    self._require(ImageChops.difference(r,g).getbbox() is None and ImageChops.difference(g,b).getbbox() is None,'La salida en grises conserva colores.')
                    image_count+=1
            self._require(image_count>=2,'No se pudo contrastar la imagen impresa de cada página.')
            self._step('impresion_pdf_grises_verificada',pages=2,images_checked=image_count,physical_job=False)
            self.stage='complete';self.finish();return
        super()._next()

    def prepared_print(self,result):
        self.print_pages=result['pages']
        printer=QPrinter(QPrinter.HighResolution);printer.setOutputFormat(QPrinter.PdfFormat)
        configure_printer_v201(printer,self.print_settings);self.preview_printer=printer
        self.preview=PrintPreviewV201(printer,self.print_pages,self.print_settings,self.window._paint_print_v200,self.window)
        self.stage='print_preview_first';self.preview.show();self.preview.preview.updatePreview()
