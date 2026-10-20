from pathlib import Path

import pytest

from pdfmodder import office_conversion_v305 as office
from pdfmodder.draft_control_v305 import DraftControl
from pdfmodder import worker


def test_conversion_without_session_and_partial_failure(tmp_path, monkeypatch):
    sources = [str(tmp_path / name) for name in ('primero.docx', 'dañado.doc', 'tercero.docx')]
    calls = []

    def convert(source, destination=None, *, cancel=None):
        assert cancel() is False
        calls.append(source)
        if source == sources[1]:
            raise office.ConversionError('El documento está dañado.')
        return {'path': str(Path(source).with_suffix('.pdf')), 'source_unchanged': True}

    monkeypatch.setattr(office, 'convert_document_to_pdf', convert)
    monkeypatch.setattr(worker, '_session', None)
    report = worker.dispatch('convert_office', {'paths': sources})
    assert calls == sources
    assert [item['path'] for item in report['results']] == [str(Path(p).with_suffix('.pdf')) for p in (sources[0], sources[2])]
    assert report['errors'] == [{'source': sources[1], 'error': 'El documento está dañado.'}]
    assert report['cancelled'] is False
    assert worker._session is None


def test_cancel_between_documents_preserves_finished_pdf_and_session(tmp_path, monkeypatch):
    channel = DraftControl()
    ticket = channel.ticket()
    current = object()
    monkeypatch.setattr(worker, '_session', current)
    calls = []
    sources = [str(tmp_path / name) for name in ('one.docx', 'two.docx')]

    def convert(source, destination=None, *, cancel=None):
        calls.append(source)
        output = Path(source).with_suffix('.pdf')
        output.write_bytes(b'completed output')
        channel.invalidate()
        return {'path': str(output)}

    monkeypatch.setattr(office, 'convert_document_to_pdf', convert)
    try:
        result = worker.dispatch('convert_office', {'paths': sources, '_office_ticket': ticket})
    finally:
        channel.close()
    assert calls == sources[:1]
    assert result == {'results': [{'path': str(tmp_path / 'one.pdf')}], 'errors': [], 'cancelled': True}
    assert (tmp_path / 'one.pdf').read_bytes() == b'completed output'
    assert worker._session is current


def test_cancel_stops_running_conversion(tmp_path, monkeypatch):
    channel = DraftControl()
    ticket = channel.ticket()

    def convert(source, destination=None, *, cancel=None):
        channel.invalidate()
        assert cancel()
        raise office.ConversionCancelled('Cancelada')

    monkeypatch.setattr(office, 'convert_document_to_pdf', convert)
    try:
        result = worker.dispatch('convert_office', {'paths': [str(tmp_path / 'one.doc')], '_office_ticket': ticket})
    finally:
        channel.close()
    assert result == {'results': [], 'errors': [], 'cancelled': True}


def test_reading_mode_allows_office_without_enabling_pdf_edits():
    from pdfmodder.reading_ui_v171 import ReadingUiV171Mixin
    class Window(ReadingUiV171Mixin):
        application_mode = 'reading'
        def _notice(self, text):
            pass
    window = Window()
    assert window._reading_command_allowed_v171('convert_office')
    assert window._reading_command_allowed_v171('combine')
    assert not window._reading_command_allowed_v171('rich_preview')
