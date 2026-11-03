"""Immediate plain text, with revision-safe asynchronous rich enrichment."""
from types import SimpleNamespace
from concurrent.futures import Future

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from pdfmodder.clipboard_ui_v170 import ClipboardUiV170Mixin, mime_bundle_v170
from pdfmodder.responsive_ui_v310 import ResponsiveUiV310Mixin
from test_saving_v300 import saving_window, make_pdf, open_editing


class Window(ClipboardUiV170Mixin, QMainWindow):
    error_raised=Signal(str)

    def __init__(self):
        super().__init__()
        self._closed=False;self.busy=False;self._command='';self._active_session_v200='session-a'
        self.page_number=0
        self.state={'copy_allowed':True,'document_revision':'rev-a'}
        self.glyph=SimpleNamespace(id=1,mode=0,opacity=1)
        self.text='primera\u2028segunda'
        self.model=SimpleNamespace(number=0,revision='rev-a',selected=lambda ids:[self.glyph],
                                   text=lambda ids:self.text)
        self.canvas=SimpleNamespace(model=self.model,ids=[1],selected_image=lambda:None,
            editor=SimpleNamespace(isVisible=lambda:False),setCursor=lambda _:None)
        self.compare_action=SimpleNamespace(isChecked=lambda:False)
        self._rich_loading=False;self._rich_active=False;self._navigation=False
        self.application_mode='editing';self.requests=[];self.notices=[];self.errors=[];self.placed=[]
        self._init_fast_clipboard_v318()
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed_v318)

    def _refresh_clipboard_v170(self):pass
    def _native_clipboard_v170(self,operation):return False
    def _clipboard_ready_v170(self,editing=False):return not self.busy
    def _navigation_pending_v310(self):return self._navigation
    def _render_busy_v310(self):return ResponsiveUiV310Mixin._render_busy_v310(self)
    def _notice(self,message):self.notices.append(message)
    def _error(self,message):self.errors.append(message);self.error_raised.emit(message)
    def _refresh_actions(self):pass
    def _edited(self,result):pass
    def _place_clipboard_v170(self,x,y):self.placed.append((x,y,self._clipboard_placement_v170))
    def _submit(self,command,payload=None,callback=None):
        if self.busy:return False
        self.requests.append((command,payload,callback));self.busy=True;self._command=command
        return True
    def complete(self,index=0,**kwargs):
        self.busy=False
        result={'bundle':{'version':1,'kind':'text','portable':True,'runs':['original styles']},
                'text':'texto enriquecido'}
        result.update(kwargs)
        self.requests[index][2](result)


@pytest.fixture
def window(qtbot):
    result=Window();qtbot.addWidget(result)
    yield result
    result._closed=True;result._clipboard_copy_timer_v318.stop()
    QApplication.clipboard().clear()


def test_copy_is_immediate_and_rich_format_is_added_later(window):
    window.clipboard_copy_v170()
    assert QApplication.clipboard().text()=='primera\nsegunda'
    assert not window.requests
    window._enrich_clipboard_v318()
    command,payload,_=window.requests[0]
    assert command=='clipboard_copy' and payload['_background_ui'] is True
    assert payload['session_id']=='session-a' and payload['revision']=='rev-a' and payload['ids']==[1]
    window.complete()
    assert mime_bundle_v170(QApplication.clipboard().mimeData())['runs']==['original styles']


def test_background_formatting_yields_to_foreground_editing(window):
    window.clipboard_copy_v170()
    window._ui_mutation_locked_v310=lambda:True
    window._enrich_clipboard_v318()
    assert not window.requests
    assert QApplication.clipboard().text()=='primera\nsegunda'
    window._ui_mutation_locked_v310=lambda:False
    window._enrich_clipboard_v318()
    assert window.requests[0][0]=='clipboard_copy'


def test_external_copy_is_never_overwritten_by_old_rich_result(window):
    window.clipboard_copy_v170();window._enrich_clipboard_v318()
    QApplication.clipboard().setText('copiado en otra aplicación')
    window.complete()
    assert QApplication.clipboard().text()=='copiado en otra aplicación'
    assert window._clipboard_pending_v318 is None


def test_repeated_copy_discards_old_rich_result(window):
    window.clipboard_copy_v170();window._enrich_clipboard_v318()
    window.text='segunda selección';window.clipboard_copy_v170()
    assert QApplication.clipboard().text()=='segunda selección'
    window.complete()
    assert QApplication.clipboard().text()=='segunda selección'
    window._enrich_clipboard_v318();window.complete(1)
    assert mime_bundle_v170(QApplication.clipboard().mimeData()) is not None


