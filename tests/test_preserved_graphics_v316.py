from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.analysis_reuse_v315 import AnalysisCacheV315,analysis_scope_v315
from pdfmodder.model import EditError
from pdfmodder.preserved_graphics_v316 import preserved_text_graphics_v316
from pdfmodder.validation import assert_text_object_structure


def source():
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=220)
        page.draw_rect((20,20,100,100),fill=(.2,.4,.6))
        page.insert_text((30,150),'Original')
        doc.new_page(width=300,height=220).insert_text((30,150),'Second')
        return doc.tobytes()


def add_stream(data,raw):
    with fitz.open(stream=data,filetype='pdf') as doc:
        page=doc[0];contents=page.get_contents()
        new=doc.get_new_xref();doc.update_object(new,'<<>>');doc.update_stream(new,raw)
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in [*contents,new])+']')
        return doc.tobytes(garbage=2)


def test_only_independent_text_may_change_above_unchanged_artwork():
    original=source()
    with fitz.open(stream=original,filetype='pdf') as doc:
        from pdfmodder.media import _isolate_existing_content
        _isolate_existing_content(doc,doc[0])
        doc[0].insert_text((130,80),'Added',fontname='cour')
        output=doc.tobytes(garbage=2)
    assert preserved_text_graphics_v316(original,output,0)
    with fitz.open(stream=output,filetype='pdf') as doc:
        xref=doc[0].get_contents()[-1]
        raw=doc.xref_stream(xref)
        doc.update_stream(xref,b'q 1 0 0 1 10 5 cm\n'+raw+b'\nQ')
        moved=doc.tobytes(garbage=2)
    assert preserved_text_graphics_v316(output,moved,0)


@pytest.mark.parametrize('raw',[
    b'q 1 0 0 rg 130 130 10 10 re f Q',
    b'q 1 0 0 1 30 30 cm Q 2 0 0 2 0 0 cm',
    b'1 0 0 1 30 30 cm',
    b'q /Unknown Do Q',
    b'q BT /helv 12 Tf 7 Tr (clip) Tj ET Q',
])
def test_new_graphics_state_or_paint_falls_back(raw):
    original=source()
    assert not preserved_text_graphics_v316(original,add_stream(original,raw),0)


def test_existing_font_binding_must_retain_its_exact_program():
    original=source()
    with fitz.open(stream=original,filetype='pdf') as doc:
        font=doc[0].get_fonts()[0][0]
        doc.xref_set_key(font,'BaseFont','/Courier')
        output=doc.tobytes(garbage=2)
    assert not preserved_text_graphics_v316(original,output,0)


def test_new_font_cannot_resolve_an_original_missing_name():
    original=add_stream(source(),b'q BT /Missing 10 Tf 7 Tr 1 0 0 1 20 20 Tm (X) Tj ET Q')
    with fitz.open(stream=original,filetype='pdf') as doc:
        font=doc[0].get_fonts()[0][0]
        resources=int(doc.xref_get_key(doc[0].xref,'Resources')[1].split()[0])
        kind,value=doc.xref_get_key(resources,'Font')
        if kind=='xref':doc.xref_set_key(int(value.split()[0]),'Missing',f'{font} 0 R')
        else:doc.xref_set_key(resources,'Font',value[:-2]+f' /Missing {font} 0 R >>')
        output=doc.tobytes(garbage=2)
    assert not preserved_text_graphics_v316(original,output,0)


def test_scope_summary_reuses_only_exact_complete_streams(monkeypatch):
    import pdfmodder.analysis_reuse_v315 as analysis
    original=source()
    output=add_stream(original,b'q BT /helv 12 Tf 1 0 0 1 120 50 Tm (New) Tj ET Q')
    parsed=[];parse=analysis.ContentStream._parse_content_stream
    def count(self,*args,**kwargs):
        parsed.append(True);return parse(self,*args,**kwargs)
    monkeypatch.setattr(analysis.ContentStream,'_parse_content_stream',count)
    cache=AnalysisCacheV315()
    with analysis_scope_v315(cache):
        assert_text_object_structure(original)
        first=len(parsed)
        assert_text_object_structure(output)
        assert len(parsed)==first+1
    cache.clear()
    assert not cache._state['scopes']


def test_scope_summary_preserves_cross_stream_text_scope_and_operand_fallback():
    with fitz.open() as doc:
        page=doc.new_page(width=200,height=200);page.insert_font(fontname='helv')
        ids=[]
        for raw in [b'BT /helv 12 Tf 1 0 0 1 20 20 Tm (A)',b'Tj ET']:
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,raw);ids.append(xref)
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in ids)+']')
        good=doc.tobytes()
        doc.update_stream(ids[-1],b'Tj')
        bad=doc.tobytes()
    with analysis_scope_v315():
        assert_text_object_structure(good)
        with pytest.raises(EditError,match='BT sin cierre'):
            assert_text_object_structure(bad)


