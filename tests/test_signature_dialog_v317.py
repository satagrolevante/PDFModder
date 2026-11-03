"""Visible certificate stamps may use a saved drawing; invisible signatures never do."""
from io import BytesIO

from PIL import Image, ImageDraw

from pdfmodder.signing_ui import SignatureDialog, SigningUiMixin
from test_signature_ui import CERTIFICATE, PAGES, png


def drawing():
    image = Image.new('RGBA', (180, 60), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(5, 40), (30, 7), (55, 45), (90, 14), (170, 28)],
                             fill=(0, 0, 0, 255), width=3)
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def signature_dialog(qtbot, **options):
    dialog = SignatureDialog(certificates=[CERTIFICATE], pages=PAGES,
        manual_signatures=[{'id': 'example', 'name': 'Firma habitual', 'png': drawing()}],
        **options)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_saved_drawing_is_optional_and_never_added_to_invisible_signature(qtbot):
    dialog = signature_dialog(qtbot, visible=True)
    assert dialog.visible_signature.isChecked()
    assert 'visible' in dialog.windowTitle()
    assert 'manual_signature_png' not in dialog.appearance()
    dialog.manual_signature.setCurrentIndex(1)
    assert dialog.appearance()['manual_signature_png'] == drawing()
    assert not dialog.manual_signature_preview.pixmap().isNull()
    # Black ink remains readable even when the interface changes the label's background.
    assert dialog.manual_signature_preview.pixmap().toImage().pixelColor(0, 0).name() == '#ffffff'
    assert dialog.manual_signature.itemIcon(1).pixmap(100, 36).toImage().pixelColor(0, 0).name() == '#ffffff'
    options = dialog.signing_options()
    assert options['certificate_thumbprint'] == CERTIFICATE['thumbprint']
    assert options['visible_signature']['manual_signature_png'] == drawing()
    dialog.visible_signature.setChecked(False)
    assert dialog.signing_options()['visible_signature'] is None
    assert not dialog.appearance_options.isVisible()
    dialog.visible_signature.setChecked(True)
    assert dialog.appearance()['manual_signature_png'] == drawing()


def test_changing_saved_drawing_invalidates_pending_certificate_preview(qtbot):
    dialog = signature_dialog(qtbot, visible=True)
    requests = []
    dialog.preview_requested.connect(lambda options, revision: requests.append((options, revision)))
    dialog.preview_button.click()
    revision = requests[0][1]
    assert 'manual_signature_png' not in requests[0][0]['visible_signature']
    dialog.manual_signature.setCurrentIndex(1)
    dialog.receive_preview({'png': png(), 'appearance_png': png()}, revision)
    assert dialog._preview_result is None
    assert 'cambiaron' in dialog.message.text()
    dialog.preview_button.click()
    assert requests[-1][0]['visible_signature']['manual_signature_png'] == drawing()
    dialog.receive_preview({'png': png(), 'appearance_png': png()}, requests[-1][1])
    assert dialog._preview_result is not None
    dialog.manual_signature.setCurrentIndex(0)
    assert dialog._preview_result is None


def test_invisible_entry_opens_without_stamp_and_can_be_changed_explicitly(qtbot):
    dialog = signature_dialog(qtbot, visible=False)
    assert dialog.signing_options()['visible_signature'] is None
    assert 'invisible' in dialog.windowTitle()
    dialog.visible_signature.setChecked(True)
    assert dialog.appearance() is not None


def test_explicit_visible_entry_does_not_silently_fall_back_to_invisible():
    class Window(SigningUiMixin):
        def _error(self, message):
            self.error = message
    window = Window()
    window._choose_signature_certificate({'visible_signature_error': 'Sello incompatible con este PDF'},
                                         visible=True)
    assert window.error == 'Sello incompatible con este PDF'
