"""Local printer configuration and bounded preview; PDF rendering stays in worker."""
from PySide6.QtCore import QRectF,QSizeF,Signal,QEventLoop
from PySide6.QtGui import QAction,QImage,QPainter,QPageSize,QPageLayout
from PySide6.QtPrintSupport import QPrinter,QPrinterInfo,QPrintDialog,QPrintPreviewWidget
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,
    QLabel,QDialogButtonBox,QSpinBox,QCheckBox,QPushButton,QHBoxLayout,QApplication)
from .ui_icons_v170 import icon_v170


def print_target_v200(width_pt,height_pt,paint_rect,dpi,fit=True):
    """PDF points to device pixels, centered in the printable paper area."""
    width=width_pt/72.*dpi;height=height_pt/72.*dpi
    if fit:
        scale=min(paint_rect.width()/width,paint_rect.height()/height)
        width*=scale;height*=scale
    return QRectF(paint_rect.x()+(paint_rect.width()-width)/2.,
                  paint_rect.y()+(paint_rect.height()-height)/2.,width,height)


def select_print_pages_v201(scope,count,current,expression=''):
    from .pageops import parse_pages
    if scope=='all':return parse_pages('1-'+str(count),count)
    if scope=='current':
        if type(current) is not int or not 0<=current<count:raise ValueError('La página actual no existe.')
        return [current]
    if scope=='range':return parse_pages(expression,count)
    raise ValueError('Elige todas las páginas, la página actual o un intervalo.')


def printer_capabilities_v201(name):
    if not name:return {'duplex_modes':None,'color_modes':None}
    info=QPrinterInfo.printerInfo(name)
    if info.isNull():raise ValueError('La impresora seleccionada ya no está disponible.')
    return {'duplex_modes':info.supportedDuplexModes() or None,
            'color_modes':info.supportedColorModes() or None}


def configure_printer_v201(printer,settings,capabilities=None):
    modes=(capabilities or {}).get('duplex_modes')
    duplex=settings.get('duplex',QPrinter.DuplexNone)
    if duplex!=QPrinter.DuplexNone and modes is not None and duplex not in modes:
        raise ValueError('La impresora no admite la doble cara elegida. Selecciona una cara u otra impresora.')
    colors=(capabilities or {}).get('color_modes')
    color=settings.get('color',QPrinter.Color)
    if color==QPrinter.Color and colors is not None and color not in colors:
        raise ValueError('La impresora no admite color. Selecciona escala de grises.')
    if settings.get('printer'):printer.setPrinterName(settings['printer'])
    printer.setResolution(settings['dpi']);printer.setFullPage(False)
    printer.setColorMode(color);printer.setDuplex(duplex)
    printer.setCopyCount(settings.get('copies',1));printer.setCollateCopies(settings.get('collate',True))


def print_image_v201(path,color_mode):
    image=QImage(str(path))
    if image.isNull():raise RuntimeError('No se pudo leer una página preparada para imprimir.')
    if color_mode==QPrinter.GrayScale:image=image.convertToFormat(QImage.Format_Grayscale8)
    return image


def print_job_pages_v201(printer,pages):
    selected=list(pages)
    if printer.printRange()==QPrinter.PageRange:
        first,last=printer.fromPage(),printer.toPage()
        if not 1<=first<=last<=len(selected):raise ValueError('El intervalo de impresión no existe en la vista previa.')
        selected=selected[first-1:last]
    if printer.pageOrder()==QPrinter.LastPageFirst:selected.reverse()
    # A capable driver repeats the job. Never also duplicate its pages here.
    copies=1 if printer.supportsMultipleCopies() else max(1,printer.copyCount())
    if copies>1 and printer.duplex()!=QPrinter.DuplexNone:
        raise ValueError('Para doble cara, este controlador sólo permite una copia por trabajo. Imprime las copias en trabajos separados.')
    return selected*copies if printer.collateCopies() else [page for page in selected for _ in range(copies)]


def set_print_layout_v201(printer,page,settings):
    if settings.get('driver_layout'):return
    if settings['paper']==0:
        size=QPageSize(QSizeF(min(page['width'],page['height']),max(page['width'],page['height'])),QPageSize.Point)
    else:size=QPageSize({1:QPageSize.A4,2:QPageSize.A3,3:QPageSize.Letter}[settings['paper']])
    if not printer.setPageSize(size):raise RuntimeError('El controlador no acepta el tamaño de papel elegido.')
    orientation=settings['orientation']
    value=QPageLayout.Landscape if orientation==2 or (orientation==0 and page['width']>page['height']) else QPageLayout.Portrait
    if not printer.setPageOrientation(value):raise RuntimeError('El controlador no acepta la orientación elegida.')


