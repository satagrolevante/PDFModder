"""Windows action refresh checks metadata, never reads/writes the real clipboard."""
from types import SimpleNamespace
import ctypes
import pytest

from pdfmodder import clipboard_formats_v200 as formats
from pdfmodder import clipboard_ui_v170 as ui


class Action:
    def setEnabled(self,value):self.enabled=bool(value)


class ClipboardWindow(ui.ClipboardUiV170Mixin):
    def __init__(self,target=None):
        self.target=target;self._closed=False
        for name in ('copy','cut','paste','delete'):setattr(self,name+'_action_v170',Action())
        self.canvas=SimpleNamespace(ids=[1],selected_image=lambda:None)
    def _native_clipboard_target_v170(self):return self.target
    def _clipboard_ready_v170(self,editing=False):return True


def forbid_clipboard():
    pytest.fail('Refreshing action state must not query the external Qt clipboard provider')


@pytest.mark.parametrize('available_format',[1,13,2,8,17,0xC001,0xC002,None])
def test_windows_detects_text_images_custom_or_empty_without_qt_provider(monkeypatch,available_format):
    queried=[]
    monkeypatch.setattr(formats,'sys',SimpleNamespace(platform='win32'))
    def available(code):queried.append(code);return code==available_format
    monkeypatch.setattr(formats,'_windows_probe_v200',lambda:(available,(1,13,2,8,17,0xC001,0xC002)))
    monkeypatch.setattr(ui,'QApplication',SimpleNamespace(clipboard=forbid_clipboard))
    window=ClipboardWindow();window._refresh_clipboard_v170()
    assert window.paste_action_v170.enabled is (available_format is not None)
    assert window.copy_action_v170.enabled and window.cut_action_v170.enabled and window.delete_action_v170.enabled
    assert queried


@pytest.mark.parametrize('error',[OSError('Metadata API unavailable'),AttributeError('Unavailable user32')])
def test_windows_metadata_failure_does_not_fall_back_to_ole(monkeypatch,error):
    monkeypatch.setattr(formats,'sys',SimpleNamespace(platform='win32'))
    def unavailable():raise error
    monkeypatch.setattr(formats,'_windows_probe_v200',unavailable)
    monkeypatch.setattr(ui,'QApplication',SimpleNamespace(clipboard=forbid_clipboard))
    window=ClipboardWindow();window._refresh_clipboard_v170()
    assert window.paste_action_v170.enabled  # Explicit Paste will validate data when requested.


def test_windows_native_text_input_refresh_preserves_selection_and_read_only_rules(monkeypatch):
    monkeypatch.setattr(formats,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(formats,'_windows_probe_v200',lambda:(lambda value:value==13,(1,13)))
    monkeypatch.setattr(ui,'QApplication',SimpleNamespace(clipboard=forbid_clipboard))
    target=SimpleNamespace(textCursor=lambda:SimpleNamespace(hasSelection=lambda:True),isReadOnly=lambda:True)
    window=ClipboardWindow(target);window._refresh_clipboard_v170()
    assert window.copy_action_v170.enabled
    assert not window.cut_action_v170.enabled and not window.paste_action_v170.enabled and not window.delete_action_v170.enabled


def test_native_probe_registers_qt_custom_and_png_names_without_getting_data(monkeypatch):
    registered=[]
    class Function:
        def __init__(self,callback):self.callback=callback
        def __call__(self,value):return self.callback(value)
    user32=SimpleNamespace(
        IsClipboardFormatAvailable=Function(lambda value:False),
        RegisterClipboardFormatW=Function(lambda name:(registered.append(name),0xC000+len(registered))[1]))
    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kwargs:user32,raising=False)
    formats._windows_probe_v200.cache_clear()
    try:
        available,numbers=formats._windows_probe_v200()
        assert registered==['application/x-pdfmodder-object-v1','PNG']
        assert numbers==(1,13,2,8,17,0xC001,0xC002)
        assert available is user32.IsClipboardFormatAvailable
        # Cached registration prevents repeated initialization on each refresh.
        assert formats._windows_probe_v200()==(available,numbers)
        assert len(registered)==2
    finally:formats._windows_probe_v200.cache_clear()
