"""Independent form values remain editable without executing stored scripts."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from pdfmodder.font_choice_v321 import FontChoiceRequired
from pdfmodder.forms_redaction_v200 import form_fields_pdf, edit_form_field_pdf, atomic_save_form_pdf, _script_snapshot, _pdf_value
from pdfmodder.model import EditError
from pdfmodder.tools_v200 import FormEditorDialog
from test_forms_redaction_media_v200 import form_pdf
from test_fonts import make_font


FONT=Path(__file__).resolve().parents[1]/'assets/fonts/LiberationSans-Regular.ttf'
CHOICE={'name':'LiberationSans','path':str(FONT)}


def scripted(source, code, *, document=False):
    if not document:
        with fitz.open(stream=source,filetype='pdf') as doc:
            page=doc[0];widget=next(w for w in page.widgets() if w.field_name=='nombre')
            widget.script_calc=code;widget.update()
            return doc.tobytes()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)))
    action=DictionaryObject({NameObject('/S'):NameObject('/JavaScript'),NameObject('/JS'):TextStringObject(code)})
    writer.root_object[NameObject('/Names')]=DictionaryObject({NameObject('/JavaScript'):DictionaryObject({
        NameObject('/Names'):ArrayObject([TextStringObject('stored-script'),writer._add_object(action)])})})
    out=BytesIO();writer.write(out);return out.getvalue()


def field(data,name='aceptado'):
    return next(f for f in form_fields_pdf(data)['fields'] if f['name']==name)


@pytest.mark.parametrize('code',[
    'event.value = 1 + 2;',
    'event.value = this.getField("nombre").value;',
    'AFSimple_Calculate("SUM", ["nombre"]);',
])
def test_independent_field_in_calculated_document_is_editable_and_scripts_remain(code):
    source=scripted(form_pdf(),code)
    selected=field(source)
    assert selected['value_editable'] and not field(source,'nombre')['value_editable']
    output,report=edit_form_field_pdf(source,0,selected['xref'],{'value':True})
    assert report['verified'] and field(output)['checked']
    assert field(output,'nombre')['value']=='Ana'
    assert _script_snapshot(PdfReader(BytesIO(source)))==_script_snapshot(PdfReader(BytesIO(output)))
    assert _pdf_value(PdfReader(BytesIO(source)).get_fields()['nombre']['/AA'])==_pdf_value(PdfReader(BytesIO(output)).get_fields()['nombre']['/AA'])


@pytest.mark.parametrize('code',[
    'event.value = this.getField("aceptado").value ? 2 : 1;',
    'AFSimple_Calculate("SUM", ["aceptado"]);',
])
def test_fields_referenced_by_calculation_stay_protected(code):
    source=scripted(form_pdf(),code)
    selected=field(source)
    assert not selected['value_editable'] and 'nombre' in selected['dependencies']
    with pytest.raises(EditError,match='JavaScript'):
        edit_form_field_pdf(source,0,selected['xref'],{'value':True})


@pytest.mark.parametrize('code',[
    'var name = "acep" + "tado"; event.value = this.getField(name).value;',
    'event.value = this["getField"]("aceptado").value;',
    'event.value = externalFunction();',
    'app["unknownMethod"]();',
    'event.value = event.source.value;',
])
def test_dynamic_or_external_dependencies_are_not_guessed(code):
    source=scripted(form_pdf(),code)
    listing=form_fields_pdf(source)
    assert listing['dependency_analysis']['unknown_dependencies']
    assert not field(source)['value_editable']


def test_literal_document_references_only_block_related_fields_and_never_execute():
    source=scripted(form_pdf(),'this.getField("nombre").value = "CHANGED BY SCRIPT";',document=True)
    assert field(source)['value_editable'] and not field(source,'nombre')['value_editable']
    output,_=edit_form_field_pdf(source,0,field(source)['xref'],{'value':True})
    assert field(output,'nombre')['value']=='Ana'
    assert _script_snapshot(PdfReader(BytesIO(source)))==_script_snapshot(PdfReader(BytesIO(output)))


def test_comments_and_string_content_cannot_invent_field_dependencies():
    source=scripted(form_pdf(),'// this.getField(dynamicName)\napp.alert("getField(name) is just a label");',document=True)
    assert not form_fields_pdf(source)['dependency_analysis']['unknown_dependencies']
    assert field(source)['value_editable']


def test_hierarchical_reference_protects_descendant_field():
    with fitz.open(stream=form_pdf(),filetype='pdf') as doc:
        page=doc[0];w=next(w for w in page.widgets() if w.field_name=='aceptado')
        w.field_name='group.aceptado';w.update();source=doc.tobytes()
    source=scripted(source,'event.value=this.getField("group").value;')
    assert not field(source,'group.aceptado')['value_editable']


def test_calculation_order_without_script_still_protects_its_target():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(form_pdf())))
    form=writer.root_object['/AcroForm']
    form[NameObject('/CO')]=ArrayObject([form['/Fields'][0]])
    out=BytesIO();writer.write(out);source=out.getvalue()
    assert not field(source,'nombre')['value_editable']
    assert field(source)['value_editable']


def test_document_javascript_tampering_is_rejected(monkeypatch):
    import pdfmodder.forms_redaction_v200 as forms
    source=scripted(form_pdf(),'this.getField("nombre").value="Ana";',document=True)
    action=PdfReader(BytesIO(source)).trailer['/Root']['/Names']['/JavaScript']['/Names'][1].idnum
    write=forms.full_write
    def changed(doc):
        doc.xref_set_key(action,'JS',fitz.get_pdf_str('this.getField("nombre").value="OTHER";'))
        return write(doc)
    monkeypatch.setattr(forms,'full_write',changed)
    with pytest.raises(EditError,match='scripts'):
        edit_form_field_pdf(source,0,field(source)['xref'],{'value':True})


def test_gui_exposes_independent_values_and_explicit_font_choice(qtbot):
    listing=form_fields_pdf(form_pdf(True));listing['catalog']=[CHOICE]
    dialog=FormEditorDialog(listing);qtbot.addWidget(dialog)
    assert not dialog.change_value.isEnabled()
    dialog.table.setCurrentCell(1,0)
    assert dialog.change_value.isEnabled()
    dialog.change_value.setChecked(True)
    assert dialog.operation()['changes']=={'value':False}


def test_gui_font_choice_uses_shared_picker_and_produces_real_verified_preview(qtbot,monkeypatch):
    source=form_pdf();listing=form_fields_pdf(source);listing['catalog']=[CHOICE]
    dialog=FormEditorDialog(listing);qtbot.addWidget(dialog)
    def choose(picker):
        picker.entry=dict(CHOICE)
        return QDialog.Accepted
    monkeypatch.setattr('pdfmodder.font_choice_ui_v321.FontChoiceDialog.exec',choose)
    dialog._choose_font_v322()
    assert dialog.change_font.isChecked() and dialog.accept_button.isEnabled()
    operation=dialog.operation()
    assert operation['changes']=={'font':CHOICE}
    output,report=edit_form_field_pdf(source,**operation)
    assert report['verified'] and field(output,'nombre')['font'].startswith('PMForm')


def test_missing_original_characters_offer_shared_font_choice():
    source=form_pdf();selected=field(source,'nombre')
    with pytest.raises(FontChoiceRequired) as error:
        edit_form_field_pdf(source,0,selected['xref'],{'value':'漢字'})
    assert error.value.text=='漢字'


def test_explicit_font_value_save_reopen_and_later_reedit(tmp_path):
    source=form_pdf();selected=field(source,'nombre')
    output,report=edit_form_field_pdf(source,0,selected['xref'],{'value':'Клиент Ω','font':CHOICE})
    assert report['verified'] and report['font_choice'][0]['explicit']
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert any(s['font']=='LiberationSans' and ''.join(chr(c[0]) for c in s['chars'])=='Клиент Ω'
                   for s in doc[0].get_texttrace())
    original=tmp_path/'original.pdf';original.write_bytes(source)
    saved=tmp_path/'saved.pdf';atomic_save_form_pdf(output,saved,original)
    selected=field(saved.read_bytes(),'nombre')
    edited,report=edit_form_field_pdf(saved.read_bytes(),0,selected['xref'],{'value':'SANDÍA Ñ'})
    assert report['verified'] and field(edited,'nombre')['value']=='SANDÍA Ñ'
    assert field(edited,'nombre')['font']==selected['font']
    assert original.read_bytes()==source


def test_font_can_change_without_mutating_value_or_other_field():
    source=form_pdf();selected=field(source,'nombre')
    output,report=edit_form_field_pdf(source,0,selected['xref'],{'font':CHOICE})
    assert report['verified'] and field(output,'nombre')['value']=='Ana'
    assert field(output)['value']==field(source)['value']


def test_restricted_or_incomplete_font_is_not_silently_substituted(tmp_path):
    source=form_pdf();selected=field(source,'nombre')
    incomplete=make_font(tmp_path/'partial.ttf',text=' SANDIA')
    with pytest.raises(FontChoiceRequired):
        edit_form_field_pdf(source,0,selected['xref'],{'value':'SANDÍA','font':{'name':'Partial','path':str(incomplete)}})
    restricted=make_font(tmp_path/'restricted.ttf',flags=2)
    with pytest.raises(FontChoiceRequired):
        edit_form_field_pdf(source,0,selected['xref'],{'font':{'name':'Restricted','path':str(restricted)}})


def test_list_font_keeps_all_choices_labels_and_selection():
    with fitz.open(stream=form_pdf(),filetype='pdf') as doc:
        page=doc[0];widget=fitz.Widget();widget.field_name='lista'
        widget.field_type=fitz.PDF_WIDGET_TYPE_LISTBOX;widget.rect=fitz.Rect(40,200,240,280)
        widget.choice_values=['UNO','DOS','TRES'];widget.field_value='DOS'
        widget.text_font='Helv';widget.text_fontsize=11;page.add_widget(widget)
        source=doc.tobytes()
    selected=field(source,'lista')
    output,report=edit_form_field_pdf(source,0,selected['xref'],{'font':CHOICE})
    assert report['verified'] and field(output,'lista')['value']=='DOS'
    assert field(output,'lista')['choices']==selected['choices']
    with fitz.open(stream=output,filetype='pdf') as doc:
        labels=[''.join(chr(c[0]) for c in span['chars']) for span in doc[0].get_texttrace() if span['font']=='LiberationSans']
        assert labels==['UNO','DOS','TRES']


def test_comb_font_keeps_each_character_in_its_slot():
    with fitz.open(stream=form_pdf(),filetype='pdf') as doc:
        page=doc[0];widget=next(w for w in page.widgets() if w.field_name=='nombre')
        widget.field_flags=fitz.PDF_TX_FIELD_IS_COMB;widget.text_maxlen=8
        widget.field_value='12345678';widget.update();source=doc.tobytes()
    selected=field(source,'nombre')
    output,report=edit_form_field_pdf(source,0,selected['xref'],{'font':CHOICE})
    assert report['verified'] and field(output,'nombre')['value']=='12345678'
    with fitz.open(stream=output,filetype='pdf') as doc:
        glyphs=[c for span in doc[0].get_texttrace() if span['font']=='LiberationSans' for c in span['chars']]
        assert ''.join(chr(c[0]) for c in glyphs)=='12345678'
        assert [round(glyphs[i+1][2][0]-glyphs[i][2][0],3) for i in range(7)]==[25.]*7
