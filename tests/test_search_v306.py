"""Read-only search returns contextual occurrences, not merged paint boxes."""
from pathlib import Path

import pymupdf as fitz
import pytest

from pdfmodder.draft_control_v305 import DraftCancelled, DraftControl, controlled_draft
from pdfmodder.model import EditError
from pdfmodder.search_v306 import search_document


FONT = Path(__file__).resolve().parents[1] / 'assets/fonts/Vera.ttf'


def add_text(page, text, point=(40, 60), *, unicode=False):
    options = {'fontname': 'SearchTest', 'fontfile': str(FONT)} if unicode else {}
    page.insert_text(point, text, fontsize=11, **options)


def assert_context(match):
    assert match['context'][match['context_start']:match['context_end']] == match['text']
    assert '\x00' not in match['context']
    assert match['rects']
    for rect in match['rects']:
        assert fitz.Rect(match['rect']).contains(fitz.Rect(rect))


def test_counts_actual_adjacent_occurrences_and_preserves_pdf():
    with fitz.open() as document:
        add_text(document.new_page(), 'SOL SOL SOLSOL and sol')
        add_text(document.new_page(), 'Second page SOL')
        original = document.tobytes()
    with fitz.open(stream=original, filetype='pdf') as document:
        matches = search_document(document, 'SOL')
        assert len(matches) == 6
        assert [m['page'] for m in matches] == [0] * 5 + [1]
        # MuPDF joins SOLSOL into a single result rectangle. Every SOL must be
        # a separate selectable occurrence, including the adjacent pair.
        assert matches[2]['rect'][2] <= matches[3]['rect'][0] + .01
        assert len(search_document(document, 'SOL', case_sensitive=True)) == 5
        assert len(search_document(document, 'SOL', whole_word=True)) == 4
        assert document.tobytes(no_new_id=True) == original
        assert not document.is_dirty
        for match in matches:
            assert_context(match)


def test_literal_punctuation_and_empty_query():
    with fitz.open() as document:
        page = document.new_page()
        add_text(page, 'a+b@example.org, a.b, a+b@example.org')
        assert len(search_document(document, 'a+b@example.org')) == 2
        assert len(search_document(document, 'a.b')) == 1
        assert not search_document(document, '')
        assert not search_document(document, ' \t\n ')


def test_phrase_across_lines_is_one_result_with_two_physical_fragments():
    with fitz.open() as document:
        add_text(document.new_page(), 'La fecha de\nrevision prevista es hoy.')
        matches = search_document(document, 'fecha de revision')
        assert len(matches) == 1
        assert len(matches[0]['rects']) == 2
        assert matches[0]['text'] == 'fecha de revision'
        assert_context(matches[0])


def test_dehyphenated_word_counts_once_with_both_highlights():
    with fitz.open() as document:
        add_text(document.new_page(), 'La responsa-\nbilidad compartida.')
        matches = search_document(document, 'responsabilidad')
        assert len(matches) == 1
        assert len(matches[0]['rects']) == 2
        assert matches[0]['text'] == 'responsabilidad'
        assert_context(matches[0])


def test_two_columns_on_same_baseline_do_not_form_a_false_phrase():
    with fitz.open() as document:
        page = document.new_page()
        add_text(page, 'LEFT', (40, 60))
        add_text(page, 'RIGHT', (320, 60))
        assert not search_document(document, 'LEFT RIGHT')
        matches = search_document(document, 'RIGHT')
        assert len(matches) == 1
        assert matches[0]['context'].replace('…', '') == 'RIGHT'
        assert_context(matches[0])


def test_unicode_case_ligature_and_casefold_expansions():
    with fitz.open() as document:
        page = document.new_page()
        add_text(page, 'Información INFORMACIÓN ﬁnal Straße', unicode=True)
        assert len(search_document(document, 'información')) == 2
        assert len(search_document(document, 'Información', case_sensitive=True)) == 1
        ligature = search_document(document, 'final')
        assert len(ligature) == 1 and ligature[0]['text'] == 'final'
        street = search_document(document, 'STRASSE')
        assert len(street) == 1 and street[0]['text'] == 'Straße'
        assert_context(ligature[0])
        assert_context(street[0])
        # One lowercase s matches the initial S, never either half of ß→ss.
        assert len(search_document(document, 's')) == 1


def test_noncomposing_combining_mark_is_part_of_a_whole_word():
    font = FONT.with_name('LiberationSans-Regular.ttf')
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((40, 60), 'x\u0304 x e\u0301', fontname='CombiningTest', fontfile=str(font))
        assert len(search_document(document, 'x')) == 2
        whole = search_document(document, 'x', whole_word=True)
        assert len(whole) == 1
        assert_context(whole[0])
        canonical = search_document(document, 'é')
        assert len(canonical) == 1 and canonical[0]['text'] == 'é'
        assert_context(canonical[0])


def test_rotated_cropbox_uses_visible_unrotated_page_coordinates():
    with fitz.open() as document:
        page = document.new_page(width=500, height=500)
        add_text(page, 'outside', (20, 30))
        add_text(page, 'visible', (150, 180))
        page.set_cropbox(fitz.Rect(100, 100, 450, 450))
        page.set_rotation(90)
        matches = search_document(document, 'visible')
        assert len(matches) == 1
        assert matches[0]['rect'] == pytest.approx(tuple(page.search_for('visible')[0]), abs=.001)
        assert not search_document(document, 'outside')


def test_context_offsets_remain_exact_when_snippet_is_truncated():
    with fitz.open() as document:
        page = document.new_page(width=1800)
        add_text(page, 'prefijo ' * 14 + 'OBJETIVO ' + 'final ' * 22)
        match = search_document(document, 'OBJETIVO')[0]
        assert match['context'].startswith('…') and match['context'].endswith('…')
        assert_context(match)


def test_obsolete_search_cancels_before_native_extraction():
    channel = DraftControl()
    ticket = channel.ticket()
    channel.invalidate()
    try:
        with fitz.open() as document:
            add_text(document.new_page(), 'needle')
            with pytest.raises(DraftCancelled):
                with controlled_draft(ticket):
                    search_document(document, 'needle')
            assert len(search_document(document, 'needle')) == 1
    finally:
        channel.close()


def test_obsolete_search_cancels_between_pages(monkeypatch):
    from pdfmodder import search_v306
    channel = DraftControl()
    ticket = channel.ticket()
    actual_checkpoint = search_v306.checkpoint
    calls = []

    def checkpoint():
        calls.append(True)
        if len(calls) == 2:
            channel.invalidate()
        actual_checkpoint()

    monkeypatch.setattr(search_v306, 'checkpoint', checkpoint)
    try:
        with fitz.open() as document:
            for _ in range(3):
                add_text(document.new_page(), 'needle')
            with pytest.raises(DraftCancelled):
                with controlled_draft(ticket):
                    search_document(document, 'needle')
            assert len(calls) == 2
    finally:
        channel.close()


def test_existing_invisible_ocr_remains_searchable_without_modification():
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((40, 60), 'correo@example.org', render_mode=3)
        matches = search_document(document, 'correo@example.org')
        assert len(matches) == 1
        assert_context(matches[0])


@pytest.mark.parametrize('query', [None, 'x' * 4097, '\x00needle'])
def test_invalid_query_has_readable_error(query):
    with fitz.open() as document:
        with pytest.raises(EditError):
            search_document(document, query)
