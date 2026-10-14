"""Paragraph continuations use verified scope evidence and keep painted barriers."""
from test_selection_v300 import glyphs, model


def indented_paragraph():
    return [glyphs('First indented row',40,30,block=7,line=0),
            glyphs('Second complete body row',10,44,start=18,block=7,line=1),
            glyphs('Third complete body row',10,58,start=42,block=7,line=2),
            glyphs('Short end',10,72,start=65,block=7,line=3)]


def test_unstructured_paragraph_includes_short_last_line_from_either_anchor():
    rows=indented_paragraph();page=model(rows)
    expected=[g.id for row in rows for g in row]
    assert page.group(rows[0][0],'paragraph')==expected
    assert page.group(rows[-1][0],'paragraph')==expected


def test_short_continuation_does_not_cross_a_painted_row_barrier():
    rows=indented_paragraph();page=model(rows,[(0.,69.,200.,69.)])
    assert page.group(rows[0][0],'paragraph')==[g.id for row in rows[:-1] for g in row]


def test_last_line_anchor_does_not_absorb_next_heading_after_a_larger_gap():
    rows=indented_paragraph();heading=glyphs('Next heading',10,92,start=74,block=8,line=4)
    page=model([*rows,heading]);expected=[g.id for row in rows for g in row]
    assert page.group(rows[-1][0],'paragraph')==expected


def test_verified_semantic_scope_includes_indentation_and_mixed_extraction_blocks():
    rows=indented_paragraph()
    # Validated tag ownership, rather than extraction block identity, connects
    # the last line even when PDF painting split it into another block.
    from dataclasses import replace
    rows[-1]=[replace(g,block=8) for g in rows[-1]]
    page=model(rows);expected=tuple(g.id for row in rows for g in row)
    page.semantic_paragraph_scopes=[expected]
    assert page.group(rows[0][0],'paragraph')==list(expected)
    assert page.group(rows[-1][0],'paragraph')==list(expected)


def test_verified_scope_stops_at_cell_borders_and_never_includes_hidden_ocr():
    left=glyphs('LEFT',10,20);right=glyphs('RIGHT',110,20,start=4,block=1,line=1)
    hidden=glyphs('OCR',10,20,start=9,mode=3,line=2)
    edges=[(0.,0.,200.,0.),(0.,60.,200.,60.),(0.,0.,0.,60.),(100.,0.,100.,60.),(200.,0.,200.,60.)]
    page=model([left,right,hidden],edges)
    page.semantic_paragraph_scopes=[tuple(g.id for g in left+right+hidden)]
    assert page.group(left[0],'paragraph')==[g.id for g in left]
    assert page.group(right[0],'paragraph')==[g.id for g in right]


def test_incomplete_semantic_evidence_does_not_expand_selection():
    rows=indented_paragraph();page=model(rows)
    page.semantic_paragraph_scopes=[(rows[0][0].id,999999)]
    assert page.group(rows[0][0],'paragraph')==[g.id for row in rows for g in row]