class PrintOptionsV200(QDialog):
    def __init__(self,count,current,parent=None):
        super().__init__(parent);self.setWindowTitle('Imprimir / vista previa');self.setObjectName('printOptionsV200')
        layout=QVBoxLayout(self);form=QFormLayout();self.count=count;self.current=current
        self.printer=QComboBox();self.printer.setObjectName('printPrinterV201')
        names=QPrinterInfo.availablePrinterNames()
        for name in names:self.printer.addItem(name,name)
        if not names:self.printer.addItem('Vista previa (no hay impresoras disponibles)','')
        default=QPrinterInfo.defaultPrinterName()
        if default in names:self.printer.setCurrentIndex(names.index(default))
        form.addRow('Impresora',self.printer)
        self.color=QComboBox();self.color.setObjectName('printColorV201')
        self.color.addItem('Color',QPrinter.Color);self.color.addItem('Escala de grises',QPrinter.GrayScale);form.addRow('Color',self.color)
        self.duplex=QComboBox();self.duplex.setObjectName('printDuplexV201')
        self.duplex.addItem('Una cara',QPrinter.DuplexNone)
        self.duplex.addItem('Doble cara · borde largo (tipo libro)',QPrinter.DuplexLongSide)
        self.duplex.addItem('Doble cara · borde corto (tipo calendario)',QPrinter.DuplexShortSide);form.addRow('Caras',self.duplex)
        self.scope=QComboBox();self.scope.setObjectName('printScopeV201')
        self.scope.addItem('Todas las páginas','all');self.scope.addItem(f'Página actual ({current+1})','current');self.scope.addItem('Páginas concretas / intervalos','range');form.addRow('Imprimir',self.scope)
        self.pages=QLineEdit('1-'+str(count) if count>1 else '1');self.pages.setObjectName('printPagesV200')
        self.pages.setPlaceholderText('Ejemplo: 1,3-5');self.pages.setEnabled(False);form.addRow('Intervalos',self.pages)
        self.scope.currentIndexChanged.connect(lambda _:self.pages.setEnabled(self.scope.currentData()=='range'))
        self.copies=QSpinBox();self.copies.setRange(1,99);self.copies.setObjectName('printCopiesV201');form.addRow('Copias',self.copies)
        self.collate=QCheckBox('Agrupar cada copia completa');self.collate.setChecked(True);form.addRow('',self.collate)
        self.scale=QComboBox();self.scale.addItems(['Ajustar al área imprimible','Tamaño real (100%)']);form.addRow('Escala',self.scale)
        self.orientation=QComboBox();self.orientation.addItems(['Según cada página','Vertical','Horizontal']);form.addRow('Orientación',self.orientation)
        self.paper=QComboBox();self.paper.addItems(['Tamaño de cada página','A4','A3','Carta']);self.paper.setCurrentIndex(1);form.addRow('Papel',self.paper)
        self.dpi=QSpinBox();self.dpi.setRange(72,600);self.dpi.setValue(300);self.dpi.setSuffix(' ppp');form.addRow('Resolución',self.dpi);layout.addLayout(form)
        self.capability=QLabel();self.capability.setWordWrap(True);layout.addWidget(self.capability)
        note=QLabel('La vista previa muestra el color y el área imprimible. Tamaño real puede recortar contenido si el papel es menor. '
                    'Imprimir abre la confirmación de Windows y las propiedades del controlador. '
                    'Se imprime la apariencia renderizada; Guardar como conserva el PDF vectorial y seleccionable.')
        note.setWordWrap(True);layout.addWidget(note)
        self.error=QLabel();self.error.setWordWrap(True);layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.button(QDialogButtonBox.Ok).setText('Preparar vista previa');buttons.accepted.connect(self.validate);buttons.rejected.connect(self.reject)
        layout.addWidget(buttons);self.printer.currentIndexChanged.connect(self.update_capabilities);self.update_capabilities()

    def settings(self):
        return {'printer':self.printer.currentData(),'color':self.color.currentData(),'duplex':self.duplex.currentData(),
                'copies':self.copies.value(),'collate':self.collate.isChecked(),'fit':self.scale.currentIndex()==0,
                'orientation':self.orientation.currentIndex(),'paper':self.paper.currentIndex(),'dpi':self.dpi.value()}

    def update_capabilities(self,*args):
        try:
            caps=printer_capabilities_v201(self.printer.currentData())
            for index in (1,2):
                modes=caps['duplex_modes'];self.duplex.model().item(index).setEnabled(modes is None or self.duplex.itemData(index) in modes)
            if not self.duplex.model().item(self.duplex.currentIndex()).isEnabled():self.duplex.setCurrentIndex(0)
            modes=caps['color_modes'];self.color.model().item(0).setEnabled(modes is None or QPrinter.Color in modes)
            if not self.color.model().item(0).isEnabled():self.color.setCurrentIndex(1)
            known=caps['duplex_modes']
            self.capability.setText('Doble cara automática no disponible en esta impresora.' if known is not None and not any(v in known for v in (QPrinter.DuplexLongSide,QPrinter.DuplexShortSide)) else
                'La doble cara requiere una impresora y un controlador compatibles. Borde largo: tipo libro; borde corto: tipo calendario.')
        except Exception as exc:self.error.setText(str(exc))

    def validate(self):
        try:
            self.numbers=select_print_pages_v201(self.scope.currentData(),self.count,self.current,self.pages.text())
            caps=printer_capabilities_v201(self.printer.currentData());modes=caps['duplex_modes']
            if self.duplex.currentData()!=QPrinter.DuplexNone and modes is not None and self.duplex.currentData() not in modes:
                raise ValueError('La impresora no admite la doble cara elegida.')
        except Exception as exc:self.error.setText(str(exc));return
        self.accept()