def test_immediate_internal_paste_waits_for_original_fonts(window):
    window.clipboard_copy_v170();window._enrich_clipboard_v318()
    window.clipboard_paste_v170((70,120))
    assert not window.placed
    assert window._clipboard_paste_pending_v318 is not None
    window.complete()
    assert window.placed==[(70,120,{'version':1,'kind':'text','portable':True,'runs':['original styles']})]


def test_queued_paste_cannot_follow_revision_change(window):
    window.clipboard_copy_v170();window._enrich_clipboard_v318()
    window.clipboard_paste_v170((70,120));window.state['document_revision']='rev-b'
    window.complete()
    assert not window.placed and 'destino cambió' in window.notices[-1]


def test_old_revision_or_tab_does_not_start_background_analysis(window):
    window.clipboard_copy_v170();window.state['document_revision']='rev-b'
    window._enrich_clipboard_v318()
    assert not window.requests and window._clipboard_pending_v318 is None
    assert QApplication.clipboard().text()=='primera\nsegunda'


def test_failed_rich_copy_keeps_plain_text_and_cancels_queued_paste(window):
    window.clipboard_copy_v170();window._enrich_clipboard_v318()
    window.clipboard_paste_v170((70,120));window._error('No se pudo reproducir la fuente')
    assert window._clipboard_pending_v318 is None and window._clipboard_paste_pending_v318 is None
    assert QApplication.clipboard().text()=='primera\nsegunda'
    assert not window.placed


@pytest.mark.parametrize('change',[
    lambda w:w.state.update(copy_allowed=False),
    lambda w:w.state.update(document_revision='rev-b'),
    lambda w:w.state.update(preview=True),
    lambda w:setattr(w.canvas,'model',None),
    lambda w:setattr(w,'_navigation',True),
    lambda w:setattr(w.glyph,'mode',3),
    lambda w:setattr(w.glyph,'opacity',0),
])
def test_fast_copy_requires_current_permitted_visible_selection(window,change):
    QApplication.clipboard().setText('anterior')
    change(window)
    assert not window._copy_plain_v318()
    assert QApplication.clipboard().text()=='anterior'


def test_copy_responds_during_read_analysis_but_not_mutation(window):
    window.busy=True;window._command='selection_capabilities'
    window.clipboard_copy_v170()
    assert QApplication.clipboard().text()=='primera\nsegunda'
    window._enrich_clipboard_v318()
    assert not window.requests
    QApplication.clipboard().setText('anterior')
    window._command='clipboard_apply'
    assert not window._copy_plain_v318()
    assert QApplication.clipboard().text()=='anterior'


def test_real_editing_window_copies_before_enrichment_and_preserves_portable_paste(
        qtbot,saving_window,tmp_path,monkeypatch):
    window=saving_window
    source=make_pdf(tmp_path/'copiar.pdf','Texto para copiar')
    original=source.read_bytes()
    open_editing(qtbot,window,source)
    qtbot.waitUntil(lambda:window.model is not None and not window.busy,timeout=30000)
    window.canvas.setFocus()
    window.canvas.set_selection([g.id for g in window.model.glyphs])
    expected=window.model.text(window.canvas.ids)
    window.clipboard_copy_v170()
    assert QApplication.clipboard().text()==expected
    assert mime_bundle_v170(QApplication.clipboard().mimeData()) is None
    qtbot.waitUntil(lambda:window._clipboard_pending_v318 is None and not window.busy,timeout=30000)
    assert not window.last_error
    bundle=mime_bundle_v170(QApplication.clipboard().mimeData())
    assert bundle is not None and bundle['kind']=='text'
    window.clipboard_paste_v170()
    assert window._clipboard_placement_v170['kind']=='text'
    assert source.read_bytes()==original
    window._cancel_placement()
    # Exercise App._poll's real failure order, including the public error
    # signal, so a failed enrichment cannot strand subsequent Paste requests.
    failed=Future();failed.set_exception(ValueError('fallo de enriquecimiento de prueba'))
    with monkeypatch.context() as context:
        context.setattr(window.pool,'submit',lambda *_args,**_kwargs:failed)
        window.clipboard_copy_v170();window._enrich_clipboard_v318()
        assert window._clipboard_pending_v318['started']
        window._poll()
        assert window._clipboard_pending_v318 is None
        assert window.last_error=='fallo de enriquecimiento de prueba'
        assert QApplication.clipboard().text()==expected
    QApplication.clipboard().clear()


def test_cut_reply_from_identical_revision_in_another_tab_cannot_delete(window):
    window.clipboard_cut_v170()
    assert window.requests[0][0]=='clipboard_copy'
    window._active_session_v200='duplicate-tab'
    window.complete()
    assert len(window.requests)==1
