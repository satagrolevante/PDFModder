"""Synthetic Form instances: one occurrence edited, original resources retained."""
import pymupdf as fitz
import pytest
from pypdf import PdfReader
from io import BytesIO

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.form_instances_v200 import isolate_selected_forms
from pdfmodder.model import EditRequest, EditError


def form_document():
    with fitz.open() as artwork, fitz.open() as doc:
        source = artwork.new_page(width=220, height=100)
        source.draw_rect(fitz.Rect(0, 0, 220, 100), color=(.2,.5,.2), fill=(.9, .95, .8))
        source.insert_text((20, 45), 'Fecha 2025', fontsize=11)
        page = doc.new_page(width=500, height=350)
        page.show_pdf_page(fitz.Rect(20, 20, 240, 120), artwork, 0)
        page.show_pdf_page(fitz.Rect(250, 180, 470, 280), artwork, 0)
        page.insert_text((30, 320), 'Vecino intacto', fontsize=10, fontname='cour')
        doc.new_page(width=500, height=350).show_pdf_page(fitz.Rect(20,20,240,120), artwork, 0)
        return doc.tobytes()


def selection(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
        occurrence = next(i for i in range(len(model.glyphs)-3)
                          if ''.join(g.text for g in model.glyphs[i:i+4]) == '2025')
        return model, tuple(g.id for g in model.glyphs[occurrence:occurrence+4])


def test_isolation_preserves_pixels_vectors_and_second_page():
    data = form_document()
    model, ids = selection(data)
    isolated, request, report = isolate_selected_forms(data, EditRequest(0, ids, text='2026', revision=model.revision))
    assert report['shared_objects_unchanged'] and report['selected_instance_count'] == 1
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=isolated, filetype='pdf') as after:
        assert before[0].get_pixmap(matrix=fitz.Matrix(2,2)).samples == after[0].get_pixmap(matrix=fitz.Matrix(2,2)).samples
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert after[0].get_text().count('2025') == 2
        assert len(before[0].get_drawings()) == len(after[0].get_drawings())
    assert request.revision != model.revision


def test_edit_one_form_occurrence_and_reopen():
    data = form_document()
    model, ids = selection(data)
    changed, report = edit_pdf(data, EditRequest(0, ids, text='2026', revision=model.revision))
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=changed, filetype='pdf') as after:
        assert after[0].get_text().count('2026') == 1
        assert after[0].get_text().count('2025') == 1
        assert 'Vecino intacto' in after[0].get_text()
        assert after[1].get_pixmap().samples == before[1].get_pixmap().samples
    assert '2026' in PdfReader(BytesIO(changed)).pages[0].extract_text()
    assert report['form_isolation']['shared_objects_unchanged']


def test_group_form_reports_local_limit():
    data = form_document()
    with fitz.open(stream=data, filetype='pdf') as doc:
        first = doc[0].get_xobjects()[0][0]
        doc.xref_set_key(first, 'Group', '<< /S /Transparency /I true >>')
        data = doc.tobytes()
    model, ids = selection(data)
    with pytest.raises(EditError, match='/Group'):
        isolate_selected_forms(data, EditRequest(0, ids, text='2026'))


def test_direct_text_on_form_page_is_not_globally_blocked():
    data = form_document()
    model, _ = selection(data)
    assert not any('Form XObjects' in issue for issue in model.issues)
    direct = tuple(g.id for g in model.glyphs if g.origin[1] > 300)
    assert isolate_selected_forms(data, EditRequest(0, direct, text='Vecino entero')) is None
    changed, _ = edit_pdf(data, EditRequest(0, direct, text='Vecino entero', auto_width=True))
    with fitz.open(stream=changed, filetype='pdf') as doc:
        assert 'Vecino entero' in doc[0].get_text()
        assert doc[0].get_text().count('2025') == 2


def test_move_form_word_only_once():
    data = form_document()
    model, ids = selection(data)
    changed, _ = edit_pdf(data, EditRequest(0, ids, dx=5, dy=10, revision=model.revision))
    with fitz.open(stream=changed, filetype='pdf') as doc:
        after = extract_page(doc, 0, changed)
        for old in model.selected(ids):
            assert any(g.text == old.text and abs(g.origin[0]-old.origin[0]-5)<.035
                       and abs(g.origin[1]-old.origin[1]-10)<.035 for g in after.glyphs)
        assert doc[0].get_text().count('2025') == 2
