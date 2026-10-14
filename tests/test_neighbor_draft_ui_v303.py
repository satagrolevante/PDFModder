"""Neighbor layout options affect the real draft and ignore stale worker replies."""
from copy import deepcopy
from dataclasses import replace

import pymupdf as fitz
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QDialog

from pdfmodder.model import Glyph
from pdfmodder.selection_ui_v300 import NeighborLayoutDialogV303
from pdfmodder.tools_ui_v150 import ToolSection
from test_selection_ui_v300 import Harness, payload


class NeighborHarness(Harness):
    def __init__(self):
        super().__init__()
        neighbor=Glyph(1,'vecino',(60.,30.),(60.,20.,90.,30.),(60.,20.,90.,30.),
                       'Helvetica',10.,(0.,0.,0.),1.,0,0,0)
        self.model=replace(self.model,revision='test',glyphs=self.model.glyphs+[neighbor])
        with fitz.open() as document:
            png=document.new_page(width=200,height=150).get_pixmap().tobytes('png')
        self.canvas.set_page(png,self.model,1.);self.canvas.set_selection([0])
        self.allow_overlap_box=QCheckBox();self.property_box.layout().addRow(self.allow_overlap_box)
        self._workspace_timer_v200=QTimer(self);self._workspace_timer_v200.setSingleShot(True)
        self._active_session_v200='original-tab'
        self.requests=[]

    def _submit(self,command,request,callback):
        self.requests.append((command,deepcopy(request),callback));self.busy=True;return True

    def _exec_edit_dialog(self,dialog):
        self.last_dialog=dialog;return QDialog.Rejected

    def complete(self,result):
        self.busy=False;self.requests[-1][2](result)


@pytest.fixture
def window(qtbot):
    widget=NeighborHarness();qtbot.addWidget(widget);widget.show()
    return widget


def expanded(source):
    result=deepcopy(source)
    result.update(ids=[0,1],rect=[20.,20.,150.,70.],width=130.,height=50.,catalog=[],
                  neighbor_layout_info={'scope':'paragraph','neighbor_count':1})
    result['runs'].append(dict(result['runs'][0],text=' vecino'))
    return result


def test_overlap_option_is_reachable_and_updates_current_draft_without_typing(window,qtbot):
    window.format_tools_section=ToolSection('Formato','testFormat',expanded=False)
    window.centralWidget().layout().addWidget(window.format_tools_section)
    window.format_tools_section.body.addWidget(window.rich_result)
    window.property_box.setEnabled(False)
    window._open_rich_payload(payload(text='Mi corrección',allow_overlap=False))
    before=deepcopy(window.canvas.editor.payload());serial=window._rich_serial
    assert window.format_tools_section.header.isChecked()
    qtbot.waitUntil(window.draft_overlap_box_v303.isVisible)
    assert window.draft_overlap_box_v303.isVisible() and window.draft_overlap_box_v303.isEnabled()
    assert not window.allow_overlap_box.isEnabled()
    window.draft_overlap_box_v303.setChecked(True)
    current=window.canvas.editor.payload()
    assert current['allow_overlap'] and current['runs']==before['runs']
    assert current['paragraphs']==before['paragraphs'] and current['rect']==before['rect']
    assert window._rich_serial>serial and window._rich_pending['allow_overlap']
    assert window._rich_timer.isActive() and window._workspace_timer_v200.isActive()
    assert window.canvas.editor._draft_changed


def test_restored_overlap_choice_is_not_overwritten_by_global_checkbox(window):
    window.allow_overlap_box.setChecked(False)
    window._open_rich_payload(payload(allow_overlap=True))
    assert window.draft_overlap_box_v303.isChecked() and window.canvas.editor.payload()['allow_overlap']
    window._end_rich();window.allow_overlap_box.setChecked(True)
    window._open_rich_payload(payload(allow_overlap=False))
    assert not window.draft_overlap_box_v303.isChecked()
    assert not window.canvas.editor.payload()['allow_overlap']


def test_pdf_view_and_accepting_disable_options_without_blocking_pdf_accept(window):
    window._open_rich_payload(payload(allow_overlap=False))
    window.canvas.editor.toolbar.pdf_button.setChecked(True)
    assert window.canvas.editor.pdf_view
    assert not window.draft_overlap_box_v303.isEnabled() and not window.draft_neighbors_button_v303.isEnabled()
    assert window.canvas.editor.toolbar.accept.isEnabled()
    window.canvas.editor.toolbar.pdf_button.setChecked(False)
    window._rich_accept(window.canvas.editor.payload())
    assert window._rich_accept_pending and not window.draft_overlap_box_v303.isEnabled()
    assert not window.draft_neighbors_button_v303.isEnabled()
    window._rich_failed('rich_prepare','El texto se solapa con caracteres vecinos.')
    assert window.draft_overlap_box_v303.isEnabled() and window.draft_neighbors_button_v303.isEnabled()


def test_overlap_failure_keeps_text_and_format_and_shows_both_actions(window):
    window._open_rich_payload(payload(text='Mi corrección',allow_overlap=False))
    before=deepcopy(window.canvas.editor.payload())
    window._rich_failed('rich_prepare','El texto se solapa con caracteres vecinos.')
    assert window.canvas.editor.payload()==before and not window.canvas.editor.isReadOnly()
    assert 'permitir el solapamiento' in window.draft_area_status_v300.text()
    assert 'redistribuir' in window.draft_area_status_v300.text()
    assert window.draft_overlap_box_v303.isVisible() and window.draft_neighbors_button_v303.isVisible()


