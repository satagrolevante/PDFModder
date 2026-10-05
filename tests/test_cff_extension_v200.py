"""Original CC0 synthetic OpenType/CFF contours, including Spanish characters."""
from io import BytesIO
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from pypdf import PdfReader
import pymupdf as fitz
import pytest

from pdfmodder.fonts import FontResolver, FontError
from pdfmodder.native_font_extension import prepare_native_font
from test_native_font_extension import document, paint
from test_fonts import make_font


def make_cff(path, text=' ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ñÑáéíóúÁÉÍÓÚ€.,-/'):
    points = sorted(set(ord(char) for char in text))
    names = ['.notdef']+[f'uni{point:04X}' for point in points]
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({point:f'uni{point:04X}' for point in points})
    charstrings = {}
    for name in names:
        pen = T2CharStringPen(600, None)
        if name != 'uni0020':
            pen.moveTo((50,0)); pen.lineTo((500,0)); pen.lineTo((500,650)); pen.lineTo((50,650)); pen.closePath()
        charstrings[name] = pen.getCharString()
    builder.setupCFF('PDFModderCFF-Regular', {'FullName':'PDFModder CFF Regular', 'FamilyName':'PDFModder CFF',
                    'Weight':'Regular', 'FontBBox':[50,0,500,650]}, charstrings, {})
    builder.setupHorizontalMetrics({name:(600,50) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({'familyName':'PDFModder CFF', 'styleName':'Regular', 'fullName':'PDFModder CFF Regular',
                           'psName':'PDFModderCFF-Regular', 'version':'Version 1.0',
                           'licenseDescription':'Original synthetic font, CC0 public domain.'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,fsType=8)
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)
    return path


def test_explicit_cff_encoding_keeps_original_program_and_real_text(tmp_path):
    data, show = document(make_font(tmp_path/'source.ttf'))
    chosen = make_cff(tmp_path/'chosen.otf')
    extension = prepare_native_font(data,0,show,'SANDÍA Ñ €',font_file=chosen,
                                   resolver=FontResolver(tmp_path/'mapping.json',installed_dirs=[]))
    assert extension.evidence['program_unchanged']
    assert extension.evidence['outline_format']=='CFF'
    assert extension.font['/FontDescriptor']['/FontFile3'].get_data()==chosen.read_bytes()
    changed = paint(extension,'SANDÍA Ñ €')
    assert 'SANDÍA Ñ €' in PdfReader(BytesIO(changed)).pages[0].extract_text()
    with fitz.open(stream=changed,filetype='pdf') as doc:
        assert 'SANDÍA Ñ €' in doc[0].get_text()
    # Same outlines and position as MuPDF's normal OTF route, without any
    # rasterisation or TrueType conversion.
    with fitz.open() as reference, fitz.open(stream=changed,filetype='pdf') as actual:
        page = reference.new_page(width=300,height=200)
        page.insert_text((30,100),'SANDÍA Ñ €',fontname='CFF',fontfile=str(chosen),fontsize=11.25)
        region = fitz.Rect(20,85,150,115)
        assert page.get_pixmap(matrix=fitz.Matrix(2,2),clip=region).samples == actual[0].get_pixmap(matrix=fitz.Matrix(2,2),clip=region).samples


def test_cff_missing_character_has_precise_error(tmp_path):
    data, show = document(make_font(tmp_path/'source.ttf'))
    chosen = make_cff(tmp_path/'partial.otf',text=' ABC')
    with pytest.raises(FontError,match='U\\+20AC'):
        prepare_native_font(data,0,show,'ABC €',font_file=chosen,
                            resolver=FontResolver(tmp_path/'mapping.json',installed_dirs=[]))
