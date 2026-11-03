"""Mouse stroke capture, undo and transparent export, without PDF work."""
from io import BytesIO

from PIL import Image
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from pdfmodder.signature_draw_ui_v317 import SignatureDrawingDialogV317, SignatureDrawingPadV317


def test_mouse_capture_undo_and_clear(qtbot):
    pad = SignatureDrawingPadV317()
    qtbot.addWidget(pad)
    pad.show()
    qtbot.mousePress(pad, Qt.LeftButton, pos=QPoint(30, 70))
    qtbot.mouseMove(pad, QPoint(110, 40))
    qtbot.mouseRelease(pad, Qt.LeftButton, pos=QPoint(180, 95))
    assert pad.has_ink()
    with Image.open(BytesIO(pad.png_data())) as image:
        assert image.mode == 'RGBA'
        assert image.getchannel('A').getextrema() == (0, 255)
        assert all(image.getchannel(channel).getextrema() == (0, 0) for channel in 'RGB')
    pad.add_stroke([(220, 70), (260, 45)])
    assert len(pad._strokes) == 2
    pad.undo_stroke()
    assert len(pad._strokes) == 1
    pad.clear()
    assert not pad.has_ink()
    with pytest.raises(ValueError):
        pad.png_data()


def test_dialog_requires_name_and_ink_and_returns_named_png(qtbot):
    dialog = SignatureDrawingDialogV317()
    qtbot.addWidget(dialog)
    dialog.show()
    save = dialog.buttons.button(QDialogButtonBox.Save)
    assert not save.isEnabled() and not dialog.undo_button.isEnabled()
    dialog.name_edit.setText('  Mi firma ')
    assert not save.isEnabled()
    dialog.pad.add_stroke([(25, 110), (80, 25), (150, 100)])
    assert save.isEnabled() and dialog.undo_button.isEnabled()
    name, png = dialog.signature_data()
    assert name == 'Mi firma' and png.startswith(b'\x89PNG')
    before = png
    dialog.resize(dialog.width() + 250, dialog.height() + 60)
    assert dialog.signature_data()[1] == before
    dialog.accept()
    assert dialog.result() == QDialog.Accepted


def test_dialog_clear_restores_empty_state(qtbot):
    dialog = SignatureDrawingDialogV317()
    qtbot.addWidget(dialog)
    dialog.name_edit.setText('Firma')
    dialog.pad.add_stroke([(10, 40), (100, 20)])
    dialog.clear_button.click()
    assert not dialog.buttons.button(QDialogButtonBox.Save).isEnabled()
    dialog.accept()
    assert dialog.result() != QDialog.Accepted and 'Dibuja' in dialog.message.text()
