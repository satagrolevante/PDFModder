"""Print intent and cancellable bounded batches preserve the PDF snapshot."""
from hashlib import sha256
from pathlib import Path

import pymupdf as fitz
import pytest

from pdfmodder.draft_control_v305 import DraftControl
from pdfmodder.editor_tools_v200 import install_editor_tools_v200
from pdfmodder.model import EditError
from pdfmodder.printing_render_v314 import print_annotation_page_v314
from pdfmodder.worker import Session


@pytest.fixture(autouse=True)
def install_print_commands():
    install_editor_tools_v200(Session)


def make_pdf(path, count=1):
    with fitz.open() as document:
        for number in range(count):
            document.new_page(width=300, height=400).insert_text((30, 50), f'Page {number+1}')
        document.save(path)
    return path


def test_print_flags_include_print_only_and_exclude_hidden_annotations_and_widgets(tmp_path):
    source = tmp_path/'annotations.pdf'
    with fitz.open() as document:
        page = document.new_page(width=360, height=240)
        flags = (0, 4|32, 4, 4|2, 4|1)
        colors = ((1,0,0), (0,0,1), (0,1,0), (1,0,1), (1,.5,0))
        for index, (value, color) in enumerate(zip(flags, colors)):
            rect = fitz.Rect(10+65*index, 10, 50+65*index, 50)
            annotation = page.add_rect_annot(rect)
            annotation.set_colors(stroke=color, fill=color)
            annotation.update()
            annotation.set_flags(value)
        for index, (value, color) in enumerate(zip((0,4|32,4|2), colors)):
            widget = fitz.Widget()
            widget.field_name = f'field{index}'
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect = fitz.Rect(10+65*index, 100, 50+65*index, 140)
            widget.field_value = 'X'
            widget.fill_color = color
            widget.text_color = (0,0,0)
            page.add_widget(widget)
            xref = page.annot_xrefs()[-1][0]
            document.xref_set_key(xref, 'F', str(value))
        document.save(source)
    original = source.read_bytes()
    with fitz.open(stream=original, filetype='pdf') as document:
        page = document[0]
        appearances = {xref: document.xref_get_key(xref, 'AP') for xref, *_ in page.annot_xrefs()}
        page = print_annotation_page_v314(document, page)
        assert appearances == {xref: document.xref_get_key(xref, 'AP') for xref in appearances}
    session = Session(source, reading=True, history_dir=tmp_path/'history')
    try:
        rendered = session.print_pages_v200([0], 72, revision=sha256(original).hexdigest())
        image = fitz.Pixmap(rendered['pages'][0]['path'])
        assert [image.pixel(30+65*i, 30) for i in range(5)] == [
            (255,255,255), (0,0,255), (0,255,0), (255,255,255), (255,255,255)]
        assert [image.pixel(46+65*i, 104) for i in range(3)] == [
            (255,255,255), (0,0,255), (255,255,255)]
        assert session.history.current == original and session.history.index == 0
        assert source.read_bytes() == original
    finally:
        session.close()


def test_direct_annotation_dictionaries_have_print_flags_applied(tmp_path):
    source = tmp_path/'direct.pdf'
    with fitz.open() as document:
        page = document.new_page(width=180, height=100)
        references = []
        for rect, color, flags in ((fitz.Rect(10,10,60,60),(1,0,0),0),
                                   (fitz.Rect(90,10,140,60),(0,0,1),36)):
            annotation = page.add_rect_annot(rect)
            annotation.set_colors(stroke=color, fill=color)
            annotation.update()
            annotation.set_flags(flags)
            references.append(document.xref_object(annotation.xref, compressed=True))
        document.xref_set_key(page.xref, 'Annots', '['+' '.join(references)+']')
        assert all(xref == 0 for xref, *_ in page.annot_xrefs())
        document.save(source)
    original = source.read_bytes()
    session = Session(source, reading=True, history_dir=tmp_path/'history')
    try:
        result = session.print_pages_v200([0], 72)
        image = fitz.Pixmap(result['pages'][0]['path'])
        assert image.pixel(30,30) == (255,255,255)
        assert image.pixel(110,30) == (0,0,255)
        assert source.read_bytes() == original
    finally:
        session.close()


