"""Area decisions keep the real rich draft editable after validation fails."""
from copy import deepcopy

import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QMainWindow, QToolBar, QVBoxLayout, QWidget

from pdfmodder.canvas import PdfCanvas
from pdfmodder.model import Glyph, PageModel, union
from pdfmodder.rich_ui import RichEditing
from pdfmodder.selection_ui_v300 import SelectionUiV300Mixin


class Harness(SelectionUiV300Mixin, RichEditing, QMainWindow):
    """Uses the actual canvas/editor without an unrelated multiprocessing job."""
    def __init__(self):
        super().__init__()
        self.busy=False;self.application_mode='editing';self._closed=False;self.page_number=0
        self.toolbar=QToolBar(self);self.addToolBar(self.toolbar)
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central)
        self.canvas=PdfCanvas();layout.addWidget(self.canvas)
        self.mode_box=QComboBox()
        for key in ('character','word','line','block'):self.mode_box.addItem(key,key)
        self.mode_box.setCurrentIndex(1)
        self.mode_box.currentIndexChanged.connect(lambda _:setattr(self.canvas,'mode',self.mode_box.currentData()))
        layout.addWidget(self.mode_box)
        self.property_box=QGroupBox();self.property_box.setLayout(QFormLayout());layout.addWidget(self.property_box)
        self._init_rich(layout)
        self._init_selection_v300()
        glyph=Glyph(0,'Texto',(20.,30.),(20.,20.,50.,30.),(20.,20.,50.,30.),'Helvetica',10.,(0.,0.,0.),1.,0,0,0)
        self.model=PageModel(0,200.,150.,0,(1.,0.,0.,1.,0.,0.),(1.,0.,0.,1.,0.,0.),(0.,0.,200.,150.),[glyph],
            selection_boundaries=[(10.,10.,90.,10.),(90.,10.,90.,65.),(90.,65.,10.,65.),(10.,65.,10.,10.)])
        with fitz.open() as doc:
            page=doc.new_page(width=200,height=150)
            png=page.get_pixmap().tobytes('png')
        self.canvas.set_page(png,self.model,1.)
        self.canvas.set_selection([0])
        self.resize(800,700)

    def _action(self,text,callback):
        action=self.toolbar.addAction(text);action.triggered.connect(callback);return action

    def _refresh_actions(self):pass
    def _notice(self,message):pass
    def _rich_pump(self):self._rich_timer.stop()


@pytest.fixture
def harness(qtbot):
    window=Harness();qtbot.addWidget(window);window.show()
    return window


def payload(rect=(20.,20.,50.,30.), text='Texto', **options):
    return dict(page=0,ids=[0],revision='test',rect=list(rect),width=rect[2]-rect[0],height=rect[3]-rect[1],
                runs=[dict(text=text,font_name='Helvetica',size=10.,color=(.1,.2,.3),underline=True)],
                paragraphs=[dict(index=0)],auto_width=False,auto_height=False,**options)


def test_validation_failure_keeps_text_format_and_shows_explicit_area_choices(harness):
    window=harness;window._open_rich_payload(payload(text='Texto corregido'))
    editor=window.canvas.editor;before=deepcopy(editor.payload())
    window._rich_accept_pending=True;editor.set_accepting(True)
    window._rich_failed('rich_prepare','El texto supera la altura disponible.')
    assert editor.isVisible() and not editor.isReadOnly()
    assert not window._rich_accept_pending and editor.payload()==before
    assert 'Tu texto sigue en el borrador' in window.draft_area_status_v300.text()
    assert window.canvas.draft_overflow_rect_v300 is not None
    assert window.draft_area_button_v300.isEnabled()
    assert window.draft_reflow_button_v300.isEnabled()
    assert window.draft_size_button_v300.isEnabled()


def test_chosen_area_changes_bounds_without_changing_text_or_styles(harness):
    window=harness;window._open_rich_payload(payload(text='Mi texto'))
    before=deepcopy(window.canvas.editor.payload()['runs'])
    window._apply_draft_area_v300((20.,20.,140.,80.))
    result=window.canvas.editor.payload()
    assert result['runs']==before
    assert result['rect']==[20.,20.,140.,80.]
    assert result['width']==120. and result['height']==60.
    assert result['auto_width'] is result['auto_height'] is False


def test_fresh_cell_selection_uses_border_but_explicit_area_and_restored_draft_keep_their_bounds(harness):
    window=harness;window.mode_box.setCurrentIndex(window.mode_box.findData('cell'));window.canvas.set_selection([0])
    natural=union(g.bbox for g in window.model.glyphs)
    window._open_rich_payload(payload(rect=natural))
    assert window.canvas.editor._payload['rect']==[12.,12.,88.,63.]
    window._end_rich()
    chosen=(15.,18.,120.,95.)
    window._open_rich_payload(payload(rect=chosen,text='Borrador recuperado'))
    assert window.canvas.editor._payload['rect']==list(chosen)
    assert window.canvas.editor.toPlainText()=='Borrador recuperado'
    window._end_rich()
    explicit=payload(rect=natural);explicit['_explicit_area_v300']=True
    window._open_rich_payload(explicit)
    assert window.canvas.editor._payload['rect']==list(natural)


def test_reflow_replaces_only_soft_breaks_and_keeps_paragraphs_and_styles(harness):
    window=harness;window._open_rich_payload(payload(rect=(20.,20.,170.,100.),text='Una\u2028línea\nOtro párrafo'))
    before={k:v for k,v in window.canvas.editor.payload()['runs'][0].items() if k!='text'}
    window._reflow_draft_v300()
    result=window.canvas.editor.payload()
    assert ''.join(r['text'] for r in result['runs'])=='Una línea\nOtro párrafo'
    assert all({k:v for k,v in run.items() if k!='text'}==before for run in result['runs'])
    assert len(result['paragraphs'])==2


def test_auto_height_does_not_report_a_height_only_overflow(harness):
    window=harness
    value=payload(rect=(20.,20.,140.,35.),text='Varias\nLíneas\nDe texto')
    value['auto_height']=True
    window._open_rich_payload(value)
    window._draft_dimensions_v300=lambda:(60.,80.)
    window._update_draft_area_v300()
    assert window.canvas.draft_overflow_rect_v300 is None
    assert 'supera' not in window.draft_area_status_v300.text()


def test_cancel_clears_overflow_overlay_and_area_controls(harness):
    window=harness;window._open_rich_payload(payload())
    window._rich_failed('rich_prepare','El texto supera la altura disponible.')
    window._end_rich()
    assert not window.canvas.editor.isVisible()
    assert window.canvas.draft_overflow_rect_v300 is None
    assert not window.draft_area_tools_v300.isVisible()
