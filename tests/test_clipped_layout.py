"""Campos recortados reproducibles: códigos nativos y cursor posterior intactos."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, DictionaryObject, FloatObject, NameObject, NumberObject

from pdfmodder.clipping import CLIP_ISSUE, _raw
from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest


def fixture(word='SOL', *, tc=0., tw=0., tz=100., neighbors=True, shared=False,
            native=False, inherited_text_clip=False, restore_clip=False, clip_right=420):
    with fitz.open() as doc:
        page=doc.new_page(width=450,height=400)
        page.draw_rect((30,45,420,100),color=(.2,.4,.5),fill=(.83,.94,.92))
        page.insert_text((40,80),word,fontname='cour',fontsize=10)
        page.insert_text((40,250),'ABCDEFGHIJKLMNOPQRSTUVWXYZ ',fontname='cour',fontsize=10)
        doc.new_page(width=450,height=400).insert_text((40,80),'PAGINA INTACTA')
        data=doc.tobytes()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
    page=writer.pages[0]
    stream=ContentStream(page['/Contents'][1],writer)
    middle=[]
    for args,op in stream.operations:
        if op==b'TJ':
            word_bytes=word.encode()
            array=ArrayObject([ByteStringObject(word_bytes[:1]),FloatObject(18.25),
                               ByteStringObject(word_bytes[1:]),NumberObject(-8000)])
            if neighbors:array.append(ByteStringObject(b' LUNA'))
            middle.extend([([FloatObject(tc)],b'Tc'),([FloatObject(tw)],b'Tw'),([FloatObject(tz)],b'Tz'),
                           ([array],b'TJ'),([ByteStringObject(b' FIN')],b'Tj')])
        else:middle.append((args,op))
    n=lambda *v:[FloatObject(a) for a in v]
    prefix=[([],b'q'),(n(.1,0,0,.1,0,0),b'cm'),(n(300,3000,(clip_right-30)*10,550),b're'),([],b'W'),([],b'n'),
            (n(10,0,0,10,0,0),b'cm')]
    if inherited_text_clip:
        # A later Tr0 does not undo the text clipping installed by ET.
        clip_ops=[([],b'BT'),([NameObject('/cour'),NumberObject(10)],b'Tf'),
                  (n(1,0,0,1,40,280),b'Tm'),([NumberObject(7)],b'Tr'),
                  ([ByteStringObject(b'ABC')],b'Tj'),([],b'ET'),([NumberObject(0)],b'Tr')]
        prefix+=([([],b'q')]+clip_ops+[([],b'Q')]) if restore_clip else clip_ops
    stream.operations=prefix+middle+[([],b'Q')]
    page['/Contents'][1]=writer._add_object(stream)
    if native:
        # The bytes are deliberately not ASCII/Unicode: A..Z use 128..153.
        font=page['/Resources']['/Font']['/cour']
        font[NameObject('/Encoding')]=DictionaryObject({NameObject('/BaseEncoding'):NameObject('/WinAnsiEncoding'),
            NameObject('/Differences'):ArrayObject([NumberObject(128),*[NameObject('/'+c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ']])})
        font[NameObject('/FirstChar')]=NumberObject(0)
        font[NameObject('/LastChar')]=NumberObject(255)
        font[NameObject('/Widths')]=ArrayObject([NumberObject(600)]*256)
        for index,ref in enumerate(page['/Contents']):
            item=ContentStream(ref,writer)
            ops=[]
            for args,op in item.operations:
                convert=lambda v:ByteStringObject(bytes(code+63 if 65<=code<=90 else code for code in _raw(v)))
                if op==b'TJ':args=[ArrayObject([convert(v) if isinstance(v,(str,bytes)) else v for v in args[0]])]
                elif op==b'Tj':args=[convert(args[0])]
                ops.append((args,op))
            item.operations=ops
            page['/Contents'][index]=writer._add_object(item)
    if shared:
        writer.pages[1][NameObject('/Contents')]=page['/Contents']
        writer.pages[1][NameObject('/Resources')]=page['/Resources']
    out=BytesIO();writer.write(out)
    return out.getvalue()


def selected(data,word):
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,0,data)
    joined=''.join(g.text for g in model.glyphs)
    offset=joined.find(word)
    assert offset>=0
    chosen=model.glyphs[offset:offset+len(word)]
    # Ignore an earlier clipping-only SHOW when present.
    if chosen[0].mode!=0:
        offset=joined.find(word,offset+1)
        chosen=model.glyphs[offset:offset+len(word)]
    assert all(abs(g.origin[1]-80)<.02 and g.mode==0 for g in chosen)
    assert CLIP_ISSUE in model.issues
    return model,chosen


def change(data,old,new,**kwargs):
    model,chosen=selected(data,old)
    return edit_pdf(data,EditRequest(0,[g.id for g in chosen],text=new,revision=model.revision,**kwargs))


@pytest.mark.parametrize('new',['SAL','ESTRELLA','A'])
@pytest.mark.parametrize('native',[False,True])
def test_automatic_width_uses_native_tj_tracking_and_scale_instead_of_unicode_estimate(new,native):
    from pdfmodder.textlayout import edit_with_layout
    from pdfmodder.model import union
    data=fixture('SOL',tc=.375,tw=1.1,tz=80,native=native)
    model,chosen=selected(data,'SOL')
    output,report=edit_with_layout(data,EditRequest(0,[g.id for g in chosen],text=new,auto_width=True,revision=model.revision))
    assert report['verified'] and report['auto_width'] and report['font_resources_unchanged']
    after_model,after_chosen=selected(output,new)
    actual=union(g.bbox for g in after_chosen)
    assert report['area_width']==pytest.approx(actual[2]-actual[0],abs=.001)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        for word in ('LUNA','FIN'):
            assert tuple(before[0].search_for(word)[0])==pytest.approx(tuple(after[0].search_for(word)[0]),abs=.0001)
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples


def test_automatic_native_width_cannot_expand_outside_the_actual_clip():
    from pdfmodder.textlayout import edit_with_layout
    data=fixture('SOL',clip_right=65)
    model,chosen=selected(data,'SOL')
    with pytest.raises(EditError,match='recorte'):
        edit_with_layout(data,EditRequest(0,[g.id for g in chosen],text='ESTRELLA',auto_width=True,revision=model.revision))


@pytest.mark.parametrize('old,new',[('SOL','ESTRELLA'),('ESTRELLA','SOL'),('EL SOL','LA ESTRELLA')])
@pytest.mark.parametrize('spacing',[(0,0,100),(.375,1.1,80)])
@pytest.mark.parametrize('native',[False,True])
def test_length_changes_preserve_same_show_next_show_native_font_and_vectors(old,new,spacing,native):
    data=fixture(old,tc=spacing[0],tw=spacing[1],tz=spacing[2],native=native)
    fingerprint=sha256(data).hexdigest()
    output,report=change(data,old,new,width=88,line_reflow=False)
    assert report['verified'] and report['operators_preserved'] and report['font_resources_unchanged']
    assert abs(report['cursor_residual'])<1e-10
    assert report['tc']==spacing[0] and report['tw']==spacing[1] and report['tz']==spacing[2]/100
    assert report['internal_tj_removed']==18.25
    assert len(report['source_regions'])==len(old) and len(report['destination_regions'])==len(new)
    assert all(p['max_channel_delta']==0 for p in report['pages'])
    assert sha256(data).hexdigest()==fingerprint
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_texttrace()==after[1].get_texttrace()
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert before[0].get_drawings()==after[0].get_drawings()
        for word in ('LUNA','FIN'):
            old_boxes,new_boxes=before[0].search_for(word),after[0].search_for(word)
            assert len(old_boxes)==len(new_boxes)==1
            # Native TJ arithmetic accumulates float32 roundoff below .0001 pt.
            assert tuple(old_boxes[0])==pytest.approx(tuple(new_boxes[0]),abs=.0001)
        assert len(after[0].search_for(new))==1


@pytest.mark.parametrize('anchor',['left','right','center'])
def test_shorter_full_field_keeps_anchor_and_shared_page(anchor):
    data=fixture('ESTRELLA',neighbors=False,shared=True)
    output,report=change(data,'ESTRELLA','SOL',anchor=anchor,line_reflow=True)
    assert report['layout_scope']=='Campo completo'
    assert report['line_reflow_requested'] and not report['line_reflow']
    old,new=report['old_bounds'],report['new_bounds']
    if anchor=='left':assert new[0]==pytest.approx(old[0],abs=.001)
    elif anchor=='right':assert new[2]==pytest.approx(old[2],abs=.001)
    else:assert new[0]+new[2]==pytest.approx(old[0]+old[2],abs=.001)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[1].get_texttrace()==after[1].get_texttrace()
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples


def test_partial_line_adjustment_is_explicitly_blocked_and_original_is_unchanged():
    data=fixture()
    fingerprint=sha256(data).hexdigest()
    with pytest.raises(EditError,match='texto completo'):
        change(data,'SOL','ESTRELLA',width=80,line_reflow=True)
    assert sha256(data).hexdigest()==fingerprint


def test_longer_field_needs_explicit_space_and_can_be_edited_again_after_reopen():
    data=fixture(neighbors=False)
    with pytest.raises(EditError,match='espacio disponible'):
        change(data,'SOL','ESTRELLA',line_reflow=True)
    output,report=change(data,'SOL','ESTRELLA',width=80,line_reflow=True)
    output2,report2=change(output,'ESTRELLA','SOL',line_reflow=True)
    assert report['verified'] and report2['verified']
    with fitz.open(stream=output2,filetype='pdf') as doc:
        assert len(doc[0].search_for('SOL'))==1
        assert len(doc[0].search_for('ESTRELLA'))==0


def test_clip_bounds_block_longer_text_despite_large_manual_area():
    data=fixture(neighbors=False,clip_right=70)
    with pytest.raises(EditError,match='espacio disponible o su recorte'):
        change(data,'SOL','ESTRELLA',width=150,line_reflow=True)


def test_inherited_text_clip_is_not_cleared_by_later_tr_zero():
    data=fixture(inherited_text_clip=True)
    with pytest.raises(EditError,match='recorte de texto|Codificación'):
        change(data,'SOL','ESTRELLA',width=80)


def test_q_restore_removes_unrelated_inherited_text_clip():
    data=fixture(inherited_text_clip=True,restore_clip=True)
    output,report=change(data,'SOL','ESTRELLA',width=80)
    assert report['verified']


@pytest.mark.parametrize('kwargs,message',[
    ({'dx':1},'mover'),({'size':9},'tamaño'),({'font_name':'Arial'},'fuente'),
    ({'reflow':True},'entre líneas'),({'anchor':'decimal'},'anclaje'),
])
def test_variable_length_guard_keeps_format_movement_and_reflow_explicit(kwargs,message):
    with pytest.raises(EditError,match=message):change(fixture(),'SOL','ESTRELLA',width=80,**kwargs)


def test_native_route_does_not_invent_codes_not_observed_in_selected_resource():
    with pytest.raises(EditError,match='códigos únicos'):change(fixture(native=True),'SOL','NIÑO',width=80)


def test_extgstate_requires_explicit_font_size_after_gs():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(fixture())))
    page=writer.pages[0]
    page['/Resources'][NameObject('/ExtGState')]=DictionaryObject({NameObject('/GS'):DictionaryObject({
        NameObject('/Font'):ArrayObject([page['/Resources']['/Font'].raw_get('/cour'),NumberObject(10)])})})
    stream=ContentStream(page['/Contents'][1],writer)
    operations=[]
    for args,op in stream.operations:
        operations.append((args,op))
        if op==b'Tf':operations.append(([NameObject('/GS')],b'gs'))
    stream.operations=operations
    page['/Contents'][1]=writer._add_object(stream)
    out=BytesIO();writer.write(out)
    with pytest.raises(EditError,match='transformación no compatible'):
        change(out.getvalue(),'SOL','ESTRELLA',width=80)


def test_expanding_into_an_unselected_link_is_blocked_before_serializing():
    with fitz.open(stream=fixture(),filetype='pdf') as doc:
        doc[0].insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(65,70,100,90),'uri':'https://example.org/'})
        data=doc.tobytes()
    with pytest.raises(EditError,match='enlace'):
        change(data,'SOL','ESTRELLA',width=80)


def test_different_direct_font_resource_cannot_supply_missing_native_code():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(fixture())))
    page=writer.pages[0]
    fonts=page['/Resources']['/Font']
    fonts[NameObject('/cour')]=DictionaryObject(dict(fonts['/cour']))
    fonts[NameObject('/helv')]=DictionaryObject(dict(writer.pages[1]['/Resources']['/Font']['/helv']))
    stream=ContentStream(page.get_contents(),writer)
    operations=[]
    for args,op in stream.operations:
        if op==b'TJ':args=[ArrayObject([ByteStringObject(_raw(v).replace(b'Z',b'')) if isinstance(v,(str,bytes)) else v for v in args[0]])]
        operations.append((args,op))
    operations.extend([([],b'BT'),([NameObject('/helv'),NumberObject(10)],b'Tf'),
                       ([NumberObject(v) for v in (1,0,0,1,40,200)],b'Tm'),
                       ([ByteStringObject(b'Z')],b'Tj'),([],b'ET')])
    stream.operations=operations
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out)
    with pytest.raises(EditError,match='códigos únicos'):
        change(out.getvalue(),'SOL','ZOLA',width=80)
