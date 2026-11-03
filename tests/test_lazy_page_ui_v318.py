"""Inventories are deferred, coalesced and cannot update another revision/tab."""
from types import SimpleNamespace

from PySide6.QtWidgets import QMainWindow
import pytest

from pdfmodder.lazy_page_ui_v318 import LazyPageUiV318Mixin


class Base:
    def _submit(self,command,payload=None,callback=None):
        self.requests.append((command,payload,callback))
        return True


class Window(LazyPageUiV318Mixin,Base,QMainWindow):
    def __init__(self):
        super().__init__()
        self._closed=False;self.busy=False;self.application_mode='editing'
        self.state={'session_id':'one'};self._active_session_v200='one'
        self.model=SimpleNamespace(revision='revision');self.page_number=0
        self.compare_action=SimpleNamespace(isChecked=lambda:False)
        self.canvas=SimpleNamespace(image_mode=False,selected_image=lambda:None,
                                    set_images=lambda images,rect:self.images.append((images,rect)))
        self.requests=[];self.images=[];self._restore_image_rect=None
        self.fonts=[]
        self._inventory_view_v318=('one','revision',0,False)
        self._inventory_ready_v318={'fonts':False,'images':False}
        self._inventory_view_v318=self._inventory_context_v318()
        self._inventory_ready_v318={'images':False,'fonts':False}

    def refresh_elements(self):pass


@pytest.fixture
def window(qtbot):
    value=Window();qtbot.addWidget(value)
    yield value
    value._closed=True
    if hasattr(value,'_inventory_timer_v318'):value._inventory_timer_v318.stop()


def test_page_submit_asks_only_for_inventory_required_by_active_tool(window):
    window._submit('page',{'number':0})
    assert window.requests[-1][1]=={'number':0,'lazy':True}
    window.canvas.image_mode=True
    window._submit('page',{'number':0})
    assert window.requests[-1][1]['capabilities']==('images',)


def test_requests_coalesce_and_wait_until_worker_is_free(window):
    window.busy=True
    seen=[]
    window._ensure_page_inventory_v318(['fonts'],lambda:seen.append('font'))
    window._ensure_page_inventory_v318(['images'])
    window._prepare_page_inventory_v318()
    assert window.requests==[]
    window.busy=False;window._prepare_page_inventory_v318()
    command,payload,callback=window.requests[0]
    assert command=='page_capabilities_v318' and payload['needs']==['fonts','images']
    assert payload['_background_ui'] and payload['session_id']=='one'
    callback({'number':0,'revision':'revision','original':False,'fonts':[{'name':'font'}],
              'images':[{'id':'image'}],'inventory_ready_v318':{'fonts':True,'images':True}})
    assert window.fonts==[{'name':'font'}] and window.images==[([{'id':'image'}],None)]
    assert seen==['font']
    assert not window._ensure_page_inventory_v318(['fonts','images'])


def test_revision_change_discards_queued_inventory(window):
    window._ensure_page_inventory_v318(['images'])
    window.model.revision='changed'
    window._prepare_page_inventory_v318()
    assert not window.requests and window._inventory_request_v318 is None


def test_inventory_yields_to_a_foreground_placement(window):
    window._ensure_page_inventory_v318(['images'])
    window._placement='text'
    window._prepare_page_inventory_v318()
    assert not window.requests
    window._placement=None
    window._prepare_page_inventory_v318()
    assert window.requests[0][0]=='page_capabilities_v318'


def test_tab_change_discards_late_inventory_reply(window):
    window._ensure_page_inventory_v318(['images'])
    window._prepare_page_inventory_v318()
    callback=window.requests[-1][2]
    window.state={'session_id':'two'};window._active_session_v200='two'
    callback({'number':0,'revision':'revision','original':False,'fonts':[],
              'images':[{'id':'old-image'}],'inventory_ready_v318':{'fonts':False,'images':True}})
    assert window.images==[]
