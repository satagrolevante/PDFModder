from pathlib import Path
from io import BytesIO
import tempfile
import pymupdf as fitz
import pytest
from PySide6.QtCore import QRectF
from pypdf import PdfReader

from pdfmodder.worker import Session
from pdfmodder.editor_tools_v200 import install_editor_tools_v200
from pdfmodder.printing_v200 import print_target_v200
from pdfmodder.model import EditError


def test_print_scale_real_size_fit_and_center():
    area=QRectF(0,0,2400,3300)
    actual=print_target_v200(612,792,area,300,False)
    assert actual.width()==2550 and actual.height()==3300
    assert actual.x()==-75 and actual.y()==0
    fitted=print_target_v200(612,792,area,300,True)
    assert fitted.width()==2400 and fitted.height()<3300
    assert fitted.y()>0


def test_print_prepare_ranges_rotation_and_original_unchanged():
    with tempfile.TemporaryDirectory(dir=Path('output')) as directory:
        root=Path(directory);source=root/'source.pdf'
        with fitz.open() as doc:
            doc.new_page(width=300,height=400).insert_text((30,50),'Primera')
            page=doc.new_page(width=300,height=400);page.insert_text((30,50),'Segunda');page.set_rotation(90)
            doc.save(source)
        initial=source.read_bytes();session=Session(source,reading=True,history_dir=root/'history')
        install_editor_tools_v200(Session)
        try:
            result=session.print_pages_v200([1],144)
            assert len(result['pages'])==1
            page=result['pages'][0]
            assert page['width']==400 and page['height']==300 and page['dpi']==144
            assert Path(page['path']).is_file()
            with fitz.open(page['path']) as image:
                assert image[0].get_pixmap().width>0
            assert session.history.index==0 and source.read_bytes()==initial
            assert PdfReader(BytesIO(initial)).pages[1].extract_text().strip()=='Segunda'
            with pytest.raises(EditError):session.print_pages_v200([3])
        finally:session.close()


def test_printer_preview_paints_landscape_and_portrait_pages(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage,QColor
    from PySide6.QtPrintSupport import QPrinter
    from pdfmodder.printing_v200 import PrintingV200Mixin
    app=QApplication.instance() or QApplication([])
    image=QImage(400,300,QImage.Format_RGB32);image.fill(QColor('white'))
    path=tmp_path/'page.png';assert image.save(str(path))
    class PrinterHarness(PrintingV200Mixin):
        errors=[]
        def _error(self,text):self.errors.append(text)
    printer=QPrinter(QPrinter.HighResolution);printer.setResolution(144)
    printer.setOutputFormat(QPrinter.PdfFormat);destination=tmp_path/'printer.pdf';printer.setOutputFileName(str(destination))
    harness=PrinterHarness()
    harness._paint_print_v200(printer,[{'path':str(path),'width':400,'height':300},
                                    {'path':str(path),'width':300,'height':400}],
                             {'fit':True,'orientation':0,'paper':0})
    assert not harness.errors
    with fitz.open(destination) as doc:
        assert len(doc)==2
        assert (doc[0].rect.width,doc[0].rect.height)==pytest.approx((400,300),abs=1)
        assert (doc[1].rect.width,doc[1].rect.height)==pytest.approx((300,400),abs=1)


def test_final_driver_layout_is_preserved(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage,QColor,QPageSize,QPageLayout
    from PySide6.QtPrintSupport import QPrinter
    from pdfmodder.printing_v200 import PrintingV200Mixin
    app=QApplication.instance() or QApplication([])
    image=QImage(100,100,QImage.Format_RGB32);image.fill(QColor('red'))
    path=tmp_path/'page.png';assert image.save(str(path))
    class Harness(PrintingV200Mixin):
        def __init__(self):self.errors=[]
        def _error(self,text):self.errors.append(text)
    printer=QPrinter(QPrinter.HighResolution);printer.setOutputFormat(QPrinter.PdfFormat)
    target=tmp_path/'driver.pdf';printer.setOutputFileName(str(target));printer.setResolution(144)
    assert printer.setPageSize(QPageSize(QPageSize.Letter))
    assert printer.setPageOrientation(QPageLayout.Landscape)
    printer.setColorMode(QPrinter.GrayScale)
    harness=Harness()
    assert harness._paint_print_v200(printer,[{'path':str(path),'width':300,'height':400}],
                                   {'fit':True,'orientation':1,'paper':1,'driver_layout':True})
    assert not harness.errors
    with fitz.open(target) as doc:
        assert len(doc)==1
        assert (doc[0].rect.width,doc[0].rect.height)==pytest.approx((792,612),abs=1)
        image=doc[0].get_pixmap()
        pixels=memoryview(image.samples)
        assert all(pixels[i]==pixels[i+1]==pixels[i+2] for i in range(0,len(pixels),3))
