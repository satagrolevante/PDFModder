"""Run the exact frozen-capable smoke harness against the source MainWindow."""
from pathlib import Path
import multiprocessing
import os
import sys


def main():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    from PySide6.QtWidgets import QApplication
    from pdfmodder.app import MainWindow
    from pdfmodder.smoke_v200 import SmokeV200
    report=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'output'/'ui-v200'/'workspace-source.json'
    report.parent.mkdir(parents=True,exist_ok=True)
    history=report.parent/'history';history.mkdir(exist_ok=True)
    app=QApplication(sys.argv[:1]);app.setApplicationName('PDF Modder');app.setStyle('Fusion')
    window=MainWindow(config_path=report.parent/'fonts.json',history_dir=history)
    window.show()
    window._smoke=SmokeV200(window,root/'examples'/'digital.pdf',report)
    return app.exec()


if __name__=='__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
