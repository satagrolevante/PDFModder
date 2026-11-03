"""Real panel placement, drag/drop, PDF edits and signature independence."""
from io import BytesIO

from PIL import Image, ImageDraw
import pymupdf as fitz
from pypdf import PdfReader
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

from pdfmodder.signatures_ui_v317 import SIGNATURE_MIME_V317
from pdfmodder.signature_draw_ui_v317 import SignatureDrawingDialogV317
from pdfmodder.workspace_ui_v170 import local_data_directory
from test_saving_v300 import saving_window, open_editing, finished


def drawing():
    image = Image.new('RGBA', (180, 60), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(5, 40), (30, 7), (55, 45), (90, 14), (170, 28)],
                             fill=(0, 0, 0, 255), width=3)
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def source_pdf(path, rotation=0):
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=350)
        page.insert_text((45, 70), 'Documento de prueba')
        page.draw_rect((40, 110, 300, 260), fill=(.5, .8, 1), color=None)
        page.set_cropbox((20, 30, 400, 330))
        page.set_rotation(rotation)
        doc.new_page(width=420, height=350).insert_text((45, 70), 'Otra pagina intacta')
        doc.save(path)
    return path


def add_saved(window):
    entry = window.signature_library_v317.add('Firma habitual', drawing())
    window._reload_signatures_v317(entry['id'])
    return entry


def send_drop(window, location):
    mime = window.signature_list_v317.signature_mime()
    assert mime.hasFormat(SIGNATURE_MIME_V317) and not mime.hasUrls()
    point = window.canvas.viewport_point(location)
    enter = QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window.canvas.viewport(), enter)
    drop = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(window.canvas.viewport(), drop)
    return enter, drop


def test_panel_creates_named_signatures_without_a_certificate(qtbot, saving_window, monkeypatch):
    window = saving_window
    assert window.signature_tools_section_v317.header.text() == 'Firmas'
    assert not any('iniciales' in button.text().lower()
                   for button in window.signature_tools_section_v317.findChildren(QToolButton))
    def capture(dialog):
        assert isinstance(dialog, SignatureDrawingDialogV317)
        dialog.name_edit.setText('Firma de prueba')
        dialog.pad.add_stroke([(20, 70), (70, 20), (120, 80), (200, 45)])
        dialog.accept()
        return QDialog.Accepted
    monkeypatch.setattr(window, '_exec_edit_dialog', capture)
    window._create_signature_v317()
    assert window.signature_list_v317.count() == 1
    item = window.signature_list_v317.currentItem()
    assert item.text() == 'Firma de prueba' and not item.icon().isNull()
    assert window.signature_library_v317.directory == local_data_directory(window.config_path)/'firmas'
    assert len(window.signature_library_v317.entries()) == 1
    assert not window.state and not window.busy


@pytest.mark.parametrize('rotation', [0, 90])
def test_drop_then_move_resize_rotate_delete_and_undo_preserves_original(
        qtbot, saving_window, tmp_path, rotation):
    window = saving_window
    source = source_pdf(tmp_path/'original.pdf', rotation)
    original = source.read_bytes()
    open_editing(qtbot, window, source)
    entry = add_saved(window)
    assert window._manual_signature_ready_v317()
    location = (170., 150.)
    window.canvas.centerOn(window.canvas.scene_rect((120, 100, 220, 200)).center())
    enter, drop = send_drop(window, location)
    assert enter.isAccepted() and drop.isAccepted()
    qtbot.waitUntil(lambda: window.state.get('history_index') == 1, timeout=30000)
    finished(qtbot, window)
    assert not window.state['preview'] and window.state['dirty']
    assert not window._combined_edit_v150
    image = window.canvas.selected_image()
    assert image and image['editable']
    center = ((image['rect'][0]+image['rect'][2])/2, (image['rect'][1]+image['rect'][3])/2)
    assert center == pytest.approx(location, abs=2/window.zoom)
    assert window.last_report['verified']

    rect = image['rect']
    moved = (rect[0]+15, rect[1]+20, rect[2]+15, rect[3]+20)
    window.transform_image(image['id'], moved)
    finished(qtbot, window)
    assert window.state['history_index'] == 2
    image = window.canvas.selected_image()
    assert image['rect'] == pytest.approx(moved, abs=.05)
    resized = (moved[0], moved[1], moved[0]+100, moved[1]+30)
    window.transform_image(image['id'], resized)
    finished(qtbot, window)
    assert window.state['history_index'] == 3
    image = window.canvas.selected_image()
    window.canvas.image_rotate_requested.emit(image['id'], 17.)
    finished(qtbot, window)
    assert window.state['history_index'] == 4 and window.last_report['verified']

    destination = tmp_path/'firma-manual.pdf'
    window.save_as(destination)
    finished(qtbot, window)
    reader = PdfReader(destination)
    assert not any(field.get('/FT') == '/Sig' for field in (reader.get_fields() or {}).values())
    with fitz.open(destination) as doc, fitz.open(stream=original, filetype='pdf') as before:
        assert doc[0].get_text() == before[0].get_text()
        assert doc[1].get_pixmap().samples == before[1].get_pixmap().samples
        assert len(doc[0].get_image_info()) == 1
        # The PNG's white thumbnail backing must never become a PDF background.
        assert doc.xref_get_key(doc[0].get_images()[0][0], 'SMask')[0] == 'xref'

    image = window.canvas.selected_image()
    window.canvas.image_delete_requested.emit(image['id'])
    finished(qtbot, window)
    assert not window.canvas.images and window.state['history_index'] == 5
    window.undo_action.trigger()
    finished(qtbot, window)
    assert len(window.canvas.images) == 1 and window.state['history_index'] == 4
    assert source.read_bytes() == original
    assert window.signature_library_v317.get(entry['id'])['name'] == 'Firma habitual'


