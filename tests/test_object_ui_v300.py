"""Object inventory controls expose real capabilities and preserve edits."""
from types import SimpleNamespace

from PySide6.QtGui import QColor,QPixmap
from PySide6.QtWidgets import QWidget,QGraphicsScene,QColorDialog
import pytest

from pdfmodder.model import pt
from pdfmodder.object_ui_v300 import NativeObjectsDialog


def information(reason=''):
    return {'page':0,'revision':'a'*64,'items':[{
        'id':'vector:1','kind':'vector','label':'Trazado vectorial','parent':None,
        'rect':[20,30,70,90],'layers':[],'resource':None,'properties':{},
        'capabilities':{key:not bool(reason) for key in
            ('move','scale','rotate','duplicate','opacity','line_width','fill_color','stroke_color')}
            | {'reason':reason,'duplicate_reason':''}}]}


def test_dialog_request_preserves_colour_when_operation_changes(qtbot,monkeypatch):
    dialog=NativeObjectsDialog(information());qtbot.addWidget(dialog)
    monkeypatch.setattr(QColorDialog,'getColor',lambda **kwargs:QColor('#00ff00'))
    dialog.pick_colour('fill_color',dialog.fill)
    dialog.operation.setCurrentIndex(dialog.operation.findData('properties'))
    dialog.operation.setCurrentIndex(dialog.operation.findData('move'))
    dialog.dx.setValue(12);dialog.dy.setValue(5)
    dialog.choose()
    assert dialog.result_request['object_id']=='vector:1'
    assert dialog.result_request['dx']==pytest.approx(pt(12))
    assert dialog.result_request['dy']==pytest.approx(pt(5))
    assert dialog.result_request['properties']['fill_color']==[0,1,0]


def test_dialog_disabled_operation_explains_local_reason(qtbot):
    reason='El documento declara firmas digitales.'
    dialog=NativeObjectsDialog(information(reason));qtbot.addWidget(dialog)
    assert not dialog.preview.isEnabled()
    assert reason in dialog.message.text()
    assert not dialog.fill.isEnabled() and not dialog.opacity_enabled.isEnabled()


def test_object_selection_highlights_its_area_on_existing_page_preview(qtbot):
    parent=QWidget();qtbot.addWidget(parent)
    scene=QGraphicsScene(parent);pixmap=QPixmap(200,200);pixmap.fill(QColor('white'))
    parent.canvas=SimpleNamespace(_pixmap_item=scene.addPixmap(pixmap),zoom=2)
    parent.model=SimpleNamespace(rotation_matrix=(1,0,0,1,0,0))
    dialog=NativeObjectsDialog(information(),parent);qtbot.addWidget(dialog)
    assert dialog.page_preview is not None
    assert tuple((dialog.highlight.rect().x(),dialog.highlight.rect().y(),
                  dialog.highlight.rect().width(),dialog.highlight.rect().height()))==(40,60,100,120)
