"""Native moves preserve known tag styles and update only proven text boxes."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject

from pdfmodder.clipped_layout import move_clipped_text
from pdfmodder.model import EditError
from pdfmodder.tagged import analyze, _attribute_snapshot
from test_engine import request_for, select
from test_tagged_layout_styles import boxed_pdf, layout_style, styled_pdf


@pytest.mark.parametrize('classed', [False, True])
def test_move_preserves_known_shared_layout_styles(classed):
    source = styled_pdf(layout_style(), indirect=True, classed=classed)
    model, glyphs = select(source, '10/09/2026', x=100, y=100)
    output, report = move_clipped_text(source, request_for(model, glyphs, dx=9, dy=14), model)
    assert report['verified'] and report['accessibility']['reading_order_preserved']
    assert report['accessibility']['layout_attribute_updates'] == 0
    assert analyze(output).semantic() == analyze(source).semantic()


@pytest.mark.parametrize('classed', [False, True])
def test_move_updates_tight_text_bbox_without_mutating_shared_definition(classed):
    source = boxed_pdf(classed=classed)
    model, glyphs = select(source, '10/09/2026', x=100, y=100)
    output, report = move_clipped_text(source, request_for(model, glyphs, dx=9, dy=14), model)
    assert report['accessibility']['layout_attribute_updates'] == 1
    before = PdfReader(BytesIO(source)).trailer['/Root']['/StructTreeRoot']
    after = PdfReader(BytesIO(output)).trailer['/Root']['/StructTreeRoot']
    if classed:
        assert _attribute_snapshot(before['/ClassMap']) == _attribute_snapshot(after['/ClassMap'])
    # An unrelated node retains the original shared class/attribute geometry.
    assert _attribute_snapshot(before['/K']['/K'][-1].get_object().get('/A')) == _attribute_snapshot(
        after['/K']['/K'][-1].get_object().get('/A'))
    with fitz.open(stream=output, filetype='pdf') as document:
        assert '10/09/2026' in document[0].get_text()


def test_unknown_layout_geometry_remains_guarded():
    attributes = layout_style()
    attributes[NameObject('/Width')] = NumberObject(100)
    source = styled_pdf(attributes)
    model, glyphs = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match='atributos de disposición'):
        move_clipped_text(source, request_for(model, glyphs, dx=9, dy=14), model)
