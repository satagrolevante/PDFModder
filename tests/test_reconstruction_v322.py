"""Explicit reconstruction removes source glyphs instead of covering them."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                          FloatObject, NameObject, NumberObject)
import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog

from pdfmodder.engine import extract_page
from pdfmodder.fonts import FontResolver
from pdfmodder.model import EditError
from pdfmodder.reconstruct_text_v322 import reconstruction_selection, reconstruction_issues
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf
from test_editing_extensions_v322 import custom_cmap_document, FONT
from test_rich_ui_v09 import window, idle, select


def type3_document():
    with fitz.open() as doc:
        page=doc.new_page(width=340,height=220)
        page.draw_rect((15,20,320,90),fill=(.9,.95,.8),color=None)
        page.insert_text((150,50),'NEIGHBOR',fontsize=12)
        page.insert_text((30,160),'CONTROL',fontsize=12)
        doc.new_page(width=340,height=220).insert_text((30,50),'OTHER PAGE')
        source=doc.tobytes()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    chars=DictionaryObject()
    for name,color in [('/A','0 0 1'),('/B','0 .5 0')]:
        glyph=DecodedStreamObject()
        # d0 glyphs own their colors: the normal marker-color probe cannot
        # map these letters to a SHOW by changing rg before that SHOW.
        glyph.set_data(f'600 0 d0 {color} rg 40 0 520 700 re f'.encode())
        chars[NameObject(name)]=writer._add_object(glyph)
    cmap=DecodedStreamObject();cmap.set_data(b'''/CIDInit /ProcSet findresource begin
12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Type3Unicode def /CMapType 2 def
1 begincodespacerange <00> <ff> endcodespacerange
2 beginbfchar <01> <0041> <02> <0042> endbfchar
endcmap CMapName currentdict /CMap defineresource pop end end''')
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type3'),
        NameObject('/Name'):NameObject('/T3'),NameObject('/CharProcs'):chars,
        NameObject('/FontBBox'):ArrayObject([NumberObject(x) for x in (0,0,600,700)]),
        NameObject('/FontMatrix'):ArrayObject([FloatObject(.001),NumberObject(0),NumberObject(0),FloatObject(.001),NumberObject(0),NumberObject(0)]),
        NameObject('/FirstChar'):NumberObject(1),NameObject('/LastChar'):NumberObject(2),
        NameObject('/Widths'):ArrayObject([NumberObject(600),NumberObject(600)]),
        NameObject('/Encoding'):DictionaryObject({NameObject('/Type'):NameObject('/Encoding'),
            NameObject('/Differences'):ArrayObject([NumberObject(1),NameObject('/A'),NameObject('/B')])}),
        NameObject('/ToUnicode'):writer._add_object(cmap),NameObject('/Resources'):DictionaryObject()})
    page=writer.pages[0];page['/Resources']['/Font'][NameObject('/T3')]=writer._add_object(font)
    stream=DecodedStreamObject();stream.set_data(b'q BT /T3 16 Tf 1 0 0 1 30 170 Tm <0102> Tj ET Q')
    page[NameObject('/Contents')]=ArrayObject([*page['/Contents'],writer._add_object(stream)])
    output=BytesIO();writer.write(output)
    return output.getvalue()


def selection_for(data,text):
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,0,data)
    joined=''.join(g.text for g in model.glyphs);start=joined.index(text)
    return model,[g.id for g in model.glyphs[start:start+len(text)]]


def assert_source_removed_and_controls_preserved(source,output,old,new):
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        trace=''.join(chr(c[0]) for span in after[0].get_texttrace() for c in span['chars'])
        assert new in trace and old not in trace
        assert 'CONTROL' in trace
        if len(before)>1:
            assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert before[0].get_pixmap(clip=(135,0,340,220)).samples==after[0].get_pixmap(clip=(135,0,340,220)).samples
        drawings=lambda p:[{k:v for k,v in d.items() if k!='seqno'} for d in p.get_drawings()]
        assert drawings(before[0])==drawings(after[0])
    assert old not in PdfReader(BytesIO(output)).pages[0].extract_text()


def test_type3_colored_glyphs_reconstruct_without_cover_or_neighbor_loss():
    source=type3_document();model,ids=selection_for(source,'AB')
    payload=reconstruction_selection(source,0,ids,FontResolver())
    request=RichTextRequest(0,ids,[dict(text='NUEVO',font_name='LiberationSans',font_file=FONT,
        size=12,color=(0,0,0),opacity=1)],rect=payload['rect'],revision=model.revision,
        auto_width=True,auto_height=True,auto_adapt=True,reconstruct=True)
    output,report=edit_rich_pdf(source,request)
    assert report['verified'] and report['reconstruction']
    assert_source_removed_and_controls_preserved(source,output,'AB','NUEVO')


def test_gui_reconstruction_is_explicit_preview_cancel_apply_save_and_undo(qtbot,window,tmp_path,monkeypatch):
    source=custom_cmap_document();path=tmp_path/'ambiguous-font.pdf';path.write_bytes(source)
    window.open_document(path);idle(qtbot,window)
    select(window,'Texto original');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible() or bool(window.last_error),timeout=15000)
    assert window.canvas.editor.isVisible(),window.last_error
    assert window.reconstruct_button_v322.isVisible()
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.select(QTextCursor.Document);cursor.insertText('Texto reconstruido')
    window._rich_timer.stop()  # Test the explicit choice before submitting the obsolete ordinary draft.
    before=editor.payload()
    monkeypatch.setattr(window,'_exec_edit_dialog',lambda dialog:QDialog.Rejected)
    window._reconstruct_block_v322()
    assert editor.payload()==before and not editor.payload().get('reconstruct')
    assert window.state['history_index']==0 and path.read_bytes()==source
    monkeypatch.setattr('pdfmodder.font_choice_ui_v321.QFileDialog.getOpenFileName',lambda *args:(FONT,'Fuentes (*.ttf *.otf)'))
    def choose(dialog):
        dialog.import_font();dialog.accept();return dialog.result()
    monkeypatch.setattr(window,'_exec_edit_dialog',choose)
    window._reconstruct_block_v322();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert editor.payload()['reconstruct'] and window.state['history_index']==0
    assert 'validado' in window.rich_result_message.text().lower()
    window.cancel();idle(qtbot,window)
    assert window.state['history_index']==0 and path.read_bytes()==source
    select(window,'Texto original');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=15000)
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.select(QTextCursor.Document);cursor.insertText('Texto reconstruido')
    window._rich_timer.stop();window._reconstruct_block_v322();idle(qtbot,window)
    editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==1
    target=tmp_path/'reconstructed.pdf';window.save_as(target);idle(qtbot,window)
    assert_source_removed_and_controls_preserved(source,target.read_bytes(),'Texto original','Texto reconstruido')
    window.history('undo');idle(qtbot,window)
    assert 'Texto original' in ''.join(g.text for g in window.model.glyphs)
    assert path.read_bytes()==source


@pytest.mark.parametrize('kind',['link','widget','annotation','signed','tagged'])
def test_reconstruction_is_not_advertised_for_semantic_or_protected_regions(kind):
    if kind=='tagged':
        from tagged_corpus import make_tagged_pdf
        source=make_tagged_pdf();model,ids=selection_for(source,'10/09/2026')
    else:
        source=type3_document()
        if kind=='signed':
            writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
            writer.root_object[NameObject('/Perms')]=DictionaryObject({NameObject('/DocMDP'):DictionaryObject({NameObject('/Type'):NameObject('/Sig')})})
            output=BytesIO();writer.write(output);source=output.getvalue()
        else:
            with fitz.open(stream=source,filetype='pdf') as doc:
                page=doc[0]
                if kind=='link':
                    page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(28,30,80,65),'uri':'https://example.org'})
                elif kind=='widget':
                    field=fitz.Widget();field.field_type=fitz.PDF_WIDGET_TYPE_TEXT;field.field_name='input'
                    field.rect=fitz.Rect(28,30,80,65);page.add_widget(field)
                else:
                    page.add_rect_annot((28,30,80,65)).update()
                source=doc.tobytes()
        model,ids=selection_for(source,'AB')
    assert reconstruction_issues(source,model,model.selected(ids))
    with pytest.raises(EditError):
        reconstruction_selection(source,0,ids,FontResolver())