def test_cancelled_ticket_never_renders_or_changes_history(tmp_path, monkeypatch):
    session = Session(make_pdf(tmp_path/'source.pdf', 3), reading=True, history_dir=tmp_path/'history')
    channel = DraftControl()
    try:
        ticket = channel.ticket()
        channel.invalidate()
        original = session.history.current
        monkeypatch.setattr(fitz.Page, 'get_pixmap', lambda *a, **k: pytest.fail('Cancelled render started'))
        result = session.print_pages_v200([0,1,2], 72, control=ticket)
        assert result['print_cancelled_v314'] is True and result['pages'] == []
        assert session.history.current == original and session.history.index == 0
        assert getattr(session, '_print_folder_v200', None) is None
    finally:
        channel.close()
        session.close()


def test_cancellation_during_render_stops_before_remaining_pages_and_cleans_files(tmp_path, monkeypatch):
    session = Session(make_pdf(tmp_path/'source.pdf', 20), reading=True, history_dir=tmp_path/'history')
    channel = DraftControl()
    rendered = []
    original = fitz.Page.get_pixmap
    def render(page, *args, **kwargs):
        pixmap = original(page, *args, **kwargs)
        rendered.append(page.number)
        if len(rendered) == 2:
            channel.invalidate()
        return pixmap
    monkeypatch.setattr(fitz.Page, 'get_pixmap', render)
    try:
        snapshot = session.history.current
        result = session.print_pages_v200(list(range(20)), 72, control=channel.ticket())
        assert result['print_cancelled_v314'] and result['pages'] == []
        assert rendered == [0,1]
        assert session._print_folder_v200 is None
        assert session.history.current == snapshot and session.history.index == 0
    finally:
        channel.close()
        session.close()


def test_batches_require_exact_revision_and_release_previous_images(tmp_path):
    session = Session(make_pdf(tmp_path/'source.pdf', 10), reading=True, history_dir=tmp_path/'history')
    try:
        revision = sha256(session.history.current).hexdigest()
        first = session.print_pages_v200([0], 72, revision=revision)
        assert 'layout_page_v314' not in first
        first_path = Path(first['pages'][0]['path'])
        assert first_path.is_file() and len(first['pages']) == 1
        with pytest.raises(EditError, match='documento cambió'):
            session.print_pages_v200([1], 72, revision='stale')
        assert first_path.is_file(), 'Stale jobs must not delete a usable prepared batch'
        second = session.print_pages_v200([1], 72, revision=revision)
        assert not first_path.exists()
        assert Path(second['pages'][0]['path']).is_file()
        assert second['revision'] == revision and len(second['pages']) == 1
    finally:
        session.close()


def test_preview_geometry_uses_first_selected_page_without_rendering_it(tmp_path, monkeypatch):
    source = tmp_path/'mixed.pdf'
    with fitz.open() as document:
        document.new_page(width=300, height=400)
        document.new_page(width=550, height=250)
        document.save(source)
    session = Session(source, reading=True, history_dir=tmp_path/'history')
    rendered=[]
    original=fitz.Page.get_pixmap
    def render(page, *args, **kwargs):
        rendered.append(page.number)
        return original(page, *args, **kwargs)
    monkeypatch.setattr(fitz.Page, 'get_pixmap', render)
    try:
        result=session.print_pages_v200([1], 72, layout_page=0)
        assert result['layout_page_v314'] == {'page':0,'width':300.,'height':400.}
        assert result['pages'][0]['width'] == 550.
        assert result['pages'][0]['height'] == 250.
        assert rendered == [1]
        with pytest.raises(EditError, match='referencia para el papel'):
            session.print_pages_v200([1], 72, layout_page=2)
        assert rendered == [1]
    finally:
        session.close()


def test_owner_permission_rule_and_existing_quality_limit_remain_unchanged(tmp_path):
    restricted = tmp_path/'restricted.pdf'
    with fitz.open() as document:
        document.new_page()
        document.save(restricted, encryption=fitz.PDF_ENCRYPT_AES_256,
                      owner_pw='owner', user_pw='reader', permissions=fitz.PDF_PERM_COPY)
    session = Session(restricted, password='owner', reading=True, history_dir=tmp_path/'restricted-history')
    try:
        with pytest.raises(EditError, match='no permite imprimir'):
            session.print_pages_v200([0], 72)
    finally:
        session.close()
    source = tmp_path/'quality.pdf'
    with fitz.open() as document:
        document.new_page(width=595, height=842)
        document.save(source)
    session = Session(source, reading=True, history_dir=tmp_path/'quality-history')
    try:
        result = session.print_pages_v200([0], 600)
        page = result['pages'][0]
        assert page['dpi'] == round((24_000_000/(595*842))**.5*72, 1)
        image = fitz.Pixmap(page['path'])
        assert image.n == 3 and image.alpha == 0
        assert 24_000_000 <= image.width*image.height < 24_020_000
    finally:
        session.close()
