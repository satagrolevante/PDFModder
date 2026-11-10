"""Startup must not probe remote recent files or decode hidden libraries."""
import json
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt

from pdfmodder.app import MainWindow
from pdfmodder.manual_signatures_v317 import SignatureLibraryV317
from pdfmodder.workspace_ui_v170 import RecentFilesStore


ROOT = Path(__file__).resolve().parents[1]


def window(qtbot, tmp_path):
    widget=MainWindow(config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    qtbot.addWidget(widget,before_close_func=lambda w:setattr(w,'_allow_close',True))
    return widget


def test_window_construction_and_recent_open_never_probe_stored_pdf_paths(qtbot, tmp_path, monkeypatch):
    paths=[str(tmp_path/'offline-share'/f'archived-{n}.pdf') for n in range(25)]
    (tmp_path/'recent_files.json').write_text(json.dumps({'schema':1,'files':[{'path':p} for p in paths]}))
    probes=[]
    for name in ('stat','is_file','exists','resolve'):
        original=getattr(Path,name)
        def watched(path,*args,_original=original,_name=name,**kwargs):
            if 'offline-share' in str(path):
                probes.append((_name,str(path)))
                raise AssertionError('GUI probed a potentially offline PDF')
            return _original(path,*args,**kwargs)
        monkeypatch.setattr(Path,name,watched)
    widget=window(qtbot,tmp_path)
    assert widget.recent_files_v170.count()==25
    assert widget.recent_files_v170.item(0).data(Qt.UserRole)==paths[0]
    opened=[]
    monkeypatch.setattr(widget,'_confirm_discard',lambda:True)
    monkeypatch.setattr(widget,'open_document',lambda path:opened.append(path))
    widget._open_recent_v170(widget.recent_files_v170.item(0))
    assert opened==[paths[0]] and probes==[]
    # Opening was already validated by the worker: refreshing the local list
    # must not re-resolve or stat that remote path on the GUI thread either.
    widget.recent_open(paths[-1])
    assert probes==[] and widget.recent_files_v170.item(0).data(Qt.UserRole)==paths[-1]


def test_signature_library_is_read_only_when_its_section_is_opened(qtbot, tmp_path, monkeypatch):
    reads=[]
    original=SignatureLibraryV317.entries
    def listed(library):
        reads.append(library.directory)
        return original(library)
    monkeypatch.setattr(SignatureLibraryV317,'entries',listed)
    widget=window(qtbot,tmp_path)
    assert not reads and not widget._signatures_loaded_v322
    assert not widget.signature_tools_section_v317.header.isChecked()
    widget.signature_tools_section_v317.set_expanded(True)
    assert len(reads)==1 and widget._signatures_loaded_v322
    widget.signature_tools_section_v317.set_expanded(False)
    widget.signature_tools_section_v317.set_expanded(True)
    assert len(reads)==1


def test_empty_recovery_worker_target_imports_no_ui_or_pdf_engines(tmp_path):
    script='''import json,sys
from pdfmodder.worker_entry_v322 import dispatch_pdf_worker
result=dispatch_pdf_worker('list_recovery',{'recovery_root':sys.argv[1]})
bad=[name for name in sys.modules if name.startswith(('PySide6','pymupdf','pypdf','numpy','PIL','cryptography')) or name in ('pdfmodder.app','pdfmodder.worker')]
print(json.dumps({'result':result,'unexpected':bad}))
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path/'recovery')],cwd=ROOT,
                          capture_output=True,text=True,timeout=15,check=True)
    report=json.loads(result.stdout)
    assert report=={'result':{'entries':[]},'unexpected':[]}


def test_recent_store_still_validates_unopened_files(tmp_path):
    store=RecentFilesStore(tmp_path/'recent.json')
    assert not store.add(tmp_path/'missing.pdf')
    text=tmp_path/'not-a-pdf.txt';text.write_text('plain text')
    assert not store.add(text)