class PrintPreviewV201(QDialog):
    print_requested=Signal()
    def __init__(self,printer,pages,settings,paint,parent=None):
        super().__init__(parent);self.setWindowTitle('Vista previa de impresión');self.setObjectName('printPreviewDialogV200');self.resize(1050,800)
        self.pages=pages;self.settings=settings;self.position=0
        layout=QVBoxLayout(self);bar=QHBoxLayout()
        previous=QPushButton('◀');previous.setToolTip('Página anterior');previous.clicked.connect(lambda:self.page.setValue(max(1,self.page.value()-1)));bar.addWidget(previous)
        self.page=QSpinBox();self.page.setObjectName('printPreviewPageV201');self.page.setRange(1,len(pages));bar.addWidget(self.page);bar.addWidget(QLabel(f'/ {len(pages)}'))
        following=QPushButton('▶');following.setToolTip('Página siguiente');following.clicked.connect(lambda:self.page.setValue(min(len(pages),self.page.value()+1)));bar.addWidget(following)
        self.preview=QPrintPreviewWidget(printer,self);self.preview.setObjectName('printPreviewWidgetV201')
        for title,slot in [('−',self.preview.zoomOut),('+',self.preview.zoomIn),('Ajustar página',self.preview.fitInView),('Ajustar anchura',self.preview.fitToWidth)]:
            button=QPushButton(title);button.clicked.connect(lambda _,fn=slot:fn());bar.addWidget(button)
        bar.addStretch();layout.addLayout(bar);self.summary=QLabel();layout.addWidget(self.summary);layout.addWidget(self.preview)
        self.preview.paintRequested.connect(lambda device:paint(device,[pages[self.position]],dict(settings,preview=True)))
        self.page.valueChanged.connect(self.change_page)
        buttons=QHBoxLayout();buttons.addStretch();self.print_button=QPushButton('Imprimir…');self.print_button.setObjectName('printConfirmV201')
        self.print_button.clicked.connect(self.print_requested);buttons.addWidget(self.print_button)
        close=QPushButton('Cerrar');close.clicked.connect(self.reject);buttons.addWidget(close);layout.addLayout(buttons)
        self.refresh_summary();self.preview.fitInView()

    def refresh_summary(self):
        gray=self.settings.get('color')==QPrinter.GrayScale
        self.summary.setText(f"Página original {self.pages[self.position]['page']+1} · {'Escala de grises' if gray else 'Color'} · "
                             f"{self.settings.get('copies',1)} copia(s). El intervalo final de Windows se refiere a estas {len(self.pages)} hojas seleccionadas.")

    def change_page(self,value):
        self.position=value-1;self.refresh_summary();self.preview.updatePreview()


