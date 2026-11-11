"""Insert styled/copied text into a new, independently verified tagged paragraph."""
from dataclasses import replace
import time

import pymupdf as fitz

from .draft_control_v305 import checkpoint
from .model import EditError,Glyph


def add_tagged_rich_text(data,request,resolver):
    from .engine import extract_page
    from .media import _isolate_existing_content
    from .richtext import _edit_rich_pdf,_finite,_read_metadata,_validate
    from .tagged import assert_structure
    from .tagged_insert import TaggedAddition
    from .typography_v300 import insertion_anchor_ids
    from .validation import document_issues,assert_graphics_scopes_v316
    started=time.perf_counter()
    if not request.rect or len(request.rect)!=4:
        raise EditError('Define el cuadro donde quieres añadir el texto.')
    rect=tuple(_finite(v,'Posición') for v in request.rect)
    # The positioning anchor is private working data. Its verified paragraph
    # is replaced by the requested glyphs, preserving existing source fonts.
    addition=TaggedAddition(data,request.page,'/P',text='|')
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc,operation='content')
        if issues:raise EditError('\n'.join(issues))
        original=extract_page(doc,request.page)
        page=doc[request.page]
        area=fitz.Rect(rect)
        if area.is_empty or not fitz.Rect(0,0,page.cropbox.width,page.cropbox.height).contains(area):
            raise EditError('El área de texto queda fuera de la parte visible de la página.')
        assert_graphics_scopes_v316(data,request.page)
        _isolate_existing_content(doc,page)
        page=doc.reload_page(page);old=page.get_contents()
        page.insert_text((rect[0],min(rect[1]+10,page.cropbox.height-2)),'|',fontsize=8,fontname='helv')
        expected=addition.apply(doc,old)
        anchored=doc.tobytes(garbage=0,deflate=False,no_new_id=True)
    assert_structure(data,anchored,expected)
    with fitz.open(stream=anchored,filetype='pdf') as doc:
        model=extract_page(doc,request.page)
        ids=insertion_anchor_ids(original,model)
    output,report=_edit_rich_pdf(anchored,replace(request,ids=ids,rect=rect,revision=None),resolver,compose_only=True)
    planned=[Glyph(**g) for g in report['glyphs']]
    with fitz.open(stream=output,filetype='pdf') as doc:
        records=_read_metadata(doc,request.page)
    underlines=records[-1].get('underlines',[]) if records and not report.get('typography') else []
    # Compare the exact final candidate with the user's original, including
    # the planned new tree node. No anchor or unrelated edit can survive.
    checked=_validate(data,output,request.page,original.glyphs+planned,planned,[],underlines,expected)
    report.update(checked,page=request.page,source_regions=[],original='',added_text=True,
                  elapsed_seconds=round(time.perf_counter()-started,3))
    report.setdefault('accessibility',{}).update(reading_order=addition.order,
        automatic_reading_order=addition.automatic_order,existing_structure_preserved=True)
    checkpoint()
    return output,report
