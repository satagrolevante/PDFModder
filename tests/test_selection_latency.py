"""Text preflight reuses the current page and checks other operations on demand."""
from hashlib import sha256
from types import SimpleNamespace

import pymupdf as fitz
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QWidget

from pdfmodder.compatibility_v300 import selection_capabilities_v300
from pdfmodder.compatibility_ui_v300 import CompatibilityUiV300Mixin
from pdfmodder.worker import Session
from test_compatibility_v300 import document


def test_text_selection_does_not_probe_native_objects(monkeypatch):
    import pdfmodder.objects_v300 as objects
    _, ids, session = document()
    def unexpected(*args):
        raise AssertionError('Native object probes must wait for an object operation')
    monkeypatch.setattr(objects, 'object_graph', unexpected)
    result = selection_capabilities_v300(session, 0, ids, operation='text')
    assert result['status'] == 'available'
    assert result['operations']['move']['requires_check']
    assert result['object_id'] is None


def test_current_page_model_is_reused_without_another_document_check(tmp_path, monkeypatch):
    import pdfmodder.engine as engine
    import pdfmodder.validation as validation
    source, _, _ = document()
    path = tmp_path / 'selection.pdf'; path.write_bytes(source)
    session = Session(path, reading=True, history_dir=tmp_path)
    try:
        prepared = session.prepare_editing(0)
        model = prepared['model']
        ids = model.group(model.glyphs[0], 'word')
        def unexpected(*args):
            raise AssertionError('The worker already prepared this immutable page')
        monkeypatch.setattr(engine, 'extract_page', unexpected)
        checks = []; original = validation.document_issues
        def check(*args, **kwargs):
            checks.append(1); return original(*args, **kwargs)
        monkeypatch.setattr(validation, 'document_issues', check)
        result = selection_capabilities_v300(session, 0, ids, model.revision, operation='text')
        assert result['status'] == 'available'
        assert len(checks) == 1
    finally:
        session.close()


def test_cached_page_from_previous_revision_does_not_supply_current_font_evidence(monkeypatch):
    import pdfmodder.engine as engine
    source, ids, session = document()
    with fitz.open(stream=source, filetype='pdf') as doc:
        old_model = engine.extract_page(doc, 0, source)
        doc[0].insert_text((70, 150), 'Additional current content')
        changed = doc.tobytes()
    session._model_cache = {(sha256(source).hexdigest(), 0, False): (old_model, [], [], 0)}
    session.history.current = changed
    calls = []; original = engine.extract_page
    def extract(*args):
        calls.append(1); return original(*args)
    monkeypatch.setattr(engine, 'extract_page', extract)
    result = selection_capabilities_v300(session, 0, ids, operation='text')
    assert result['revision'] == sha256(changed).hexdigest()
    assert result['status'] == 'available' and len(calls) == 1


class Harness(CompatibilityUiV300Mixin, QWidget):
    def __init__(self):
        super().__init__()
        self.model = SimpleNamespace(revision='current')
        self.page_number = 0; self.canvas = SimpleNamespace(ids=[1, 2])
        self.busy = False; self._preflight_result_v200 = None
        self._preflight_pending_v200 = (0, 'current', (1, 2))
        self._start_edit_requested_v200 = None
        self._preflight_timer_v200 = QTimer(self)
        self._preflight_timer_v200.setSingleShot(True)
        self.capability_operation_v300 = QComboBox(self)
        for key in ('text', 'move'):
            self.capability_operation_v300.addItem(key, key)
        self.capability_operation_v300.currentIndexChanged.connect(self._capability_operation_changed_v300)
        self.requests = []

    def _show_capability_v300(self, *args): pass

    def _submit(self, command, payload, ready):
        self.requests.append((command, payload, ready))


def test_operation_chooser_requests_deferred_object_checks(qtbot):
    window = Harness(); qtbot.addWidget(window)
    window._pump_preflight_v200()
    assert window.requests[-1][1]['operation'] == 'text'
    window.requests[-1][2]({'operations': {'move': {'requires_check': True}}})
    window.capability_operation_v300.setCurrentIndex(1)
    assert window._preflight_pending_v200 == (0, 'current', (1, 2))
    window._pump_preflight_v200()
    assert window.requests[-1][1]['operation'] == 'move'


def test_old_operation_response_does_not_replace_new_choice(qtbot):
    window = Harness(); qtbot.addWidget(window)
    window._pump_preflight_v200()
    previous_ready = window.requests[-1][2]
    window.capability_operation_v300.setCurrentIndex(1)
    previous_ready({'operations': {'move': {'requires_check': True}}})
    assert window._preflight_result_v200 is None
    assert window._preflight_pending_v200 == (0, 'current', (1, 2))
