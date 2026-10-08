"""Content outside widgets is editable only with full AcroForm preservation."""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DictionaryObject,
                           FloatObject, NameObject, TextStringObject)
import pytest

from pdfmodder.engine import edit_pdf, extract_page, full_write
from pdfmodder.model import EditError, EditRequest
from pdfmodder.validation import (assert_content_outside_widgets,
                                 assert_form_preservation, content_widget_issues,
                                 document_issues, form_preservation_snapshot,
                                 trace_chars, validate_transition)


def form_pdf(*, calculated=False):
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        page.insert_text((25,40), 'Texto exterior')
        for index, name in enumerate(('nombre', 'total')):
            widget = fitz.Widget()
            widget.field_name = name
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect = fitz.Rect(40,90+50*index,240,115+50*index)
            widget.field_value = 'Ana' if index == 0 else '3'
            widget.text_font = 'Helv'
            widget.text_fontsize = 11
            page.add_widget(widget)
        if calculated:
            page = doc[0]
            widget = next(w for w in page.widgets() if w.field_name == 'total')
            widget.script_calc = 'event.value = 1 + 2;'
            widget.update()
        doc.new_page(width=400, height=400).insert_text((25,40), 'Vecino intacto')
        source = doc.tobytes()
    def defaults(writer):
        resources = field(writer)['/AP']['/N']['/Resources']
        writer.root_object['/AcroForm'][NameObject('/DR')] = resources
    return rewrite(source, defaults)


def rewrite(source, mutate):
    writer = PdfWriter(clone_from=BytesIO(source))
    mutate(writer)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def field(writer, number=0):
    return writer.root_object['/AcroForm']['/Fields'][number].get_object()


@pytest.mark.parametrize('calculated', [False, True])
def test_regular_and_calculated_forms_allow_external_text_only(calculated):
    source = form_pdf(calculated=calculated)
    with fitz.open(stream=source, filetype='pdf') as doc:
        assert document_issues(source, doc, operation='content') == []
        assert any('formulario' in issue for issue in document_issues(source, doc))
        model = extract_page(doc,0,source)
        ids = [g.id for g in model.glyphs if g.origin[1] < 60]
    output, report = edit_pdf(source, EditRequest(0,ids,text='Texto editable', width=180))
    assert report['verified']
    assert_form_preservation(source, output)
    reader = PdfReader(BytesIO(output), strict=True)
    assert 'Texto editable' in reader.pages[0].extract_text()
    assert reader.get_fields()['nombre']['/V'] == 'Ana'
    assert reader.get_fields()['total']['/V'] == '3'
    if calculated:
        script = reader.get_fields()['total']['/AA']['/C']['/JS']
        logical = script.get_data().decode('utf-8') if hasattr(script,'get_data') else str(script)
        assert logical == 'event.value = 1 + 2;'


def test_form_snapshot_ignores_xref_renumbering_and_lossless_compression():
    source = form_pdf(calculated=True)
    with fitz.open(stream=source, filetype='pdf') as doc:
        output = full_write(doc)
    assert form_preservation_snapshot(source) == form_preservation_snapshot(output)


def test_external_text_move_preserves_hierarchical_widgets_and_calculations():
    source = hierarchical_form()
    with fitz.open(stream=source,filetype='pdf') as doc:
        model = extract_page(doc,0,source)
        selected = [g for g in model.glyphs if g.origin[1] < 60]
    output,report = edit_pdf(source,EditRequest(0,[g.id for g in selected],dx=8,dy=5))
    assert report['verified']
    assert_form_preservation(source,output)
    with fitz.open(stream=output,filetype='pdf') as doc:
        actual = trace_chars(doc[0])
    for glyph in selected:
        assert any(char == glyph.text and abs(origin[0]-glyph.origin[0]-8)<.035
                   and abs(origin[1]-glyph.origin[1]-5)<.035 for char,origin,*_ in actual)


def hierarchical_form():
    def split(writer):
        form = writer.root_object['/AcroForm']
        widget_ref = form['/Fields'][0]
        widget = widget_ref.get_object()
        parent = DictionaryObject({NameObject('/Kids'): ArrayObject([widget_ref])})
        for key in ('/FT','/T','/V','/DA'):
            parent[NameObject(key)] = widget.pop(NameObject(key))
        parent_ref = writer._add_object(parent)
        widget[NameObject('/Parent')] = parent_ref
        widget[NameObject('/P')] = writer.pages[0].indirect_reference
        form['/Fields'][0] = parent_ref
    return rewrite(form_pdf(calculated=True), split)


def test_parent_child_cycles_and_page_ownership_are_semantically_stable():
    source = hierarchical_form()
    with fitz.open(stream=source,filetype='pdf') as doc:
        assert document_issues(source,doc,operation='content') == []
        assert_form_preservation(source,full_write(doc))
    def parent(writer):
        child = field(writer)['/Kids'][0].get_object()
        child[NameObject('/Parent')] = writer.root_object['/AcroForm']['/Fields'][1]
    def page(writer):
        child = field(writer)['/Kids'][0].get_object()
        child[NameObject('/P')] = writer.pages[1].indirect_reference
    for mutation in (parent,page):
        with pytest.raises(EditError,match='AcroForm'):
            assert_form_preservation(source,rewrite(source,mutation))


