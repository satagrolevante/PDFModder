"""Native active-paper restrictions and exact-job cancellation, without paper."""
import pytest
import pymupdf as fitz
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrinter
from pdfmodder.printing_device_v314 import PrintSpoolV314, apply_sheet_layout_v314, paint_page_v314
from pdfmodder.windows_print_job_v314 import WindowsPrintJobV314, check_windows_driver_settings_v314


class NativeLike(QPrinter):
    def __init__(self, path):
        super().__init__(QPrinter.HighResolution)
        self.setOutputFormat(QPrinter.PdfFormat)
        self.setOutputFileName(str(path))
        self.setResolution(72)
        self.size_calls = []
    def outputFormat(self): return QPrinter.NativeFormat
    def duplex(self): return QPrinter.DuplexLongSide
    def setPageSize(self, size):
        active = self.printerState() == QPrinter.Active
        self.size_calls.append(active)
        if active:
            raise AssertionError('Native paper cannot change during an active job')
        return super().setPageSize(size)


def pages(tmp_path):
    result = []
    for i, (w, h) in enumerate(((300, 450), (900, 500), (280, 420))):
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(0xffff0000 if i == 1 else 0xff0000ff)
        path = tmp_path/f'page-{i}.png'
        image.save(str(path))
        result.append({'page':i,'path':str(path),'width':float(w),'height':float(h),'dpi':72})
    return result


def settings():
    return {'printer':'','paper':1,'orientation':0,'fit':True,'color':QPrinter.Color,
            'duplex':QPrinter.DuplexLongSide,'copies':1,'collate':True,'dpi':72}


def test_native_multiple_pages_keep_one_sheet_and_exact_preview(qapp, tmp_path):
    prepared = pages(tmp_path)
    native = NativeLike(tmp_path/'native.pdf')
    options = dict(settings(), sheet_page_v314=prepared[0])
    writer = PrintSpoolV314(native, options)
    assert all(writer.push(page) for page in prepared)
    assert writer.finish()
    assert native.size_calls == [False]
    assert writer.rotations == [0, 90, 0]
    preview = QPrinter(QPrinter.HighResolution)
    preview.setOutputFormat(QPrinter.PdfFormat)
    preview.setOutputFileName(str(tmp_path/'preview.pdf'))
    preview.setResolution(72)
    apply_sheet_layout_v314(preview, prepared[1], options)
    painter = QPainter()
    assert painter.begin(preview)
    paint_page_v314(painter, preview, QImage(prepared[1]['path']), prepared[1], options)
    assert painter.end()
    with fitz.open(tmp_path/'native.pdf') as output, fitz.open(tmp_path/'preview.pdf') as view:
        assert len(output) == 3
        assert all(page.rect == output[0].rect for page in output)
        assert output[1].rect == view[0].rect
        assert output[1].get_pixmap().samples == view[0].get_pixmap().samples


def test_windows_cancellation_never_selects_another_document_or_reused_id():
    class Queue:
        rows = [{'id':1,'document':'other-document'}]
        cancelled = []
        def jobs(self, name): return [dict(row) for row in self.rows]
        def cancel(self, name, job_id, document):
            if not any(x['id'] == job_id and x['document'] == document for x in self.rows):
                return False
            self.cancelled.append((name,job_id,document));return True
    queue = Queue()
    tracker = WindowsPrintJobV314('Office','PDFModder-unique',api=queue)
    queue.rows += [{'id':2,'document':'PDFModder-unique'}, {'id':3,'document':'someone-else'}]
    assert tracker.observe() == 2
    assert tracker.cancel()
    assert queue.cancelled == [('Office',2,'PDFModder-unique')]
    queue.rows = [{'id':2,'document':'reused-by-another-user'}]
    assert not tracker.cancel()
    assert len(queue.cancelled) == 1


def test_driver_normalization_rejects_silent_simplex_fallback():
    effective = {'duplex':0,'color':1,'copies':1,'collate':True}
    with pytest.raises(ValueError, match='caras'):
        check_windows_driver_settings_v314('Office',settings(),normalizer=lambda *_:effective)
    effective['duplex'] = 2
    assert check_windows_driver_settings_v314('Office',settings(),normalizer=lambda *_:effective) == effective


def test_cancel_before_first_page_creates_no_job(qapp, tmp_path):
    printer = NativeLike(tmp_path/'cancelled.pdf')
    writer = PrintSpoolV314(printer, settings())
    assert writer.cancel()
    assert writer.cancel_status == 'cancelled'
    assert not writer.push(pages(tmp_path)[0])
    assert not (tmp_path/'cancelled.pdf').exists()


def test_native_devmode_normalization_uses_windows_offsets_and_keeps_private_data():
    import ctypes
    import struct
    from types import SimpleNamespace
    from pdfmodder.windows_print_job_v314 import normalize_windows_settings_v314
    size=236
    class Properties:
        def __call__(self, owner, handle, name, out, incoming, flags):
            if flags==0:return size
            if flags==2:
                raw=bytearray(size)
                struct.pack_into('<HHHHI',raw,64,0x401,1,220,16,0)
                raw[220:236]=b'vendor-data-1234'
                ctypes.memmove(out,bytes(raw),size)
            elif flags==10:
                raw=ctypes.string_at(incoming,size)
                assert struct.unpack_from('<h',raw,94)[0]==3  # dmDuplex
                assert struct.unpack_from('<h',raw,86)[0]==3  # dmCopies
                assert struct.unpack_from('<h',raw,92)[0]==1  # dmColor, grayscale
                assert struct.unpack_from('<h',raw,100)[0]==1  # dmCollate
                assert raw[220:236]==b'vendor-data-1234'
                ctypes.memmove(out,raw,size)
            else:raise AssertionError(flags)
            return 1
    api=SimpleNamespace(_open=lambda name:object(),dll=SimpleNamespace(
        DocumentPropertiesW=Properties(),ClosePrinter=lambda handle:None))
    result=normalize_windows_settings_v314('Office',dict(settings(),duplex=QPrinter.DuplexShortSide,
                                                       copies=3,color=QPrinter.GrayScale),api=api)
    assert result['duplex']==3 and result['copies']==3 and result['color']==0


def test_duplex_auto_is_reapplied_after_first_landscape_sheet(qapp,tmp_path):
    class AutoPrinter(NativeLike):
        def setDuplex(self,mode):
            self.negotiated_orientation=self.pageLayout().orientation()
    printer=AutoPrinter(tmp_path/'auto.pdf')
    prepared=pages(tmp_path)
    options=dict(settings(),duplex=QPrinter.DuplexAuto,sheet_page_v314=prepared[1])
    writer=PrintSpoolV314(printer,options)
    assert writer.push(prepared[1]) and writer.finish()
    from PySide6.QtGui import QPageLayout
    assert printer.negotiated_orientation==QPageLayout.Landscape
