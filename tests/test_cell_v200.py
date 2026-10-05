"""Bounded cell acceptance using real PDF text and native rich composition."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from hashlib import sha256

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.editor_tools_v200 import install_editor_tools_v200
from pdfmodder.engine import extract_page
from pdfmodder.fonts import FontResolver
from pdfmodder.model import EditError
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload


CELL=(30.,30.,180.,105.)


def invoice_cell():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=250)
        page.draw_rect(CELL,color=(.2,.2,.2),fill=(.92,.95,.98),width=.5)
        page.draw_rect((180,30,365,105),color=(.2,.2,.2),width=.5)
        page.draw_rect((30,105,180,180),color=(.2,.2,.2),width=.5)
        size=10.375
        page.insert_text((40,52),'Importe: ',fontsize=size,fontname='helv',color=(.1,.2,.3))
        amount_x=40+fitz.get_text_length('Importe: ',fontsize=size,fontname='helv')
        page.insert_text((amount_x,52),'123,45',fontsize=size,fontname='hebo',color=(.1,.2,.3))
        page.insert_text((190,52),'CLIENTE INTACTO',fontsize=11,fontname='helv')
        page.insert_text((40,130),'CELDA VECINA',fontsize=11,fontname='helv')
        return doc.tobytes()


class CellSession:
    """Only session plumbing is in memory; selection and edit use the real engine."""
    def __init__(self,data):
        self.history=SimpleNamespace(current=data)
        self.resolver=FontResolver(Path(__file__).with_name('unused-cell-fonts.json'),installed_dirs=[])

    def _writable(self):
        pass

    def _open(self,data):
        return fitz.open(stream=data,filetype='pdf')

    def rich_selection(self,page,ids):
        return selection_payload(self.history.current,page,ids,self.resolver)

    def state(self):
        return {'document_revision':sha256(self.history.current).hexdigest()}


install_editor_tools_v200(CellSession)


def request(payload):
    keys=('page','ids','runs','rect','width','height','paragraphs','revision','allow_overlap','auto_width','auto_height')
    return RichTextRequest(**{key:payload[key] for key in keys if key in payload})


def neighbour_state(data):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
        return [(g.text,g.origin,g.font,g.size,g.color) for g in model.glyphs
                if g.origin[0]>=180 or g.origin[1]>=105]


def test_cell_right_alignment_padding_mixed_format_and_neighbours():
    data=invoice_cell();session=CellSession(data)
    result=session.cell_selection_v200(0,CELL,padding=4,alignment='right')
    payload=result['payload']
    assert payload['rect']==[34,34,176,101]
    assert payload['width']==142 and payload['height']==67
    assert payload['auto_width'] is payload['auto_height'] is False
    assert all(p['alignment']=='right' for p in payload['paragraphs'])
    old=''.join(run['text'] for run in payload['runs'])
    desired=old.replace('123,45','999,95')
    assert desired!=old
    position=0
    for run in payload['runs']:
        length=len(run['text']);run['text']=desired[position:position+length];position+=length
    changed,report=edit_rich_pdf(data,request(payload),session.resolver)
    assert report['verified']
    assert neighbour_state(changed)==neighbour_state(data)
    with fitz.open(stream=changed,filetype='pdf') as doc:
        assert '999,95' in doc[0].get_text() and '123,45' not in doc[0].get_text()
        glyphs=[g for g in report['glyphs']]
        assert max(g['bbox'][2] for g in glyphs)==pytest.approx(176,abs=.035)
        assert all(34-.035<=g['bbox'][0] and g['bbox'][2]<=176+.035
                   and 34-.035<=g['bbox'][1] and g['bbox'][3]<=101+.035 for g in glyphs)
        assert {g['font'] for g in glyphs}=={'Helvetica','Helvetica-Bold'}
        assert all(g['size']==pytest.approx(10.375) for g in glyphs)
        assert len(doc[0].get_drawings())==3
    assert '999,95' in PdfReader(BytesIO(changed)).pages[0].extract_text()


def test_cell_newline_stays_inside_fixed_area_and_retains_size():
    data=invoice_cell();session=CellSession(data)
    payload=session.cell_selection_v200(0,CELL,padding=4,alignment='left')['payload']
    payload['runs']=[dict(payload['runs'][0],text='Primera línea\nSegunda línea')]
    payload['paragraphs']=[{'alignment':'left','line_spacing':15}]
    changed,report=edit_rich_pdf(data,request(payload),session.resolver)
    assert report['line_count']==2
    assert neighbour_state(changed)==neighbour_state(data)
    ys=sorted(set(round(g['origin'][1],3) for g in report['glyphs']))
    assert len(ys)==2 and ys[1]-ys[0]==pytest.approx(15,abs=.002)
    assert all(g['size']==pytest.approx(10.375) for g in report['glyphs'])
    assert all(fitz.Rect(payload['rect']).contains(fitz.Rect(g['bbox'])) for g in report['glyphs'])
    with fitz.open(stream=changed,filetype='pdf') as doc:
        assert 'Primera línea' in doc[0].get_text() and 'Segunda línea' in doc[0].get_text()


def test_cell_overflow_keeps_original_and_does_not_expand():
    data=invoice_cell();session=CellSession(data)
    payload=session.cell_selection_v200(0,CELL,padding=4,alignment='left')['payload']
    payload['runs']=[dict(payload['runs'][0],text='\n'.join('Texto de la celda' for _ in range(10)))]
    with pytest.raises(EditError,match='altura disponible'):
        edit_rich_pdf(data,request(payload),session.resolver)
    assert session.history.current==data
    assert payload['height']==67 and payload['auto_height'] is False


@pytest.mark.parametrize('rect,padding,match',[
    ((40,45,80,55),0,'corta caracteres'),
    (CELL,80,'sin espacio'),
    ((-1,30,180,105),2,'dentro de la página'),
])
def test_cell_boundaries_are_explicit(rect,padding,match):
    session=CellSession(invoice_cell())
    with pytest.raises(EditError,match=match):
        session.cell_selection_v200(0,rect,padding=padding)
