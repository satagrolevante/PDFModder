"""Diagnóstico acotado del bucle Qt Windows; no modifica los documentos del usuario."""
from pathlib import Path
import faulthandler
import json
import multiprocessing
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    target = ROOT / 'output/native-diagnostic-v200'
    target.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with (target / 'trace.log').open('w', encoding='utf-8') as trace:
        def mark(event, **values):
            trace.write(json.dumps(dict(seconds=round(time.perf_counter()-started, 3),
                                        event=event, **values), ensure_ascii=False)+'\n')
            trace.flush()
        faulthandler.enable(file=trace)
        faulthandler.dump_traceback_later(10, repeat=True, file=trace)
        mark('before_import', pid=os.getpid())
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from pdfmodder.app import main as app_main
        mark('after_import')
        app = QApplication([])
        mark('application_created', platform=app.platformName())
        heartbeat = QTimer()
        heartbeat.setInterval(1000)
        def tick():
            windows = [w for w in app.topLevelWidgets() if hasattr(w, 'future')]
            for w in windows:
                modal = app.activeModalWidget()
                mark('heartbeat', busy=w.busy, command=w._command,
                     future_done=w.future.done() if w.future else None,
                     modal=modal.windowTitle() if modal else None,
                     stage=getattr(getattr(w, '_smoke', None), 'stage', None))
        heartbeat.timeout.connect(tick)
        heartbeat.start()
        code = app_main(['--smoke-v200', str(target / 'smoke.json')])
        faulthandler.cancel_dump_traceback_later()
        mark('exit', code=code)
        return code


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