def test_invalid_circular_child_tree_remains_blocked():
    def circular(writer):
        form = writer.root_object['/AcroForm']
        node = field(writer)
        node[NameObject('/Kids')] = ArrayObject([form['/Fields'][0]])
    source = rewrite(form_pdf(),circular)
    with fitz.open(stream=source,filetype='pdf') as doc:
        assert any('Kids circular' in issue for issue in document_issues(source,doc,operation='content'))


def _value(writer):
    field(writer)[NameObject('/V')] = TextStringObject('Valor cambiado sin actualizar apariencia')


def _rect(writer):
    values = list(field(writer)['/Rect'])
    values[0] = FloatObject(float(values[0]) + 1)
    field(writer)[NameObject('/Rect')] = ArrayObject(values)


def _script(writer):
    field(writer,1)['/AA']['/C'][NameObject('/JS')] = TextStringObject('event.value = 999;')


def _appearance(writer):
    appearance = field(writer)['/AP']['/N'].get_object()
    appearance.set_data(appearance.get_data() + b'\n% altered appearance\n')


def _defaults(writer):
    writer.root_object['/AcroForm'][NameObject('/NeedAppearances')] = BooleanObject(True)


def _font_resources(writer):
    font = writer.root_object['/AcroForm']['/DR']['/Font']['/Helv'].get_object()
    font[NameObject('/BaseFont')] = NameObject('/Courier')


def _calculation_order(writer):
    form = writer.root_object['/AcroForm']
    form[NameObject('/CO')] = ArrayObject([form['/Fields'][0]])


@pytest.mark.parametrize('mutation', [_value, _rect, _script, _appearance,
                                      _defaults, _font_resources, _calculation_order])
def test_all_field_semantics_are_preserved_even_when_not_visually_changed(mutation):
    source = form_pdf(calculated=True)
    output = rewrite(source, mutation)
    with pytest.raises(EditError, match='AcroForm'):
        assert_form_preservation(source, output)


def test_document_and_page_actions_are_preserved_without_executing_them():
    def scripts(writer):
        writer.add_js('global.calculo = 42;')
        writer.pages[0][NameObject('/AA')] = DictionaryObject({
            NameObject('/O'): DictionaryObject({NameObject('/S'): NameObject('/JavaScript'),
                                               NameObject('/JS'): TextStringObject('global.abierto = true;')})})
    source = rewrite(form_pdf(), scripts)
    with fitz.open(stream=source, filetype='pdf') as doc:
        assert document_issues(source, doc, operation='content') == []
        assert_form_preservation(source, full_write(doc))
    for mutate in (lambda writer: writer.root_object['/Names']['/JavaScript']['/Names'][1].get_object().__setitem__(
                       NameObject('/JS'),TextStringObject('global.calculo = 0;')),
                   lambda writer: writer.pages[0]['/AA']['/O'].__setitem__(
                       NameObject('/JS'),TextStringObject('global.abierto = false;'))):
        with pytest.raises(EditError, match='JavaScript'):
            assert_form_preservation(source,rewrite(source,mutate))


def test_content_exclusion_regions_cannot_hide_widget_changes():
    source = form_pdf()
    with fitz.open(stream=source, filetype='pdf') as doc:
        assert content_widget_issues(doc[0],[(25,20,150,45)]) == []
        assert content_widget_issues(doc[0],[(50,95,80,110)])
        with pytest.raises(EditError,match='Editar formularios'):
            assert_content_outside_widgets(doc[0],[(50,95,80,110)])
        expected = trace_chars(doc[0])
    with pytest.raises(EditError,match='campo interactivo'):
        validate_transition(source,source,0,expected,[(30,80,250,130)])


def test_validator_rejects_invisible_field_value_change():
    source = form_pdf()
    output = rewrite(source,_value)
    with fitz.open(stream=source,filetype='pdf') as doc:
        expected = trace_chars(doc[0])
    with pytest.raises(EditError,match='AcroForm'):
        validate_transition(source,output,0,expected,[])


@pytest.mark.parametrize('protected', ['encrypted','signature','xfa'])
def test_content_permission_does_not_remove_encryption_signature_or_xfa_guards(protected):
    source = form_pdf()
    if protected == 'encrypted':
        with fitz.open(stream=source,filetype='pdf') as doc:
            source = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                                owner_pw='owner-test',user_pw='',permissions=fitz.PDF_PERM_PRINT)
    elif protected == 'signature':
        source = rewrite(source,lambda writer: field(writer).__setitem__(NameObject('/FT'),NameObject('/Sig')))
    else:
        source = rewrite(source,lambda writer: writer.root_object['/AcroForm'].__setitem__(
            NameObject('/XFA'),TextStringObject('<xfa/>')))
    with fitz.open(stream=source,filetype='pdf') as doc:
        issues = document_issues(source,doc,operation='content')
    words = {'encrypted':'cifrado','signature':'firma','xfa':'XFA'}
    assert any(words[protected] in issue for issue in issues)
