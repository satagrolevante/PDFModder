from io import BytesIO
from pathlib import Path
import pymupdf as fitz

from pdfmodder.compatibility_v200 import preflight_text
from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.fonts import FontResolver
from pdfmodder.model import EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from test_font_evidence import synthetic_font
from test_form_instances_v200 import form_document, selection


def text_document():
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=200)
        page.insert_font(fontname='Synthetic',fontbuffer=synthetic_font(text=' ninoñáéíóú'))
        page.insert_text((40,70),'nino',fontname='Synthetic',fontsize=11.375)
        data=doc.tobytes()
        model=extract_page(doc,0,data)
        return data,model,tuple(g.id for g in model.glyphs)


def resolver():
    return FontResolver(Path(__file__).with_name('unused-v200-fonts.json'),installed_dirs=[])


def test_preflight_proves_original_codes_and_normalizes_composed_accents():
    data,model,ids=text_document()
    info=preflight_text(data,0,ids,'nin\u0303o',resolver())
    assert info['status']=='available'
    assert info['normalized_text']=='niño' and info['unicode_normalization']
    assert info['fonts'][0]['certainty']=='embedded_program'
    assert info['fonts'][0]['candidates'][0]['font_program']['outline_format']=='TrueType'
    changed,report=edit_pdf(data,EditRequest(0,ids,text='nin\u0303o',auto_width=True,revision=model.revision),resolver())
    with fitz.open(stream=changed,filetype='pdf') as doc:
        assert 'niño' in doc[0].get_text()
    assert report['unicode_normalization']['form']=='NFC'


def test_preflight_missing_glyph_never_claims_available():
    data,_,ids=text_document()
    info=preflight_text(data,0,ids,'niño €',resolver())
    assert info['status']=='conditional'
    assert info['fonts'][0]['native_missing_characters']==['€']
    assert any('U+20AC' in reason for reason in info['reasons'])
    assert info['requires_final_validation']


def test_rich_edit_selected_form_has_original_revision_and_neighbours():
    data=form_document()
    model,ids=selection(data)
    payload=selection_payload(data,0,ids,resolver())
    assert payload['revision']==model.revision and payload['form_isolation']
    runs=[dict(run) for run in payload['runs']]
    runs[-1]['text']=runs[-1]['text'][:-1]+'6'
    changed,report=edit_rich_pdf(data,RichTextRequest(0,list(ids),runs,rect=payload['rect'],
                  revision=payload['revision'],auto_width=True,auto_height=True),resolver())
    with fitz.open(stream=changed,filetype='pdf') as doc:
        assert doc[0].get_text().count('2026')==1
        assert doc[0].get_text().count('2025')==1
        assert 'Vecino intacto' in doc[0].get_text()
    assert report['form_isolation']['shared_objects_unchanged']


def test_form_preflight_reports_local_compatibility():
    data=form_document();_,ids=selection(data)
    info=preflight_text(data,0,ids,'2026',resolver())
    assert info['status']=='available' and info['form_isolation']
    assert info['fonts'][0]['availability']=='original_codes_verified'
