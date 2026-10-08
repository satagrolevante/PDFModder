from types import SimpleNamespace
from hashlib import sha256

import pymupdf as fitz
import pytest

from pdfmodder.compatibility_v300 import selection_capabilities_v300
from pdfmodder.engine import extract_page
from pdfmodder.fonts import FontResolver
from pdfmodder.model import EditError


def document(*,rotated=False,field=False,overlap=False):
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((70,90),'Texto original',rotate=90 if rotated else 0)
        if field:
            widget=fitz.Widget();widget.field_name='nombre';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect=fitz.Rect(60,70,240,110) if overlap else fitz.Rect(40,180,240,220)
            widget.field_value='Ana';page.add_widget(widget)
        data=doc.tobytes()
    with fitz.open(stream=data,filetype='pdf') as doc:
        # The field appearance is also extractable text; select the separate
        # body paragraph, exactly as a user would in the content editor.
        ids=[g.id for g in extract_page(doc,0,data).glyphs if g.origin[1]<150 and abs(g.size-11)<.01]
    session=SimpleNamespace(history=SimpleNamespace(current=data),resolver=FontResolver(),
        _open=lambda source:fitz.open(stream=source,filetype='pdf'))
    return data,ids,session


def test_rotated_text_can_be_transformed_even_when_text_replacement_is_unavailable():
    data,ids,session=document(rotated=True)
    result=selection_capabilities_v300(session,0,ids,sha256(data).hexdigest())
    assert result['operations']['text']['status']=='blocked'
    assert result['operations']['move']['status']=='available'
    assert result['operations']['rotate']['status']=='available'
    assert 'objects' in result['operations']['text']['resolution_ids']
    assert result['object_id']


def test_unrelated_fields_do_not_block_normal_text_editing():
    data,ids,session=document(field=True)
    result=selection_capabilities_v300(session,0,ids)
    assert result['operations']['text']['status']=='available'
    assert 'area' in result['operations']['text']['resolution_ids']
    assert result['operations']['move']['status']=='available'


def test_text_touching_a_field_offers_the_field_editor():
    data,ids,session=document(field=True,overlap=True)
    result=selection_capabilities_v300(session,0,ids)
    assert result['operations']['text']['status']=='blocked'
    assert 'forms' in result['operations']['text']['resolution_ids']
    assert any('campo' in reason for reason in result['operations']['text']['reasons'])
    assert result['operations']['move']['status']=='blocked'
    assert any('campo' in reason for reason in result['operations']['move']['reasons'])


def test_old_selection_never_reports_current_capabilities():
    _,ids,session=document()
    with pytest.raises(EditError,match='revisión'):
        selection_capabilities_v300(session,0,ids,revision='old')


def test_object_inventory_limitation_does_not_block_verified_text(monkeypatch):
    import pdfmodder.objects_v300 as objects
    _,ids,session=document()
    def unavailable(*args):
        raise EditError('La aparición no tiene una geometría verificable.')
    monkeypatch.setattr(objects,'object_graph',unavailable)
    result=selection_capabilities_v300(session,0,ids)
    assert result['operations']['text']['status']=='available'
    for operation in ('move','scale','rotate','duplicate'):
        assert result['operations'][operation]['status']=='blocked'
        assert 'geometría verificable' in result['operations'][operation]['reasons'][0]
    assert result['object_id'] is None
