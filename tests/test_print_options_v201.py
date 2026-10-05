"""Printing settings and output preparation, without a GUI or physical printer."""
import hashlib

import pytest
from PySide6.QtGui import QColor,QImage
from PySide6.QtPrintSupport import QPrinter

from pdfmodder.model import EditError
from pdfmodder.printing_v200 import (configure_printer_v201,print_image_v201,
    print_job_pages_v201,select_print_pages_v201)


class FakePrinter:
    def __init__(self,*,native_copies=True,collate=True,copies=1,
                 print_range=QPrinter.AllPages,first=0,last=0,
                 order=QPrinter.FirstPageFirst,duplex=QPrinter.DuplexNone):
        self.name='';self.dpi=0;self.color=QPrinter.Color;self.duplex_mode=duplex
        self.copies=copies;self.collated=collate;self.native_copies=native_copies
        self.range=print_range;self.first=first;self.last=last;self.order=order
        self.full_page=True

    def setPrinterName(self,value):self.name=value
    def printerName(self):return self.name
    def setResolution(self,value):self.dpi=value
    def resolution(self):return self.dpi
    def setFullPage(self,value):self.full_page=value
    def setColorMode(self,value):self.color=value
    def colorMode(self):return self.color
    def setDuplex(self,value):self.duplex_mode=value
    def duplex(self):return self.duplex_mode
    def setCopyCount(self,value):self.copies=value
    def copyCount(self):return self.copies
    def setCollateCopies(self,value):self.collated=value
    def collateCopies(self):return self.collated
    def supportsMultipleCopies(self):return self.native_copies
    def printRange(self):return self.range
    def fromPage(self):return self.first
    def toPage(self):return self.last
    def pageOrder(self):return self.order


@pytest.mark.parametrize('scope,current,expression,expected',[
    ('all',3,'',[0,1,2,3,4,5]),
    ('current',3,'',[3]),
    ('range',3,'5,2-3,2',[4,1,2]),
])
def test_page_scope_keeps_exact_requested_original_pages(scope,current,expression,expected):
    assert select_print_pages_v201(scope,6,current,expression)==expected


@pytest.mark.parametrize('expression',['0','7','4-2','texto',''])
def test_invalid_page_range_never_prepares_a_job(expression):
    with pytest.raises((ValueError,EditError)):
        select_print_pages_v201('range',6,0,expression)


def test_print_image_gray_is_real_and_source_file_is_unchanged(tmp_path):
    image=QImage(3,1,QImage.Format_RGB32)
    for x,color in enumerate(('red','lime','blue')):image.setPixelColor(x,0,QColor(color))
    path=tmp_path/'colores.png';assert image.save(str(path))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    color=print_image_v201(str(path),QPrinter.Color)
    gray=print_image_v201(str(path),QPrinter.GrayScale)
    assert not color.isNull() and not gray.isNull()
    assert (color.width(),color.height())==(3,1)==(gray.width(),gray.height())
    assert gray.format()==QImage.Format_Grayscale8
    levels=[]
    for x in range(3):
        assert color.pixelColor(x,0)==image.pixelColor(x,0)
        pixel=gray.pixelColor(x,0)
        assert pixel.red()==pixel.green()==pixel.blue()
        levels.append(pixel.red())
    assert levels[1]>levels[0]>levels[2]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('color,duplex',[
    (QPrinter.Color,QPrinter.DuplexNone),
    (QPrinter.GrayScale,QPrinter.DuplexLongSide),
    (QPrinter.Color,QPrinter.DuplexShortSide),
])
def test_configure_exact_color_duplex_copies_and_printer(color,duplex):
    printer=FakePrinter()
    settings={'printer':'Impresora de oficina','dpi':300,'color':color,
              'duplex':duplex,'copies':3,'collate':False}
    capabilities={'duplex_modes':[QPrinter.DuplexNone,QPrinter.DuplexLongSide,QPrinter.DuplexShortSide]}
    assert configure_printer_v201(printer,settings,capabilities) is None
    assert printer.printerName()=='Impresora de oficina' and printer.resolution()==300
    assert printer.colorMode()==color and printer.duplex()==duplex
    assert printer.copyCount()==3 and printer.collateCopies() is False
    assert printer.full_page is False


@pytest.mark.parametrize('duplex',[QPrinter.DuplexLongSide,QPrinter.DuplexShortSide])
def test_known_simplex_only_printer_rejects_duplex_explicitly(duplex):
    settings={'printer':'Sólo una cara','dpi':144,'color':QPrinter.GrayScale,
              'duplex':duplex,'copies':1,'collate':True}
    with pytest.raises(ValueError,match=r'(?i)(dúplex|duplex|doble cara)'):
        configure_printer_v201(FakePrinter(),settings,{'duplex_modes':[QPrinter.DuplexNone]})


def test_unknown_capabilities_pass_requested_duplex_to_driver():
    printer=FakePrinter()
    settings={'printer':'Controlador sin inventario','dpi':144,'color':QPrinter.Color,
              'duplex':QPrinter.DuplexLongSide,'copies':1,'collate':True}
    configure_printer_v201(printer,settings,None)
    assert printer.duplex()==QPrinter.DuplexLongSide


def test_known_monochrome_printer_rejects_color_explicitly():
    printer=FakePrinter()
    settings={'printer':'Monocromo','dpi':144,'color':QPrinter.Color,
              'duplex':QPrinter.DuplexNone,'copies':1,'collate':True}
    with pytest.raises(ValueError,match=r'(?i)(color|grises)'):
        configure_printer_v201(printer,settings,{'color_modes':[QPrinter.GrayScale]})


def test_preview_sheet_range_and_reverse_order_are_applied_once():
    pages=[{'page':1},{'page':5},{'page':8},{'page':11}]
    printer=FakePrinter(print_range=QPrinter.PageRange,first=2,last=3,order=QPrinter.LastPageFirst)
    assert [p['page'] for p in print_job_pages_v201(printer,pages)]==[8,5]
    assert pages==[{'page':1},{'page':5},{'page':8},{'page':11}]


@pytest.mark.parametrize('first,last',[(0,2),(2,4)])
def test_native_dialog_range_outside_prepared_sheets_is_rejected(first,last):
    printer=FakePrinter(print_range=QPrinter.PageRange,first=first,last=last)
    with pytest.raises(ValueError,match=r'(?i)(intervalo|página|hoja)'):
        print_job_pages_v201(printer,[{'page':1},{'page':5},{'page':8}])


@pytest.mark.parametrize('native,collate,expected',[
    (True,True,[2,7]),
    (False,True,[2,7,2,7]),
    (False,False,[2,2,7,7]),
])
def test_manual_copies_only_when_driver_does_not_handle_them(native,collate,expected):
    pages=[{'page':2},{'page':7}]
    printer=FakePrinter(native_copies=native,copies=2,collate=collate)
    assert [p['page'] for p in print_job_pages_v201(printer,pages)]==expected


@pytest.mark.parametrize('duplex',[QPrinter.DuplexLongSide,QPrinter.DuplexShortSide])
def test_duplex_multiple_copies_require_driver_support_for_copies(duplex):
    pages=[{'page':0},{'page':1},{'page':2}]
    manual=FakePrinter(native_copies=False,copies=2,duplex=duplex)
    with pytest.raises(ValueError,match=r'(?i)una copia por trabajo'):
        print_job_pages_v201(manual,pages)
    native=FakePrinter(native_copies=True,copies=2,duplex=duplex)
    assert print_job_pages_v201(native,pages)==pages