def test_tagged_pdf_signature_is_editable_and_can_be_deleted(qtbot, saving_window, tmp_path):
    from pathlib import Path
    from tagged_corpus import audit_tagged
    window = saving_window
    original_path = Path(__file__).resolve().parents[1]/'examples/etiquetado.pdf'
    source = tmp_path/'etiquetado.pdf'
    source.write_bytes(original_path.read_bytes())
    original = source.read_bytes()
    open_editing(qtbot, window, source)
    assert window.state['tagged']
    # Obtain the document's real image inventory before comparing it with
    # the inventory after deleting the added signature. It is lazy in v318.
    window.image_mode_action.trigger()
    qtbot.waitUntil(lambda: not window.busy and
                   getattr(window,'_inventory_ready_v318',{}).get('images',False),timeout=30000)
    original_image_count = len(window.canvas.images)
    entry = add_saved(window)
    assert window._drop_signature_v317(entry['id'], (170, 220), window._signature_context_v317())
    finished(qtbot, window)
    assert window.state['history_index'] == 1
    image = window.canvas.selected_image()
    assert image and image['editable']
    window.canvas.image_rotate_requested.emit(image['id'], 12.)
    finished(qtbot, window)
    assert window.state['history_index'] == 2
    window.canvas.setFocus()
    qtbot.keyClick(window.canvas, Qt.Key_Delete)
    finished(qtbot, window)
    assert window.state['history_index'] == 3 and len(window.canvas.images) == original_image_count
    destination = tmp_path/'sin-firma.pdf'
    window.save_as(destination)
    finished(qtbot, window)
    before, after = audit_tagged(original), audit_tagged(destination.read_bytes())
    for key in ('reading_order', 'content', 'objrs'):
        assert after[key] == before[key]
    assert source.read_bytes() == original


def test_click_placement_cancel_and_stale_drop_do_not_change_document(qtbot, saving_window, tmp_path):
    window = saving_window
    open_editing(qtbot, window, source_pdf(tmp_path/'click.pdf'))
    entry = add_saved(window)
    context = window._signature_context_v317()
    window._begin_manual_signature_v317()
    assert window.canvas.placement_mode
    window.cancel()
    assert not window.canvas.placement_mode and window._placing_signature_v317 is None
    assert window.state['history_index'] == 0
    assert not window._drop_signature_v317(entry['id'], (100, 120), ('another-session', *context[1:]))
    assert not window._drop_signature_v317(entry['id'], (-10, 120), context)
    window._begin_manual_signature_v317()
    point = window.canvas.viewport_point((170, 150))
    qtbot.mouseClick(window.canvas.viewport(), Qt.LeftButton, pos=point)
    finished(qtbot, window)
    assert window.state['history_index'] == 1
    assert not window.canvas.placement_mode and window._placing_signature_v317 is None


def test_certificate_shortcuts_keep_the_selected_mode_through_read_queue(
        qtbot, saving_window, tmp_path, monkeypatch):
    window = saving_window
    open_editing(qtbot, window, source_pdf(tmp_path/'digital.pdf'))
    modes = []
    monkeypatch.setattr(window, '_choose_signature_certificate',
                        lambda listing, *, visible=None: modes.append(visible))
    def submit(command, payload=None, callback=None):
        assert command == 'list_signing_certificates'
        callback({'certificates': [], 'pages': []})
        return True
    monkeypatch.setattr(window, '_submit', submit)
    window.visible_signature_action_v317.trigger()
    qtbot.waitUntil(lambda: len(modes) == 1)
    window.invisible_signature_action_v317.trigger()
    qtbot.waitUntil(lambda: len(modes) == 2)
    assert modes == [True, False]
