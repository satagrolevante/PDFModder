"""Progressive print sequencing, stale replies and immutable preview reuse."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QImage
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QMainWindow

from pdfmodder.draft_control_v305 import DraftControl
from pdfmodder.printing_ui_v314 import PrintingUiV314Mixin
from test_print_dialog_v314 import dialog_factory  # noqa:F401


class Timer:
    def start(self, *args): pass
    def stop(self): pass


class Writer:
    def __init__(self, printer, settings):
        self.settings = dict(settings)
        self.pages = []
        self.error = ''
        self.cancelled = False
    def push(self, page): self.pages.append(page['page']);return True
    def finish(self): return bool(self.pages)
    def cancel(self): self.cancelled = True;return True


class Harness(PrintingUiV314Mixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = {'document_revision':'current', 'path':'document.pdf'}
        self._active_session_v200 = 'session'
        self._closed = self.busy = False
        self.requests = []
        self.saved = []
        self._printer_preferences_v311 = SimpleNamespace(remember=lambda *args:self.saved.append(args))
    def _submit(self, command, payload, callback):
        assert not self.busy
        self.busy = True
        self.requests.append((command,payload,callback))
        return True
    def _make_print_printer_v314(self, settings): return settings['printer_device_v314']
    def _notice(self, message): pass


@pytest.fixture
def pipeline(qtbot, dialog_factory, monkeypatch):
    import pdfmodder.printing_device_v314 as device
    monkeypatch.setattr(device, 'PrintSpoolV314', Writer)
    create, _ = dialog_factory
    dialog = create()
    win = Harness();qtbot.addWidget(win)
    ctx = {'dialog':dialog,'session':'session','revision':'current','closed':False,
           'cancelled':False,'inflight':None,'job':None,'spool':None,
           'preview_wanted':None,'preview_inflight':None,'preview_control':DraftControl(),
           'print_control':DraftControl(),'ticket':None,'index':0,'geometries':{},
           'quality_noted':None,'timer':Timer()}
    dialog.preview_invalidated.connect(lambda:win._preview_changed_v314(ctx))
    dialog.cancel_requested.connect(lambda:win._cancel_print_v314(ctx))
    yield win,dialog,ctx
    ctx['closed'] = True
    ctx['preview_control'].close();ctx['print_control'].close()
    dialog.finish_cancel()


def reply(win, index, tmp_path, cancelled=False):
    _,payload,callback = win.requests[index]
    win.busy = False
    if cancelled:
        callback({'print_cancelled_v314':True,'revision':'current','pages':[]});return
    path=tmp_path/f'{index}.png'
    image=QImage(60,80,QImage.Format_RGB32);image.fill(0xffee1122);image.save(str(path))
    number=payload['pages'][0]
    callback({'revision':'current','pages':[{'page':number,'path':str(path),'width':300.,'height':450.,'dpi':payload['dpi']}],
              'layout_page_v314':{'page':payload['layout_page'],'width':300.,'height':450.}})


def test_same_page_color_change_reuses_inflight_pixels_and_current_presentation(pipeline,tmp_path):
    win,dialog,ctx = pipeline
    win._request_preview_v314(ctx);win._pump_print_v314(ctx)
    ticket=win.requests[0][1]['control']['path']
    dialog.color.setCurrentIndex(dialog.color.findData(QPrinter.GrayScale))
    win._request_preview_v314(ctx)
    assert Path(ticket).is_file()
    reply(win,0,tmp_path)
    assert dialog._preview_page['page'] == 0
    assert dialog._preview_settings['color'] == QPrinter.GrayScale
    win._pump_print_v314(ctx)
    assert len(win.requests) == 1
    assert dialog.preview_stack.currentWidget() is dialog.preview


def test_long_job_is_prepared_one_page_at_a_time_then_finishes(pipeline,tmp_path):
    win,dialog,ctx = pipeline
    dialog.scope.setCurrentIndex(dialog.scope.findData('range'));dialog.pages.setText('5,2-3')
    win._request_print_v314(ctx)
    writer=ctx['spool']
    for index,expected in enumerate((4,1,2)):
        win._pump_print_v314(ctx)
        assert len(win.requests) == index+1
        assert win.requests[index][1]['pages'] == [expected]
        reply(win,index,tmp_path)
        assert writer.pages == [4,1,2][:index+1]
    win._pump_print_v314(ctx)
    assert ctx['job'] is None and len(win.saved) == 1
    assert writer.pages == [4,1,2]


def test_cancel_invalidates_ticket_and_never_sends_late_page(pipeline,tmp_path):
    win,dialog,ctx = pipeline
    win._request_print_v314(ctx);writer=ctx['spool']
    win._pump_print_v314(ctx)
    ticket=Path(win.requests[0][1]['control']['path'])
    assert ticket.is_file()
    win._cancel_print_v314(ctx)
    assert not ticket.exists() and writer.cancelled
    reply(win,0,tmp_path,cancelled=True)
    assert not writer.pages and ctx['job'] is None
    assert win.saved == []


def test_revision_change_discards_prepared_page_and_cancels_own_job(pipeline,tmp_path):
    win,dialog,ctx = pipeline
    win._request_print_v314(ctx);writer=ctx['spool']
    win._pump_print_v314(ctx)
    win.state['document_revision']='changed'
    reply(win,0,tmp_path)
    assert writer.cancelled and writer.pages == []
    assert win.saved == []


from test_saving_v300 import saving_window, open_editing  # noqa:F401,E402


def test_real_long_document_cancel_stops_before_preparing_remaining_pages(qtbot,saving_window,tmp_path,monkeypatch):
    import pymupdf as fitz
    import pdfmodder.printing_v201 as legacy
    import pdfmodder.printing_ui_v314 as controller
    from PySide6.QtCore import QTimer
    from PySide6.QtPrintSupport import QPrinterInfo
    window=saving_window
    source=tmp_path/'long.pdf'
    with fitz.open() as document:
        for number in range(123):
            document.new_page().insert_text((40,60),f'Page {number+1}')
        document.save(source)
    original=source.read_bytes()
    open_editing(qtbot,window,source)
    monkeypatch.setattr(QPrinterInfo,'availablePrinterNames',lambda:['Test printer'])
    monkeypatch.setattr(QPrinterInfo,'defaultPrinterName',lambda:'Test printer')
    caps=lambda _: {'duplex_modes':None,'color_modes':None}
    monkeypatch.setattr(legacy,'printer_capabilities_v201',caps)
    monkeypatch.setattr(controller,'printer_capabilities_v201',caps)
    def device(settings):
        printer=QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(tmp_path/'cancelled-output.pdf'))
        printer.setResolution(72)
        return printer
    monkeypatch.setattr(window,'_make_print_printer_v314',device)
    requests=[]
    real_submit=window._submit
    def submit(command,payload=None,callback=None):
        if command=='print_pages_v200': requests.append(payload['pages'])
        return real_submit(command,payload,callback)
    monkeypatch.setattr(window,'_submit',submit)
    def cancel_after_first(command,result):
        context=getattr(window,'_print_context_v314',None)
        if command=='print_pages_v200' and context and context['index']==1:
            context['dialog'].reject()
    window.operation_finished.connect(cancel_after_first)
    execute=window._exec_edit_dialog
    def run(dialog):
        def start():
            dialog.dpi.setValue(72)
            dialog.print_button.click()
        QTimer.singleShot(0,start)
        watchdog=QTimer(dialog);watchdog.setSingleShot(True)
        watchdog.timeout.connect(dialog.reject);watchdog.start(10000)
        try:return execute(dialog)
        finally:watchdog.stop()
    monkeypatch.setattr(window,'_exec_edit_dialog',run)
    window.choose_print_v200()
    assert requests == [[0]]
    assert not window.busy and window._print_context_v314 is None
    assert source.read_bytes()==original
    assert not window.state['dirty']