class PrintingV200Mixin:
    def _init_printing_v200(self):
        self.print_action_v200=QAction('Imprimir / vista previa…',self);self.print_action_v200.setObjectName('printActionV200')
        self.print_action_v200.setIcon(icon_v170('print'));self.print_action_v200.setShortcut('Ctrl+P')
        self.print_action_v200.triggered.connect(self.choose_print_v200);self.toolbar.insertAction(self.sign_action,self.print_action_v200)

    def choose_print_v200(self):
        if not self.state or self.busy or self.state.get('preview'):return
        if self.canvas.editor.isVisible() or getattr(self,'_rich_loading',False):
            self._error('Acepta o cancela el texto que estás escribiendo antes de imprimir.');return
        options=PrintOptionsV200(self.state['page_count'],self.page_number,self)
        if self._exec_edit_dialog(options)!=QDialog.Accepted:return
        settings=options.settings()
        try:
            printer=QPrinter(QPrinter.HighResolution)
            if not settings['printer']:printer.setOutputFormat(QPrinter.PdfFormat)
            configure_printer_v201(printer,settings,printer_capabilities_v201(settings['printer']))
            if settings['printer'] and not printer.isValid():raise ValueError('La impresora seleccionada no está disponible.')
            printer.setDocName(self.state.get('path','PDF Modder'))
        except Exception as exc:self._error(str(exc));return
        def prepared(result):
            self._print_prepared_v200=result
            preview=PrintPreviewV201(printer,result['pages'],settings,self._paint_print_v200,self);self._print_dialog_v200=preview
            preview.print_requested.connect(lambda:self._confirm_print_v201(printer,result['pages'],settings,preview))
            actual=min(p['dpi'] for p in result['pages'])
            if actual<settings['dpi']-.1:self._notice(f'Resolución efectiva limitada a {actual:.1f} ppp por memoria o permisos del documento.')
            self._exec_edit_dialog(preview)
        self._submit('print_pages_v200',{'pages':options.numbers,'dpi':settings['dpi']},prepared)

    def _confirm_print_v201(self,printer,pages,settings,preview):
        try:self._execute_print_v201(printer,pages,settings,preview)
        except Exception as exc:self._error('No se pudo configurar la impresión: '+str(exc))

    def _execute_print_v201(self,printer,pages,settings,preview):
        if not QPrinterInfo.availablePrinterNames():
            self._error('No hay impresoras disponibles. Instala una impresora o Microsoft Print to PDF en Windows.');return
        if printer.outputFormat()!=QPrinter.NativeFormat:
            printer.setPrinterName(QPrinterInfo.defaultPrinterName() or QPrinterInfo.availablePrinterNames()[0]);printer.setOutputFormat(QPrinter.NativeFormat)
            configure_printer_v201(printer,dict(settings,printer=printer.printerName()))
        set_print_layout_v201(printer,pages[0],settings)
        size=printer.pageLayout().pageSize().sizePoints();before=(size.width(),size.height(),printer.pageLayout().orientation())
        printer.setPrintRange(QPrinter.AllPages)
        dialog=QPrintDialog(printer,preview);dialog.setWindowTitle('Confirmar impresión');dialog.setMinMax(1,len(pages));dialog.setFromTo(1,len(pages))
        if self._exec_edit_dialog(dialog)!=QDialog.Accepted:return
        size=printer.pageLayout().pageSize().sizePoints();after=(size.width(),size.height(),printer.pageLayout().orientation())
        changed=abs(before[0]-after[0])>.5 or abs(before[1]-after[1])>.5 or before[2]!=after[2]
        # Keep explicit driver changes rather than overriding them while painting.
        actual=dict(settings,driver_layout=changed,preview=False)
        preview.print_button.setEnabled(False)
        try:
            if self._paint_print_v200(printer,pages,actual):preview.accept()
        finally:preview.print_button.setEnabled(True)

    def _paint_print_v200(self,printer,pages,settings):
        painter=QPainter();ok=False
        try:
            selected=list(pages) if settings.get('preview') else print_job_pages_v201(printer,pages)
            for index,page in enumerate(selected):
                set_print_layout_v201(printer,page,settings)
                if index==0:
                    if not painter.begin(printer):raise RuntimeError('La impresora no permite iniciar el trabajo.')
                elif not printer.newPage():raise RuntimeError('La impresora no aceptó la siguiente página.')
                image=print_image_v201(page['path'],printer.colorMode());paint_rect=printer.pageLayout().paintRectPixels(printer.resolution())
                # Qt's painter origin already starts at the printable area.
                area=QRectF(0,0,paint_rect.width(),paint_rect.height())
                target=print_target_v200(page['width'],page['height'],area,printer.resolution(),settings['fit']);painter.drawImage(target,image);del image
                if printer.outputFormat()==QPrinter.NativeFormat and not settings.get('preview'):
                    # Keep Windows paint/dispatch alive between spooled pages,
                    # without allowing a second print action to re-enter.
                    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            ok=bool(selected)
        except Exception as exc:
            if painter.isActive():printer.abort()
            self._error('No se pudo imprimir: '+str(exc))
        finally:
            if painter.isActive() and not painter.end():ok=False;self._error('La impresora no pudo finalizar el trabajo.')
        return ok
