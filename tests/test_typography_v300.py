"""Native shaping, cluster reopening and copying with original generated fonts."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import build
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.fonts import FontError, FontResolver, instantiate_variable_font
from pdfmodder.model import EditError
from pdfmodder.reading_order_v180 import selection_text
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.typography_v300 import preflight_shaping


SAMPLE = 'office q\u0308 שלום 123 עולם مرحبا 123 بالعالم مَرْحَبًا'


def make_shaping_font(path, width=600):
    """CC0 rectangle outlines plus real GSUB/GPOS tables, no downloaded fonts."""
    points = sorted(set(map(ord, SAMPLE + 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')))
    names = ['.notdef'] + [f'uni{cp:04X}' for cp in points] + ['f_f_i']
    arabic = [f'uni{cp:04X}' for cp in points if 0x600 <= cp < 0x700 and not 0x64B <= cp <= 0x652]
    names += [name + suffix for name in arabic for suffix in ('.init', '.medi', '.fina')]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({cp: f'uni{cp:04X}' for cp in points})
    glyphs, metrics = {}, {}
    for name in names:
        mark = name == 'uni0308' or name.startswith(('uni064E', 'uni0652', 'uni064B'))
        advance = 0 if mark else width * 1.5 if name == 'f_f_i' else width
        pen = TTGlyphPen(None)
        if name != 'uni0020':
            pen.moveTo((40, 0))
            pen.lineTo((140 if mark else advance-40, 0))
            pen.lineTo((140 if mark else advance-40, 80 if mark else 650))
            pen.lineTo((40, 80 if mark else 650))
            pen.closePath()
        glyphs[name] = pen.glyph()
        metrics[name] = (advance, 40)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(dict(familyName='PDFModder Shaping Test', styleName='Regular',
        uniqueFontIdentifier='PDFModderShapingTest', fullName='PDFModderShapingTest',
        psName='PDFModderShapingTest', licenseDescription='Original test font; CC0.'))
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200, fsType=0)
    builder.setupPost()
    builder.setupMaxp()
    features = '''languagesystem DFLT dflt;
languagesystem latn dflt;
languagesystem arab dflt;
feature liga { sub uni0066 uni0066 uni0069 by f_f_i; } liga;
markClass uni0308 <anchor 0 0> @TOP;
feature mark { pos base uni0071 <anchor 300 700> mark @TOP; } mark;
'''
    for feature, suffix in [('init', '.init'), ('medi', '.medi'), ('fina', '.fina')]:
        features += f'feature {feature} {{\n' + '\n'.join(f'sub {n} by {n}{suffix};' for n in arabic) + f'\n}} {feature};\n'
    addOpenTypeFeaturesFromString(builder.font, features)
    builder.save(path)
    return path


@pytest.fixture
def shaping_font(tmp_path):
    return make_shaping_font(tmp_path / 'shaping.ttf')


def document(form=False):
    with fitz.open() as doc:
        page = doc.new_page(width=420, height=300)
        page.insert_text((35, 40), 'ORIGINAL', fontsize=11)
        page.insert_text((35, 220), 'VECINO INTACTO', fontsize=11)
        page.draw_line((20, 190), (395, 190), color=(.2, .3, .5))
        if form:
            widget = fitz.Widget()
            widget.field_name = 'Nombre'
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = 'Valor conservado'
            widget.rect = fitz.Rect(220, 230, 390, 260)
            page.add_widget(widget)
        return doc.tobytes()


def insert(data, font, text, **values):
    run = dict(text=text, font_name='PDFModderShapingTest', font_file=str(font), size=12,
               color=(0., 0., 0.), font_features={'liga': 1})
    return edit_rich_pdf(data, RichTextRequest(0, [], [run], rect=(35, 75, 390, 170), **values))


def shaped_model(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
    ids = [g.id for g in model.glyphs if g.font != 'Helvetica']
    return model, ids


def test_ligatures_have_real_substitution_and_reopen_as_whole_unicode_clusters(shaping_font):
    before = document()
    output, report = insert(before, shaping_font, 'office')
    assert report['verified'] and report['shaping_engine'] == 'HarfBuzz'
    assert any(c['text'] == 'ffi' and c['end']-c['start'] == 3 for c in report['clusters'])
    model, ids = shaped_model(output)
    assert model.text(ids) == 'office' and not model.issues
    assert 'office' in PdfReader(BytesIO(output)).pages[0].extract_text()
    ligature = next(c for c in model.logical_text_runs[0]['clusters'] if c['text'] == 'ffi')
    payload = selection_payload(output, 0, ligature['ids'][:1])
    assert payload['text'] == 'ffi' and len(payload['ids']) == 3
    changed, _ = edit_rich_pdf(output, RichTextRequest(0, payload['ids'],
        [dict(payload['runs'][0], text='X')], rect=payload['rect'], auto_width=True, auto_height=True))
    final, selected = shaped_model(changed)
    assert final.text(selected) == 'oXce'
    assert selection_payload(changed, 0, selected)['text'] == 'oXce'
    assert 'office' not in final.text(selected)
    with fitz.open(stream=changed, filetype='pdf') as doc:
        assert 'ORIGINAL' in doc[0].get_text() and 'VECINO INTACTO' in doc[0].get_text()


def test_nonprecomposable_mark_uses_positioned_glyph_and_no_added_unicode(shaping_font):
    output, report = insert(document(), shaping_font, 'q\u0308')
    assert report['auxiliary_glyphs'] == 1
    model, ids = shaped_model(output)
    assert model.text(ids) == 'q\u0308'
    assert len(model.logical_text_runs[0]['clusters']) == 1
    assert '\ufffd' not in model.text(ids)
    extracted = PdfReader(BytesIO(output)).pages[0].extract_text()
    assert 'q\u0308' in extracted and '\u200b' not in extracted
    payload = selection_payload(output, 0, ids)
    second, checked = edit_rich_pdf(output, RichTextRequest(0, payload['ids'], payload['runs'], rect=payload['rect']))
    assert checked['verified'] and shaped_model(second)[0].text(shaped_model(second)[1]) == 'q\u0308'


def test_equal_format_runs_shape_as_one_item_but_different_format_marks_refuse(shaping_font):
    style = dict(font_name='PDFModderShapingTest', font_file=str(shaping_font),
                 size=12, font_features={'liga':1})
    runs = [dict(style, text=character) for character in 'office q\u0308']
    output, report = edit_rich_pdf(document(), RichTextRequest(0, [], runs, rect=(35,75,390,170)))
    assert report['verified'] and any(c['text'] == 'ffi' for c in report['clusters'])
    model, ids = shaped_model(output)
    assert model.text(ids) == 'office q\u0308'
    runs = [dict(style, text='q'), dict(style, text='\u0308', color=(1.,0.,0.))]
    with pytest.raises(EditError, match='marca combinante cruza'):
        edit_rich_pdf(document(), RichTextRequest(0, [], runs, rect=(35,75,390,170)))


@pytest.mark.parametrize('text', ['שלום 123 עולם', 'مرحبا 123 بالعالم', 'مَرْحَبًا'])
def test_bidi_copy_in_pdfmodder_is_logical_in_reading_and_editing_with_form(shaping_font, tmp_path, text):
    from pdfmodder.worker import Session
    from pdfmodder.clipboard_ops_v170 import copy_selection_v170
    before = document(form=True)
    output, report = insert(before, shaping_font, text)
    assert report['verified'] and report['bidi_engine'] == 'Unicode bidi'
    model, ids = shaped_model(output)
    assert model.text(ids) == text
    assert selection_payload(output, 0, ids)['text'] == text
    path = tmp_path / 'shaped.pdf'
    path.write_bytes(output)
    session = Session(path, reading=True, history_dir=tmp_path/'history')
    try:
        assert session.copy_reading_selection(0, ids=ids)['text'] == text
        assert session.reading_copy_range(dict(page=0, id=ids[0]), dict(page=0, id=ids[-1]), session.history.revision)['text'] == text
        session.prepare_editing(0)
        assert copy_selection_v170(session, 0, ids=ids)['text'] == text
    finally:
        session.close()
    with fitz.open(stream=output, filetype='pdf') as doc:
        assert [(w.field_name, w.field_value) for w in doc[0].widgets()] == [('Nombre', 'Valor conservado')]
    assert all(p['pixels_above_8'] == 0 for p in report['pages'])


def test_partial_edit_keeps_other_font_resources_and_logical_metadata(shaping_font):
    output, _ = insert(document(), shaping_font, 'office office')
    model, ids = shaped_model(output)
    clusters = model.logical_text_runs[0]['clusters']
    chosen = [i for c in clusters if c['start'] >= 7 for i in c['ids']]
    payload = selection_payload(output, 0, chosen)
    changed, _ = edit_rich_pdf(output, RichTextRequest(0, payload['ids'],
        [dict(payload['runs'][0], text='office')], rect=payload['rect'], auto_width=True, auto_height=True))
    final, ids = shaped_model(changed)
    assert final.text(ids) == 'office office'
    assert selection_payload(changed, 0, ids)['text'] == 'office office'
    assert not final.issues
    assert len({g.font_xref for g in final.selected(ids)}) == 2


def make_variable_font(tmp_path):
    design = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name, axis.tag, axis.minimum, axis.default, axis.maximum = 'Weight', 'wght', 100, 100, 900
    design.addAxis(axis)
    for value, width in [(100, 600), (900, 800)]:
        path = make_shaping_font(tmp_path / f'master-{value}.ttf', width)
        source = SourceDescriptor()
        source.path, source.name, source.location = str(path), str(value), {'Weight': value}
        source.copyInfo = source.copyLib = source.copyFeatures = value == 100
        design.addSource(source)
    font, _, _ = build(design)
    path = tmp_path / 'variable.ttf'
    font.save(path)
    return path


def test_variable_axes_produce_distinct_static_verified_instances(tmp_path):
    path = make_variable_font(tmp_path)
    original = path.read_bytes()
    narrow, proof = instantiate_variable_font(original, {'wght': 100})
    wide, other = instantiate_variable_font(original, {'wght': 900})
    assert narrow != wide and proof['source_sha256'] == sha256(original).hexdigest()
    assert proof['instance_sha256'] != other['instance_sha256']
    assert proof['instance_verified']
    with TTFont(BytesIO(wide)) as font:
        assert 'fvar' not in font and 'gvar' not in font and font['OS/2'].fsType == 0
    with pytest.raises(FontError, match='debe estar'):
        instantiate_variable_font(original, {'wght': 1000})
    with pytest.raises(FontError, match='desconocidos'):
        instantiate_variable_font(original, {'fake': 1})
    run = dict(text='office', font_name='PDFModderShapingTest', font_file=str(path), size=12, font_axes={'wght': 600})
    output, report = edit_rich_pdf(document(), RichTextRequest(0, [], [run], rect=(35, 75, 390, 170)))
    assert report['verified'] and all(f['instance_verified'] for f in report['fonts'].values())
    assert selection_payload(output, 0, shaped_model(output)[1])['runs'][0]['font_axes'] == {'wght': 600.}


def test_overflow_and_partial_cluster_refuse_without_changing_snapshot(shaping_font):
    data = document()
    digest = sha256(data).hexdigest()
    with pytest.raises(EditError, match='anchura|clúster'):
        edit_rich_pdf(data, RichTextRequest(0, [], [dict(text='office',font_file=str(shaping_font),font_features={'liga':1})], rect=(35,75,36,170)))
    assert sha256(data).hexdigest() == digest
    output, _ = insert(data, shaping_font, 'office')
    model, ids = shaped_model(output)
    assert preflight_shaping(output, 0, ids)['status'] == 'available'
    cluster = next(c for c in model.logical_text_runs[0]['clusters'] if c['text'] == 'ffi')
    payload = selection_payload(output, 0, cluster['ids'])
    with pytest.raises(EditError, match='clúster completo'):
        edit_rich_pdf(output, RichTextRequest(0, cluster['ids'][:1], payload['runs'], rect=payload['rect']))


def test_unrelated_mark_or_tampered_metadata_never_authorizes_page(shaping_font):
    output, _ = insert(document(), shaping_font, 'office')
    with fitz.open(stream=output, filetype='pdf') as doc:
        page = doc[0]
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        original = b'\n'.join(doc.xref_stream(xref) for xref in page.get_contents())
        doc.update_stream(stream, original + b'\n/Unrelated BMC EMC\n')
        page.set_contents(stream)
        damaged = doc.tobytes()
    model, ids = shaped_model(damaged)
    assert any('marcado' in issue for issue in model.issues)
    assert preflight_shaping(damaged, 0, ids)['status'] == 'blocked'


def test_move_preserves_codes_clusters_logical_copy_and_reediting(shaping_font):
    from pdfmodder.engine import edit_pdf
    from pdfmodder.model import EditRequest
    output, _ = insert(document(), shaping_font, 'office q\u0308')
    model, ids = shaped_model(output)
    moved, report = edit_pdf(output, EditRequest(0, ids, dx=15, dy=22))
    final, chosen = shaped_model(moved)
    assert report['verified'] and report['rich_text_move']
    assert final.text(chosen) == 'office q\u0308'
    for before, after in zip(model.selected(ids), final.selected(chosen)):
        assert after.origin == pytest.approx((before.origin[0]+15, before.origin[1]+22), abs=.035)
    payload = selection_payload(moved, 0, chosen)
    assert payload['text'] == 'office q\u0308'
    again, checked = edit_rich_pdf(moved, RichTextRequest(0, payload['ids'], payload['runs'], rect=payload['rect']))
    assert checked['verified'] and shaped_model(again)[0].text(shaped_model(again)[1]) == 'office q\u0308'


def test_shaped_move_save_reopen_and_panel_reedit_keep_logical_bidi_and_clusters(shaping_font, tmp_path):
    from pdfmodder.engine import atomic_save, edit_pdf
    from pdfmodder.model import EditRequest
    from pdfmodder.validation import assert_text_object_structure
    original = 'office q\u0308 שלום 123 עולם'
    replacement = 'office q\u0308 עולם 123 שלום'
    output, _ = insert(document(form=True), shaping_font, original)
    _, ids = shaped_model(output)
    moved, _ = edit_pdf(output, EditRequest(0, ids, dx=12, dy=10))
    path = tmp_path/'panel-bidi.pdf'
    atomic_save(moved, path)
    reopened = path.read_bytes()
    _, ids = shaped_model(reopened)
    result, report = edit_pdf(reopened, EditRequest(0, ids, text=replacement, auto_width=True, auto_height=True))
    assert report['verified'] and report['native_panel'] and report['shaping_engine'] == 'HarfBuzz'
    assert_text_object_structure(result)
    model, ids = shaped_model(result)
    from pdfmodder.reading_order_v180 import ordered_glyphs
    logical = [g for g in ordered_glyphs(model) if g.id in ids]
    assert model.text(ids) == replacement
    assert selection_text(model, logical[0].id, logical[-1].id) == replacement
    payload = selection_payload(result, 0, ids)
    assert payload['text'] == replacement and any(r.get('font_features', {}).get('liga') == 1 for r in payload['runs'])
    with fitz.open(stream=result, filetype='pdf') as doc:
        assert [(w.field_name, w.field_value) for w in doc[0].widgets()] == [('Nombre', 'Valor conservado')]
        assert 'VECINO INTACTO' in doc[0].get_text()


def test_advanced_tabs_soft_breaks_and_auto_area_preserve_logical_text(shaping_font):
    text = 'q\u0308\tABC\u2028DEF\nשלום\t123'
    output, report = insert(document(), shaping_font, text,
        paragraphs=[dict(tab_stops=[64],left_indent=5,first_indent=7,right_indent=8)],
        auto_width=True, auto_height=True)
    assert report['line_count'] == 3
    model, ids = shaped_model(output)
    assert model.text(ids) == text
    payload = selection_payload(output, 0, ids)
    assert payload['text'] == text
    assert report['area_width'] >= 64+5+7+8
    repeated, checked = edit_rich_pdf(output, RichTextRequest(0, payload['ids'], payload['runs'],
        rect=payload['rect'], paragraphs=payload['paragraphs'],auto_width=True,auto_height=True))
    assert checked['verified'] and shaped_model(repeated)[0].text(shaped_model(repeated)[1]) == text


def test_editor_exposes_real_axes_features_direction_and_cluster_caret(qtbot, tmp_path):
    from PySide6.QtGui import QTextCursor
    from pdfmodder.rich_editor import PageEditor, PARAGRAPH_PROPERTY
    variable = make_variable_font(tmp_path)
    resolver = FontResolver(installed_dirs=[tmp_path])
    catalog = resolver.catalog()
    entry = next(e for e in catalog if e.get('path') == str(variable))
    editor = PageEditor()
    qtbot.addWidget(editor)
    editor.load_payload(dict(page=0, ids=[], rect=(20,20,320,120),
        runs=[dict(text='office',font_name=entry['name'],font_file=str(variable),font_axes={'wght':100},size=12)]), catalog)
    editor.toolbar.typography_panel.show()
    assert editor.toolbar.axis_controls['wght'].minimum() == 100
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)
    editor.toolbar.axis_controls['wght'].setValue(650)
    assert editor.payload()['runs'][0]['font_axes'] == {'wght':650.}
    editor.toolbar.ligatures.setChecked(False)
    assert editor.payload()['runs'][0]['font_features']['liga'] == 0
    editor.merge_paragraph(direction='rtl')
    assert editor.payload()['paragraphs'][0]['direction'] == 'rtl'
    assert editor.textCursor().blockFormat().property(PARAGRAPH_PROPERTY)['direction'] == 'rtl'
    editor._original_carets = [dict(index=1,bbox=(20,20,50,40),cluster_start=1,cluster_end=4,rtl=False)]
    assert editor.place_caret_pdf((48,30))
    assert editor.textCursor().position() == 4
    editor.set_accepting(True)
    assert not editor.toolbar.typography_panel.isEnabled()