def test_scope_summary_rechecks_invoked_form_resources_after_page_reuse():
    with fitz.open() as artwork,fitz.open() as doc:
        artwork.new_page(width=100,height=100).insert_text((10,20),'Form')
        doc.new_page(width=200,height=200).show_pdf_page(fitz.Rect(20,20,120,120),artwork,0)
        original=doc.tobytes()
        form=next(xref for xref,*_ in doc[0].get_xobjects() if doc.xref_stream(xref))
        doc.update_stream(form,b'ET')
        broken=doc.tobytes()
    with analysis_scope_v315():
        assert_text_object_structure(original)
        with pytest.raises(EditError,match='ET sin apertura'):
            assert_text_object_structure(broken)


def test_native_coordinate_snapshot_matches_existing_vector_comparison():
    from pdfmodder.validation import _canonical,_validation_drawings_v316
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=200)
        page.draw_rect((20,20,80,80),fill=(1,0,0))
        page.draw_line((10,90),(160,100),color=(0,0,1))
        page.draw_bezier((10,120),(20,140),(80,140),(90,120),color=(0,1,0))
        assert _canonical(page.get_drawings())==_canonical(_validation_drawings_v316(page))


def scopes_source(streams):
    with fitz.open() as doc:
        page=doc.new_page(width=200,height=200);ids=[]
        for raw in streams:
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,raw);ids.append(xref)
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in ids)+']')
        return doc.tobytes()


@pytest.mark.parametrize('raw,reason',[
    (b'Q','Q sin apertura'),(b'q','estado gráfico'),(b'BT BT ET ET','anidados'),
    (b'BT','estado gráfico'),(b'ET','sin apertura'),(b'/Span BMC','marcado abierto'),
    (b'EMC','cierre sin apertura'),(b'q 0 0 10 10 re W Q','estado gráfico'),
    (b'q 1 0 cm Q','matriz gráfica'),(b'q /Missing gs Q','estado gráfico'),
])
def test_graphics_preflight_rejects_state_leaks_and_invalid_matrices(raw,reason):
    from pdfmodder.validation import assert_graphics_scopes_v316
    with analysis_scope_v315(),pytest.raises(EditError,match=reason):
        assert_graphics_scopes_v316(scopes_source([raw]),0)


def test_graphics_preflight_carries_scopes_and_operands_across_streams():
    from pdfmodder.validation import assert_graphics_scopes_v316
    valid=scopes_source([b'q /Span BMC BT',b'ET EMC 1 0 0',b'1 10 20 cm Q'])
    with analysis_scope_v315():
        assert_graphics_scopes_v316(valid,0)


def test_page_ast_reuses_opaque_stream_across_new_revision(monkeypatch):
    import pdfmodder.analysis_reuse_v315 as analysis
    first=scopes_source([b'q 0 0 10 10 re f Q',b'q BT ET Q'])
    second=add_stream(first,b'q BT ET Q')
    calls=[];parse=analysis.ContentStream._parse_content_stream
    def count(self,*args,**kwargs):
        calls.append(True);return parse(self,*args,**kwargs)
    monkeypatch.setattr(analysis.ContentStream,'_parse_content_stream',count)
    with analysis_scope_v315():
        old=analysis.page_operations_v315(first,0,PdfReader(BytesIO(first),strict=True))
        initial=len(calls)
        newer=analysis.page_operations_v315(second,0,PdfReader(BytesIO(second),strict=True))
        assert newer[:len(old)]==old
        # The third stream is byte-identical to the existing second stream;
        # both boundaries and operands are reused without another parse.
        assert len(calls)==initial


def test_page_ast_split_operand_still_uses_concatenated_source():
    import pdfmodder.analysis_reuse_v315 as analysis
    data=scopes_source([b'q 1 0 0',b'1 10 20 cm Q'])
    with analysis_scope_v315():
        operations=analysis.page_operations_v315(data,0,PdfReader(BytesIO(data),strict=True))
        assert operations[1][1]==b'cm' and len(operations[1][0])==6


def test_syntax_lru_can_retain_small_layers_but_obeys_total_budget(monkeypatch):
    import pdfmodder.analysis_reuse_v315 as analysis
    cache=AnalysisCacheV315()
    with analysis_scope_v315(cache):
        for number in range(12):
            analysis.stream_operations_v316(f'q 1 0 0 1 {number} 0 cm Q'.encode())
        assert len(cache._state['syntax'])==12
    monkeypatch.setattr(analysis,'_MAX_AST_BYTES',1000)
    with analysis_scope_v315(cache):
        for number in range(12,24):
            analysis.stream_operations_v316(f'q 1 0 0 1 {number} 0 cm Q'.encode())
        assert cache._state['syntax_bytes']<=1000
        assert len(cache._state['syntax'])<12
        reader=PdfReader(BytesIO(source()),strict=True)
        analysis.stream_scope_events_v316(b'q BT ET Q',reader)
        assert cache._state['scopes']
    cache.clear()
    assert cache._state['syntax_bytes']==cache._state['scope_bytes']==0
    assert not cache._state['syntax'] and not cache._state['scopes']
