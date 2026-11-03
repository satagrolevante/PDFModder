"""The printer is exclusively owned by one cancellable background sender."""
import threading
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtPrintSupport import QPrinter

from pdfmodder.printing_background_v318 import BackgroundPrintSpoolV318
from pdfmodder.worker import Session
from pdfmodder.editor_tools_v200 import install_editor_tools_v200


def test_sender_keeps_event_loop_alive_and_confirms_exact_job_cancel(qtbot, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    gui_thread = threading.get_ident()
    class SlowSpool:
        def __init__(self, printer, settings):
            self.settings = settings; self.error = ''; self.finished = False
            calls.append(('init', threading.get_ident()))
        def push(self, page):
            calls.append(('push', threading.get_ident()))
            entered.set()
            assert release.wait(5)
            return True
        def cancel(self):
            calls.append(('cancel', threading.get_ident()))
            self.finished = True
            return True
    background = BackgroundPrintSpoolV318(object(), {}, factory=SlowSpool)
    ticks = []
    timer = QTimer(); timer.setInterval(5); timer.timeout.connect(lambda: ticks.append(1)); timer.start()
    try:
        assert background.push({'page': 0, 'path': str(tmp_path/'external.png'), 'dpi': 72})
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        background.cancel()
        assert background.alive, 'Cancellation request must not pretend a blocked driver has finished'
        release.set()
        qtbot.waitUntil(lambda: not background.alive)
        records = background.poll()
        assert records == [{'kind':'cancel', 'ok': True, 'error': ''}]
        assert {thread for _, thread in calls}.isdisjoint({gui_thread})
        assert len({thread for _, thread in calls}) == 1
        assert [kind for kind, _ in calls] == ['init', 'push', 'cancel']
    finally:
        timer.stop(); release.set(); background.cancel()


def test_real_pdf_sender_keeps_page_geometry_and_order(qtbot, tmp_path):
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(tmp_path/'printed.pdf'))
    printer.setResolution(72)
    options = {'dpi':72,'color':QPrinter.Color,'duplex':QPrinter.DuplexNone,
               'copies':1,'collate':True,'fit':True,'paper':0,'orientation':0}
    background = BackgroundPrintSpoolV318(printer, options)
    for number, (width,height,color) in enumerate(((120,180,0xffcc0000),(240,100,0xff0000cc))):
        path=tmp_path/f'{number}.ppm'
        image=QImage(width,height,QImage.Format_RGB888);image.fill(color);assert image.save(str(path),'PPM')
        assert background.push({'page':number,'path':str(path),'width':width,'height':height,'dpi':72})
        records=[]
        def ready():
            records.extend(background.poll())
            return bool(records)
        qtbot.waitUntil(ready)
        assert records[0]['kind']=='push' and records[0]['ok']
    assert background.finish()
    qtbot.waitUntil(lambda: not background.alive)
    assert background.poll()==[{'kind':'finish','ok':True,'error':''}]
    with fitz.open(tmp_path/'printed.pdf') as document:
        assert document.page_count == 2
        assert [(round(page.rect.width),round(page.rect.height)) for page in document] == [(120,180),(240,100)]
        assert max(abs(a-b) for a,b in zip(document[0].get_pixmap().pixel(60,90),(204,0,0))) <= 2
        assert max(abs(a-b) for a,b in zip(document[1].get_pixmap().pixel(120,50),(0,0,204))) <= 2


def test_raw_transport_is_lossless_and_reader_is_reused_only_for_same_revision(tmp_path):
    install_editor_tools_v200(Session)
    path=tmp_path/'source.pdf'
    with fitz.open() as doc:
        page=doc.new_page(width=180,height=240)
        page.insert_text((20,50),'Printed content')
        doc.new_page(width=200,height=180)
        doc.save(path)
    session=Session(path,reading=True,history_dir=tmp_path/'history')
    try:
        original=session.history.current
        png=session.print_pages_v200([0],72)
        expected=fitz.Pixmap(png['pages'][0]['path']).samples
        context=session._print_context_v318
        raw=session.print_pages_v200([0],72,raw_rgb=True)
        assert raw['pages'][0]['path'].endswith('.ppm')
        assert fitz.Pixmap(raw['pages'][0]['path']).samples == expected
        assert session._print_context_v318 is context
        assert context.prepared_pages=={0}
        session.print_pages_v200([1],72,raw_rgb=True)
        assert session._print_context_v318 is context and context.prepared_pages=={0,1}
        assert session.history.current==original and path.read_bytes()==original
    finally:
        session.close()
    assert context.document.is_closed


def test_cancel_before_first_page_waits_for_printer_owner_to_finish(qtbot):
    entered=threading.Event();release=threading.Event();cancelled=[]
    class StartingSpool:
        def __init__(self, printer, settings):
            entered.set();assert release.wait(5)
            self.finished=False
        def cancel(self):
            cancelled.append(threading.get_ident());self.finished=True;return True
    background=BackgroundPrintSpoolV318(object(),{},factory=StartingSpool)
    qtbot.waitUntil(entered.is_set)
    background.cancel()
    assert background.poll()==[] and background.alive
    release.set()
    qtbot.waitUntil(lambda:not background.alive)
    assert background.poll()==[{'kind':'cancel','ok':True,'error':''}]
    assert len(cancelled)==1


def test_initialization_failure_releases_owner_and_reports_error(qtbot):
    def failed(printer, settings):
        raise RuntimeError('Driver rejected setup')
    background=BackgroundPrintSpoolV318(object(),{},factory=failed)
    qtbot.waitUntil(lambda:not background.alive)
    assert background.poll()==[{'kind':'error','ok':False,'error':'Driver rejected setup'}]
    assert not background.busy
