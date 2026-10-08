"""Correctable scopes respect geometry, mixed styles and painted separators."""
from dataclasses import replace

import pytest

from pdfmodder.model import EditError, Glyph, PageModel
from pdfmodder.selection_v300 import (SelectionIndex, boundaries_from_drawings,
    draft_overflow, enlarged_area, selected_in_area, selection_index)


def glyphs(text, x, y, *, start=0, block=0, line=0, font='Helvetica', direction=(1., 0.), mode=0):
    result = []
    for offset, char in enumerate(text):
        if direction == (1., 0.):
            rect = (x+offset*6, y, x+offset*6+6, y+10)
        else:
            rect = (x, y+offset*6, x+10, y+offset*6+6)
        result.append(Glyph(start+offset, char, rect[:2], rect, rect,
                            font, 10., (0.,0.,0.), 1., block, line, 0,
                            direction=direction, mode=mode))
    return result


def model(groups, edges=()):
    return PageModel(0, 400., 300., 0, (1.,0.,0.,1.,0.,0.),
                     (1.,0.,0.,1.,0.,0.), (0.,0.,400.,300.),
                     [g for group in groups for g in group], selection_boundaries=list(edges))


def text(page, ids):
    return ''.join(g.text for g in page.selected(ids))


def test_words_and_lines_join_mixed_fonts_without_crossing_a_column_gap():
    first = glyphs('Mixto ', 10, 30)
    second = glyphs('texto', 46, 30, start=6, font='Helvetica-Bold')
    column = glyphs('Otra columna', 210, 30, start=11)
    page = model([first, second, column])
    assert text(page, page.group(second[2], 'word')) == 'texto'
    assert text(page, page.group(first[0], 'line')) == 'Mixto texto'
    assert text(page, page.group(column[0], 'line')) == 'Otra columna'
    assert not selection_index(page).range(first[0], column[0])


def test_verified_same_line_continuity_can_cross_original_extraction_blocks():
    first=glyphs('Uno ',10,30,block=1)
    second=glyphs('dos',34,30,start=4,block=2)
    page=model([first,second])
    assert text(page,page.group(second[0],'line'))=='Uno dos'
    assert text(page,page.group(second[0],'block'))=='dos'


def test_paragraph_combines_rows_across_extraction_blocks_but_keeps_other_column_and_heading():
    rows = [glyphs('Primera línea',10,30,start=0,block=0,line=0),
            glyphs('Segunda línea',10,44,start=13,block=1,line=1),
            glyphs('Otra columna',210,30,start=26,block=2,line=2),
            glyphs('Más columna',210,44,start=38,block=2,line=3),
            glyphs('Otro apartado',10,90,start=49,block=3,line=4)]
    page = model(rows)
    ids = page.group(rows[0][1], 'paragraph')
    assert ids == [g.id for row in rows[:2] for g in row]
    assert text(page, page.group(rows[2][1], 'paragraph')) == 'Otra columnaMás columna'


def test_painted_barriers_split_even_tightly_spaced_runs_and_stop_paragraphs():
    rows = [glyphs('IZQ',10,30),glyphs('DER',35,30,start=3),
            glyphs('ABAJO',10,45,start=6,block=1,line=1)]
    page = model(rows, [(32.,20.,32.,40.),(5.,42.,80.,42.)])
    assert text(page,page.group(rows[0][0],'line')) == 'IZQ'
    assert text(page,page.group(rows[0][0],'paragraph')) == 'IZQ'
    assert not selection_index(page).range(rows[0][0],rows[1][0])


def test_cell_uses_complete_segmented_edges_and_excludes_adjacent_cell_and_ocr():
    rows = [glyphs('Fila uno',10,20),glyphs('Fila dos',10,34,start=8,line=1),
            glyphs('VECINO',105,20,start=16,block=1,line=2),
            glyphs('OCR',10,20,start=22,line=3,mode=3)]
    edges = [(0.,0.,50.,0.),(50.,0.,100.,0.),(0.,60.,100.,60.),
             (0.,0.,0.,60.),(100.,0.,100.,60.),(200.,0.,200.,60.),
             (100.,0.,200.,0.),(100.,60.,200.,60.)]
    page = model(rows, edges)
    scope = selection_index(page).scope(rows[0][0],'cell')
    assert scope.rect == (0.,0.,100.,60.)
    assert text(page,scope.ids) == 'Fila unoFila dos'
    assert selection_index(page).cell_rect(rows[2][0]) == (100.,0.,200.,60.)


def test_incomplete_cell_is_a_correctable_paragraph_suggestion():
    rows = [glyphs('Uno',10,20),glyphs('Dos',10,34,start=3,line=1)]
    page = model(rows, [(0.,0.,100.,0.),(0.,60.,100.,60.),(0.,0.,0.,60.)])
    assert selection_index(page).cell_rect(rows[0][0]) is None
    assert text(page,page.group(rows[0][0],'cell')) == 'UnoDos'


def test_word_and_range_follow_vertical_direction_and_geometric_order():
    rows = [glyphs('UNO DOS',30,10,direction=(0.,1.))]
    # PDF painting/extraction identifiers need not be geometric order.
    rows[0] = [replace(g,id=(20-i)) for i,g in enumerate(rows[0])]
    page = model(rows)
    index = SelectionIndex(page)
    assert index.group(rows[0][1],'word') == [20,19,18]
    assert index.range(rows[0][1],rows[0][5],'word') == [20,19,18,17,16,15,14]


def test_cell_and_manual_area_require_complete_characters_without_selecting_hidden_ocr():
    visible = glyphs('Visible',10,20)
    hidden = glyphs('OCR',10,20,start=7,mode=3)
    page = model([visible,hidden])
    assert selected_in_area(page,(0.,0.,100.,50.)) == visible
    with pytest.raises(EditError,match='corta caracteres'):
        selected_in_area(page,(12.,0.,100.,50.))
    with pytest.raises(EditError,match='No hay texto visible'):
        selected_in_area(page,(200.,0.,300.,50.))


def test_geometry_index_is_reused_only_for_its_page_model():
    page = model([glyphs('Texto',10,20)])
    assert selection_index(page) is selection_index(page)
    new_page = model([glyphs('Otro',10,20)])
    assert selection_index(page) is not selection_index(new_page)


def test_only_painted_straight_boundaries_are_used():
    drawings = [{'type':'f','items':[('re',(0,0,100,60))]},
                {'type':'s','stroke_opacity':0.,'items':[('re',(0,0,100,60))]},
                {'type':'s','items':[('re',(0,0,100,60)),('l',(50,0),(50,60))]}]
    assert len(boundaries_from_drawings(drawings)) == 5


def test_overflow_reports_axes_and_expansion_preserves_size_anchor_and_page_limit():
    rect = (20.,30.,100.,50.)
    assert draft_overflow(rect,100.,20.) == (True,False)
    assert draft_overflow(rect,80.,30.) == (False,True)
    assert enlarged_area(rect,100.,30.,(0.,0.,200.,100.)) == (20.,30.,120.,60.)
    with pytest.raises(EditError,match='borde de página'):
        enlarged_area(rect,190.,30.,(0.,0.,200.,100.))


@pytest.mark.parametrize('rect',[(0,0,0,10),(0,0,float('nan'),10),(-1,0,-2,10)])
def test_manual_area_rejects_invalid_dimensions(rect):
    with pytest.raises(EditError,match='no es válida'):
        selected_in_area(model([glyphs('Texto',10,20)]),rect)
