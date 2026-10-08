"""Contrato de los modos y portapapeles, sin proceso PDF ni red."""
import pytest
from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_tools_ui_v150 import NoPdfPool
from test_reading_canvas_v171 import make_canvas, wheel
from test_continuous_ui_v180 import point


@pytest.fixture
def reader(qtbot, monkeypatch):
    import pdfmodder.app as application
    monkeypatch.setattr(application, 'ProcessPoolExecutor', NoPdfPool)
    monkeypatch.setattr(application.MainWindow, '_offer_recovery_v200', lambda self:None)
    window = application.MainWindow()
    qtbot.addWidget(window)
    window.poller.stop()
    window.thumbnail_timer.stop()
    window.reader_timer_v180.stop()
    window.show()
    yield window
    window.state = {}
    window._allow_close = True
    window.close()


def load_fixture(reader, qtbot):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    canvas, lines = make_canvas(qtbot)
    canvas.hide()
    image = QImage(540, 1200, QImage.Format_RGB32); image.fill(Qt.white)
    buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); image.save(buffer, 'PNG')
    reader.model = canvas.model
    reader.state = {'path':'synthetic.pdf','page_count':2,'document_revision':reader.model.revision,
                    'issues':[],'editing_prepared':False,'validation_pending':True,'copy_allowed':True}
    reader.zoom=1.
    reader._reader_key_v180=(reader.model.revision,False)
    reader.reader.reset_document([{'width':540.,'height':1200.}]*2,zoom=1.)
    reader.reader.set_page(0,bytes(buffer.data()),reader.model,1.)
    reader.reader.set_page(1,bytes(buffer.data()),replace(reader.model,number=1),1.)
    reader._populate_pages_v300(2,0)
    reader._refresh_actions()
    QApplication.processEvents()
    return lines


def test_startup_reading_and_explicit_tools_without_document(reader):
    assert reader.application_mode == 'reading' and reader.canvas.reading_mode
    assert not reader.tools_scroll.isVisible() and not reader.tools_action.isChecked()
    assert all(not action.isVisible() for action in reader.mode_actions_v170.values())
    reader.tools_action.setChecked(True)
    assert reader.application_mode == 'editing' and reader.tools_scroll.isVisible()
    reader.reading_action.trigger()
    assert reader.application_mode == 'reading' and not reader.tools_scroll.isVisible()


def test_reading_copy_keyboard_and_context_no_editor(reader, qtbot,monkeypatch):
    lines = load_fixture(reader, qtbot)
    queries=[]
    def submit(command,payload=None,callback=None):
        queries.append((command,payload));callback({'text':reader.reader.selection_text()});return True
    monkeypatch.setattr(reader,'_submit',submit)
    qtbot.mouseDClick(reader.reader.viewport(),Qt.LeftButton,pos=point(reader.reader,0,lines['top'][1]))
    reader.reader.setFocus()
    qtbot.keyClick(reader.reader.viewport(),Qt.Key_C,Qt.ControlModifier)
    assert QApplication.clipboard().text() == 'UNO'
    assert queries[-1][0]=='reading_copy_range'
    assert not reader.canvas.editor.isVisible() and not reader._rich_active
    assert reader.copy_action_v170.isEnabled() and not reader.cut_action_v170.isEnabled()
    reader._reader_context_v180(reader.reader.mapToGlobal(reader.reader.rect().center()))
    assert [a.text() for a in reader._clipboard_menu_v170.actions()] == ['Copiar']
    reader._clipboard_menu_v170.close()
    reader.state['copy_allowed'] = False
    reader.clipboard_copy_v170()
    assert 'no permite copiar' in reader.last_error


def test_tools_requests_full_preparation_before_mutation(reader, qtbot, monkeypatch):
    load_fixture(reader, qtbot)
    requests = []
    monkeypatch.setattr(reader, '_submit', lambda command, payload=None, callback=None: requests.append((command,payload,callback)) or True)
    reader.tools_action.setChecked(True)
    reader._refresh_actions()  # The real _submit refreshes controls after queuing work.
    assert requests[0][0] == 'prepare_editing'
    assert reader.application_mode == 'reading' and not reader.save_action.isEnabled()
    assert not reader._reading_command_allowed_v171('delete_pages')
    monkeypatch.setattr(reader, '_loaded_page', lambda result: None)
    reader.state['editing_prepared'] = True
    requests[0][2]({})
    assert reader.application_mode == 'editing' and reader.tools_scroll.isVisible()
    assert reader._reading_command_allowed_v171('delete_pages')


def test_wheel_page_bounds_and_mutation_commands_stay_guarded(reader, qtbot, monkeypatch):
    load_fixture(reader, qtbot)
    requested = []
    monkeypatch.setattr(reader, 'go_page', lambda number: requested.append(number))
    bar=reader.reader.verticalScrollBar();bar.setValue(bar.maximum())
    QApplication.processEvents()
    assert reader.page_number==1
    wheel(reader.reader)
    assert bar.value()==bar.maximum() and requested==[]
    reader._wheel_page_v171(1)
    assert requested==[]
    assert reader._submit('image_apply', {}) is False
    assert reader._submit('delete_pages', {}) is False