def test_neighbor_proposal_extends_selection_without_committing_and_previews_new_draft(window):
    window._open_rich_payload(payload(text='Mi corrección',allow_overlap=False))
    old=deepcopy(window.canvas.editor.payload());old_serial=window._rich_serial
    window._rich_pending=deepcopy(old);window._rich_timer.start(1000)
    assert window._redistribute_neighbors_draft_v303('paragraph')
    assert window.requests[-1][0]=='rich_redistribute'
    assert window.requests[-1][1]=={'request':old,'scope':'paragraph'}
    assert window._rich_pending is None and not window._rich_timer.isActive()
    assert window._rich_serial>old_serial and not window.canvas.editor.toolbar.accept.isEnabled()
    window.complete(expanded(old))
    current=window.canvas.editor.payload()
    assert current['ids']==[0,1] and window.canvas.ids==[0,1]
    assert ''.join(run['text'] for run in current['runs'])=='Mi corrección vecino'
    style={key:value for key,value in old['runs'][0].items() if key!='text'}
    assert all({key:value for key,value in run.items() if key!='text'}==style for run in current['runs'])
    assert current['paragraphs']==old['paragraphs']
    assert current['rect']==[20.,20.,150.,70.] and not current['allow_overlap']
    assert 'neighbor_layout_info' not in current and 'neighbor_layout_info' not in window.canvas.editor._payload
    assert window._editing_context==(0,'test',(0,1))
    assert window._rich_pending['ids']==[0,1] and window._rich_timer.isActive()
    assert window._workspace_timer_v200.isActive() and window.canvas.editor.toolbar.accept.isEnabled()
    assert '1 caracteres vecinos' in window.draft_area_status_v300.text()
    assert [command for command,_,_ in window.requests]==['rich_redistribute']


@pytest.mark.parametrize('change',['typing','option','cancel','page','revision','selection','tab'])
def test_late_neighbor_reply_cannot_replace_a_changed_draft_or_source(window,change):
    window._open_rich_payload(payload(text='Mi corrección',allow_overlap=False))
    original=deepcopy(window.canvas.editor.payload())
    assert window._redistribute_neighbors_draft_v303('paragraph')
    if change=='typing':window.canvas.editor.insertPlainText(' reciente')
    elif change=='option':window.draft_overlap_box_v303.setChecked(True)
    elif change=='cancel':window._end_rich()
    elif change=='page':window.page_number=1
    elif change=='revision':window.model=replace(window.model,revision='another-revision')
    elif change=='selection':window.canvas.set_selection([1])
    elif change=='tab':window._active_session_v200='other-tab'
    before=deepcopy(window.canvas.editor.payload());ids=window.canvas.ids[:]
    window.complete(expanded(original))
    assert window.canvas.editor.payload()==before and window.canvas.ids==ids
    assert window._neighbor_request_v303 is None
    if change=='cancel':assert not window._rich_active and not window.canvas.editor.isVisible()
    else:assert window._rich_active and window.canvas.editor.isVisible()


def test_neighbor_preparation_failure_keeps_draft_and_reenables_choices(window):
    window._open_rich_payload(payload(text='Mi corrección',allow_overlap=True))
    before=deepcopy(window.canvas.editor.payload())
    window._redistribute_neighbors_draft_v303('cell');window.busy=False
    window._rich_failed('rich_redistribute','No se reconoce una celda delimitada compatible.')
    assert window.canvas.editor.payload()==before and window.canvas.ids==[0]
    assert not window.canvas.editor.isReadOnly() and window._neighbor_request_v303 is None
    assert window.draft_neighbors_button_v303.isEnabled() and window.draft_overlap_box_v303.isChecked()
    assert 'borrador' in window.draft_area_status_v300.text()
    assert 'No se reconoce una celda' in window.draft_area_status_v300.text()


def test_cancel_scope_dialog_keeps_pending_preview_and_draft(window):
    window._open_rich_payload(payload(text='Mi corrección',allow_overlap=False))
    before=deepcopy(window.canvas.editor.payload())
    window._rich_changed(before);serial=window._rich_serial
    assert window._redistribute_neighbors_draft_v303() is False
    assert isinstance(window.last_dialog,NeighborLayoutDialogV303)
    assert window.canvas.editor.payload()==before and window._rich_serial==serial
    assert window._rich_pending==before and window._rich_timer.isActive() and window.requests==[]


def test_scope_dialog_offers_paragraph_cell_area_with_preview(window):
    window._open_rich_payload(payload())
    dialog=NeighborLayoutDialogV303(window.canvas.editor.payload(),window.model,'cell',window)
    assert [dialog.scope_box.itemData(i) for i in range(dialog.scope_box.count())]==['paragraph','cell','area']
    assert dialog.scope()=='cell' and 'vecino' in dialog.preview.text()
    dialog.scope_box.setCurrentIndex(dialog.scope_box.findData('area'))
    assert 'Área:' in dialog.preview.text() and 'fuera' in dialog.preview.text()


def test_new_text_can_allow_overlap_but_requires_existing_selection_for_neighbors(window):
    value=payload(allow_overlap=False);value['ids']=[]
    window._open_rich_payload(value)
    assert window.draft_overlap_box_v303.isEnabled() and not window.draft_neighbors_button_v303.isEnabled()
    assert 'seleccionar texto existente' in window.draft_neighbors_button_v303.toolTip()
    assert window._redistribute_neighbors_draft_v303('area') is False and window.requests==[]
