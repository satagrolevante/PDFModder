"""Linked-text ownership, action policy and independent preservation proofs.

Fixtures are synthetic and keep an untouched control page. Policy unit tests
edit annotations directly; rich-editor tests exercise actual text composition.
"""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, NameObject
import pytest

from pdfmodder.engine import _safe_selection, extract_page
from pdfmodder.linked_text_v303 import prepare_linked_text
from pdfmodder.model import EditError, union
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload


EMAIL = 'alice+tag@example.org'
MAILTO = 'mailto:' + EMAIL
CONTROL_URI = 'https://example.net/unchanged?x=1'


def _model_and_selection(data, text=EMAIL, page=0):
    with fitz.open(stream=data, filetype='pdf') as document:
        model = extract_page(document, page, data)
    start = ''.join(g.text for g in model.glyphs).index(text)
    selected = model.glyphs[start:start + len(text)]
    assert ''.join(g.text for g in selected) == text
    return model, selected


def _reader(data):
    return PdfReader(BytesIO(data), strict=True)


def _annotation_refs(data):
    return [list(page.get('/Annots', [])) for page in _reader(data).pages]


def _owner_ref(data):
    return next(ref for ref in _annotation_refs(data)[0]
                if ref.get_object().get('/NM') == 'linked-owner')


def _control_link_ref(data):
    return next(ref for ref in _annotation_refs(data)[1]
                if ref.get_object().get('/Subtype') == '/Link')


def _control_note_ref(data):
    return next(ref for ref in _annotation_refs(data)[1]
                if ref.get_object().get('/Subtype') == '/Text')


def _document(label=EMAIL, uri=MAILTO, *, rotation=0, cropped=False,
              duplicate=False, non_uri=False, shared_action=False):
    with fitz.open() as document:
        page = document.new_page(width=500, height=320)
        page.insert_text((50, 75), label, fontsize=12, color=(0, 0, 1))
        page.insert_text((50, 165), 'UNLINKED NEIGHBOUR', fontsize=10)
        control = document.new_page(width=500, height=320)
        control.insert_text((50, 75), 'CONTROL LINK', fontsize=12)
        control.insert_text((50, 165), 'CONTROL TEXT', fontsize=10)
        page = document[0]
        if cropped:
            page.set_cropbox((20, 20, 480, 300))
        bounds = page.search_for(label)[0]
        link = dict(kind=fitz.LINK_URI, from_=bounds, uri=uri)
        link['from'] = link.pop('from_')
        if non_uri:
            link = dict(kind=fitz.LINK_GOTO, page=1, to=fitz.Point(50, 75))
            link['from'] = bounds
        page.insert_link(link)
        if duplicate:
            page.insert_link(dict(link, uri='https://example.org/other'))
        control = document[1]
        control.insert_link({'kind': fitz.LINK_URI,
                             'from': control.search_for('CONTROL LINK')[0],
                             'uri': CONTROL_URI})
        note = control.add_text_annot((350, 180), 'Original note contents')
        resource = document.get_new_xref()
        document.update_object(resource, '<< /PDFModderResourceType /Opaque >>')
        document.update_stream(resource, b'original dependent annotation resource')
        document.xref_set_key(note.xref, 'PDFModderPrivateData', f'{resource} 0 R')
        document.xref_set_key(note.xref, 'PDFModderPrivateLabel',
                              fitz.get_pdf_str('original custom annotation metadata'))
        document.set_metadata({'title': 'Synthetic linked-text transaction',
                               'author': 'PDFModder tests'})
        data = document.tobytes(garbage=0, no_new_id=True)
    with fitz.open(stream=data, filetype='pdf') as document:
        owner = document[0].get_links()[0]['xref']
        document.xref_set_key(owner, 'NM', fitz.get_pdf_str('linked-owner'))
        document.xref_set_key(owner, 'Contents', fitz.get_pdf_str('Original link contents'))
        document.xref_set_key(owner, 'PDFModderPrivateLabel', fitz.get_pdf_str('keep me'))
        info = _reader(data).trailer.raw_get('/Info').idnum
        document.xref_set_key(info, 'PDFModderPrivateInfo', fitz.get_pdf_str('original Info extension'))
        if shared_action:
            action = document.get_new_xref()
            document.update_object(action, document.xref_get_key(owner, 'A')[1])
            control = document[1].get_links()[0]['xref']
            for annotation in (owner, control):
                document.xref_set_key(annotation, 'A', f'{action} 0 R')
        # Insert links before rotation: cropped, rotated Page.insert_link has
        # different coordinate handling from the original visible glyphs.
        document[0].set_rotation(rotation)
        return document.tobytes(garbage=0, no_new_id=True)


def _mutate(data, callback):
    with fitz.open(stream=data, filetype='pdf') as document:
        callback(document)
        return document.tobytes(garbage=0, no_new_id=True)


def _prepare(data, replacement=EMAIL, *, text=EMAIL):
    model, selected = _model_and_selection(data, text)
    policy = prepare_linked_text(data, 0, model, selected, replacement)
    assert policy is not None
    return policy, model, selected


def _apply(data, policy, planned):
    policy.plan(planned)
    output = _mutate(data, policy.apply)
    policy.validate(output)
    return output


def _uri(data, ref):
    node = _reader(data).get_object(ref.idnum)
    return str(node['/A']['/URI'])


def _shift(glyph, dx, dy):
    return replace(glyph,
                   origin=(glyph.origin[0] + dx, glyph.origin[1] + dy),
                   bbox=tuple(value + (dx if i % 2 == 0 else dy)
                              for i, value in enumerate(glyph.bbox)),
                   trace_bbox=tuple(value + (dx if i % 2 == 0 else dy)
                                    for i, value in enumerate(glyph.trace_bbox)))


def _replacement_glyphs(selected, replacement):
    assert len(selected) == len(replacement)
    return [replace(glyph, text=char) for glyph, char in zip(selected, replacement)]


def _tagged(data):
    """Give the email an MCID and OBJR owned by the same /Link element."""
    with fitz.open(stream=data, filetype='pdf') as document:
        page, control = document[0], document[1]
        target = _owner_ref(data).idnum
        tree, parent_tree, root, link, neighbour, control_node = (
            document.get_new_xref() for _ in range(6))
        objects = {
            tree: f'<< /Type /StructTreeRoot /K [{root} 0 R] '
                  f'/ParentTree {parent_tree} 0 R /ParentTreeNextKey 3 >>',
            root: f'<< /Type /StructElem /S /Document /P {tree} 0 R '
                  f'/K [{link} 0 R {neighbour} 0 R {control_node} 0 R] >>',
            link: f'<< /Type /StructElem /S /Link /P {root} 0 R /Pg {page.xref} 0 R '
                  f'/K [0 << /Type /OBJR /Obj {target} 0 R /Pg {page.xref} 0 R >>] >>',
            neighbour: f'<< /Type /StructElem /S /P /P {root} 0 R /Pg {page.xref} 0 R /K 1 >>',
            control_node: f'<< /Type /StructElem /S /P /P {root} 0 R '
                          f'/Pg {control.xref} 0 R /K [0 1] >>',
            parent_tree: f'<< /Nums [0 [{link} 0 R {neighbour} 0 R] '
                         f'1 [{control_node} 0 R {control_node} 0 R] 2 {link} 0 R] >>',
        }
        for xref, value in objects.items():
            document.update_object(xref, value)
        for number in (0, 1):
            current = document[number]
            contents = current.get_contents()
            assert len(contents) == 2
            for mcid, xref in enumerate(contents):
                document.update_stream(xref, f'/P << /MCID {mcid} >> BDC\n'.encode()
                                       + document.xref_stream(xref) + b'\nEMC\n')
            document.xref_set_key(current.xref, 'StructParents', str(number))
        document.xref_set_key(target, 'StructParent', '2')
        document.xref_set_key(document.pdf_catalog(), 'StructTreeRoot', f'{tree} 0 R')
        document.xref_set_key(document.pdf_catalog(), 'MarkInfo', '<< /Marked true >>')
        document.xref_set_key(document.pdf_catalog(), 'Lang', '(en-US)')
        return document.tobytes(garbage=0, no_new_id=True)


def test_source_link_guard_requires_exact_owned_policy():
    data = _document()
    policy, model, selected = _prepare(data)
    policy.plan(selected)
    with fitz.open(stream=data, filetype='pdf') as document:
        with pytest.raises(EditError, match='enlace'):
            _safe_selection(document[0], model, selected)
        _safe_selection(document[0], model, selected, linked_text=policy)


def test_unlinked_selection_has_no_link_allowance():
    data = _document()
    model, selected = _model_and_selection(data, 'UNLINKED')
    assert prepare_linked_text(data, 0, model, selected, 'UNCHANGED') is None


@pytest.mark.parametrize('subset', [slice(0, 5), slice(1, None)])
def test_partial_link_selection_is_rejected(subset):
    data = _document()
    model, selected = _model_and_selection(data)
    with pytest.raises(EditError):
        prepare_linked_text(data, 0, model, selected[subset], 'other')


@pytest.mark.parametrize('kind', ['multiple', 'non_uri', 'quadpoints', 'appearance'])
def test_ambiguous_or_unsupported_link_geometry_is_rejected(kind):
    data = _document(duplicate=kind == 'multiple', non_uri=kind == 'non_uri')
    owner = _owner_ref(data).idnum
    if kind == 'quadpoints':
        rect = _owner_ref(data).get_object()['/Rect']
        x0, y0, x1, y1 = (float(value) for value in rect)
        data = _mutate(data, lambda doc: doc.xref_set_key(owner, 'QuadPoints',
            f'[{x0} {y1} {x1} {y1} {x0} {y0} {x1} {y0}]'))
    elif kind == 'appearance':
        def appearance(document):
            stream = document.get_new_xref()
            document.update_object(stream, '<< /Type /XObject /Subtype /Form '
                                   '/BBox [0 0 100 20] /Resources <<>> >>')
            document.update_stream(stream, b'q Q')
            document.xref_set_key(owner, 'AP', f'<< /N {stream} 0 R >>')
        data = _mutate(data, appearance)
    model, selected = _model_and_selection(data)
    with pytest.raises(EditError):
        prepare_linked_text(data, 0, model, selected, 'bob@example.org')


def test_percent_encoded_recipient_preserves_plus_and_literal_query_bytes():
    query = '?subject=A%20B&body=a+b&subject=again&flag=&cc=copy%40else.org'
    data = _document(uri='mailto:alice%2Btag%40example.org' + query)
    replacement = 'alice+tag@example.net'
    policy, _, selected = _prepare(data, replacement)
    output = _apply(data, policy, _replacement_glyphs(selected, replacement))
    assert _uri(output, _owner_ref(data)) == 'mailto:alice%2Btag@example.net' + query
    assert policy.report()['destination_policy']
    assert policy.report()['reason']


def test_generic_display_label_preserves_uri_with_explicit_reason():
    data = _document(label='Contact us')
    policy, _, selected = _prepare(data, 'Contact me', text='Contact us')
    output = _apply(data, policy, _replacement_glyphs(selected, 'Contact me'))
    assert _uri(output, _owner_ref(data)) == MAILTO
    report = policy.report()
    assert report['reason'] and report['destination_policy']
    assert not report['active_area_disabled']


def test_shared_indirect_action_is_cloned_for_owned_link_only():
    data = _document(shared_action=True)
    old_ref = _owner_ref(data).get_object().raw_get('/A')
    assert old_ref.idnum == _control_link_ref(data).get_object().raw_get('/A').idnum
    original_action = bytes(old_ref.get_object()['/URI'].original_bytes)
    policy, _, selected = _prepare(data, 'alice+tag@example.net')
    output = _apply(data, policy, _replacement_glyphs(selected, 'alice+tag@example.net'))
    reader = _reader(output)
    assert str(reader.get_object(old_ref.idnum)['/URI']) == MAILTO
    assert bytes(reader.get_object(old_ref.idnum)['/URI'].original_bytes) == original_action
    assert _uri(output, _control_link_ref(data)) == MAILTO
    assert _uri(output, _owner_ref(data)) == 'mailto:alice%2Btag@example.net'
    assert _control_link_ref(output).get_object().raw_get('/A').idnum == old_ref.idnum


@pytest.mark.parametrize('tamper', ['unrelated_uri', 'contents', 'custom_metadata',
                                    'resource_stream', 'private_info'])
def test_annotation_validation_detects_nonvisual_unowned_changes(tamper):
    data = _document()
    policy, _, selected = _prepare(data)
    output = _apply(data, policy, selected)
    note = _control_note_ref(output)
    if tamper == 'unrelated_uri':
        target = _control_link_ref(output).idnum
        def change(document):
            document.xref_set_key(target, 'A/URI', fitz.get_pdf_str('https://tampered.invalid/'))
    elif tamper == 'contents':
        def change(document):
            document.xref_set_key(note.idnum, 'Contents', fitz.get_pdf_str('changed note contents'))
    elif tamper == 'custom_metadata':
        def change(document):
            document.xref_set_key(note.idnum, 'PDFModderPrivateLabel', fitz.get_pdf_str('changed custom metadata'))
    elif tamper == 'resource_stream':
        stream = note.get_object().raw_get('/PDFModderPrivateData').idnum
        def change(document):
            document.update_stream(stream, document.xref_stream(stream) + b'\x00')
    else:
        info = _reader(output).trailer.raw_get('/Info').idnum
        def change(document):
            document.xref_set_key(info, 'PDFModderPrivateInfo', fitz.get_pdf_str('changed Info extension'))
    with pytest.raises(EditError):
        policy.validate(_mutate(output, change))


@pytest.mark.parametrize('tamper', ['filter', 'decode_parameters'])
def test_opaque_annotation_image_codec_changes_are_not_compression_allowances(tamper):
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (2, 2), (40, 110, 200)).save(image, format='JPEG')
    payload = image.getvalue()
    data = _document()
    note = _control_note_ref(data)
    resource = note.get_object().raw_get('/PDFModderPrivateData').idnum

    def install_image(document):
        document.update_object(resource,
            '<< /Type /XObject /Subtype /Image /Width 2 /Height 2 '
            '/BitsPerComponent 8 /ColorSpace /DeviceRGB >>')
        document.update_stream(resource, payload, compress=False)
        document.xref_set_key(resource, 'Filter', '/DCTDecode')
        document.xref_set_key(resource, 'DecodeParms', '<< /ColorTransform 1 >>')

    data = _mutate(data, install_image)
    policy, _, selected = _prepare(data)
    output = _apply(data, policy, selected)
    original_image = _control_note_ref(output).get_object()['/PDFModderPrivateData']

    def change_codec(document):
        if tamper == 'filter':
            document.xref_set_key(resource, 'Filter', '/JPXDecode')
        else:
            document.xref_set_key(resource, 'DecodeParms', '<< /ColorTransform 0 >>')

    altered = _mutate(output, change_codec)
    changed_image = _control_note_ref(altered).get_object()['/PDFModderPrivateData']
    assert original_image.get_data() == changed_image.get_data() == payload
    with pytest.raises(EditError):
        policy.validate(altered)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_cropped_rotated_link_rect_maps_exact_planned_glyph_bounds(rotation):
    data = _document(rotation=rotation, cropped=True)
    policy, _, selected = _prepare(data)
    planned = [_shift(glyph, 8, 11) for glyph in selected]
    bounds = union(glyph.bbox for glyph in planned)
    with fitz.open(stream=data, filetype='pdf') as document:
        document[0].set_rotation(0)
        expected_raw = fitz.Rect(bounds) * ~document[0].transformation_matrix
    output = _apply(data, policy, planned)
    assert tuple(float(value) for value in _owner_ref(output).get_object()['/Rect']) == pytest.approx(
        tuple(expected_raw), abs=.001)
    with fitz.open(stream=output, filetype='pdf') as document:
        owner = next(link for link in document[0].get_links()
                     if link['xref'] == _owner_ref(data).idnum)
        normalized = fitz.Rect(owner['from']) * document[0].derotation_matrix
        assert tuple(normalized) == pytest.approx(bounds, abs=.001)


@pytest.mark.parametrize('tagged', [False, True])
def test_empty_label_disables_active_rect_and_retains_uri_and_annotation(tagged):
    from pdfmodder.tagged import analyze_readonly
    data = _document()
    if tagged:
        data = _tagged(data)
    policy, _, _ = _prepare(data, '')
    output = _apply(data, policy, [])
    before, after = _owner_ref(data), _owner_ref(output)
    assert (after.idnum, after.generation) == (before.idnum, before.generation)
    assert _uri(output, before) == MAILTO
    assert list(after.get_object()['/Rect']) == [0, 0, 0, 0]
    assert len(_annotation_refs(output)[0]) == len(_annotation_refs(data)[0])
    report = policy.report()
    assert report['active_area_disabled'] and report['warnings']
    expected = next(link for link in policy.expected_links if link['xref'] == before.idnum)
    assert expected['kind'] == fitz.LINK_URI and expected['uri'] == MAILTO
    assert fitz.Rect(expected['from']).is_empty
    if tagged:
        assert analyze_readonly(output).semantic() == analyze_readonly(data).semantic()
        assert after.get_object()['/StructParent'] == before.get_object()['/StructParent']


@pytest.mark.parametrize('tagged', [False, True])
@pytest.mark.parametrize('replacement', [EMAIL, 'bob@example.org'])
def test_rich_editor_changes_text_and_owned_link_once_preserving_control_page(tagged, replacement):
    from pdfmodder.clipping import _signature
    from pdfmodder.linked_text_v303 import _annotation_snapshot
    from pdfmodder.native_panel import _replace_runs
    from pdfmodder.tagged import analyze_readonly
    data = _document()
    if tagged:
        data = _tagged(data)
        assert analyze_readonly(data) is not None
    model, selected = _model_and_selection(data)
    payload = selection_payload(data, 0, [glyph.id for glyph in selected])
    runs = payload['runs'] if replacement == EMAIL else _replace_runs(payload['runs'], replacement)
    request = RichTextRequest(0, payload['ids'],
                              runs,
                              rect=payload['rect'], revision=payload['revision'],
                              auto_width=True)
    output, report = edit_rich_pdf(data, request)
    assert report['verified']
    original, current = _reader(data), _reader(output)
    owner, result = _owner_ref(data), _owner_ref(output)
    assert result.get_object()['/NM'] == owner.get_object()['/NM'] == 'linked-owner'
    assert [len(refs) for refs in _annotation_refs(output)] == [len(refs) for refs in _annotation_refs(data)]
    annotation_position = lambda reader, ref: next(
        (number, index) for number, page in enumerate(reader.pages)
        for index, candidate in enumerate(page.get('/Annots', []))
        if (candidate.idnum, candidate.generation) == (ref.idnum, ref.generation))
    assert annotation_position(current, result) == annotation_position(original, owner)
    assert str(result.get_object()['/A']['/URI']) == 'mailto:' + replacement
    assert result.get_object()['/Contents'] == owner.get_object()['/Contents']
    assert result.get_object()['/PDFModderPrivateLabel'] == 'keep me'
    assert _uri(output, _control_link_ref(output)) == CONTROL_URI
    original_fonts = original.pages[0]['/Resources']['/Font']
    current_fonts = current.pages[0]['/Resources']['/Font']
    assert set(original_fonts) <= set(current_fonts)
    for name, font in original_fonts.items():
        assert _signature(font) == _signature(current_fonts[name])
    # Full writes may renumber xrefs. Allow only the owned annotation's raw
    # rectangle and URI, then compare every annotation key, alias, dependent
    # resource stream, annotation order and metadata property semantically.
    expected_owner = original.get_object(owner.idnum)
    actual_owner = current.get_object(result.idnum)
    expected_owner[NameObject('/Rect')] = deepcopy(actual_owner['/Rect'])
    if actual_owner['/A']['/URI'] != expected_owner['/A']['/URI']:
        expected_action = DictionaryObject(dict(expected_owner['/A']))
        expected_action[NameObject('/URI')] = deepcopy(actual_owner['/A']['/URI'])
        expected_owner[NameObject('/A')] = expected_action
    assert _annotation_snapshot(original) == _annotation_snapshot(current)
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        assert after[0].get_text().count(replacement) == 1
        if replacement != EMAIL:
            assert EMAIL not in after[0].get_text()
        assert 'UNLINKED NEIGHBOUR' in after[0].get_text()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[1].get_text() == after[1].get_text()
        assert before.metadata == after.metadata
        bounds = union(glyph.bbox for glyph in _model_and_selection(output, replacement)[1])
        link = next(link for link in after[0].get_links() if link['xref'] == result.idnum)
        assert tuple(link['from']) == pytest.approx(bounds, abs=.035)
    if tagged:
        old_structure, new_structure = analyze_readonly(data), analyze_readonly(output)
        assert new_structure.semantic() == old_structure.semantic()
        normalize_owners = lambda structure: [
            (structure.annotations[target], structure.node_refs[parent])
            for target, parent in structure.object_owners]
        assert normalize_owners(new_structure) == normalize_owners(old_structure)
        assert result.get_object()['/StructParent'] == owner.get_object()['/StructParent']


@pytest.mark.parametrize('include_leading,include_trailing',
                         [(False, False), (True, False), (False, True), (True, True)])
def test_exporter_hotspot_padding_does_not_prevent_complete_email_ownership(include_leading, include_trailing):
    from pdfmodder.native_panel import _replace_runs
    label = ' ' + EMAIL + ' '
    data = _document(label=label)
    model, entire_label = _model_and_selection(data, label)
    assert entire_label[0].text == entire_label[-1].text == ' '
    with fitz.open(stream=data, filetype='pdf') as document:
        area = document[0].get_links()[0]['from']
        for glyph in entire_label:
            center = fitz.Point((glyph.bbox[0] + glyph.bbox[2]) / 2,
                                (glyph.bbox[1] + glyph.bbox[3]) / 2)
            assert area.contains(center)
    selected = entire_label[0 if include_leading else 1:None if include_trailing else -1]
    replacement = (' ' if include_leading else '') + 'bob@example.org' + (' ' if include_trailing else '')
    payload = selection_payload(data, 0, [glyph.id for glyph in selected])
    request = RichTextRequest(0, payload['ids'],
                              _replace_runs(payload['runs'], replacement),
                              rect=payload['rect'], revision=payload['revision'],
                              auto_width=True)
    output, report = edit_rich_pdf(data, request)
    assert report['verified']
    assert _uri(output, _owner_ref(output)) == 'mailto:bob@example.org'
    assert report['linked_text']['destination_policy'] == 'updated_mailto'
    updated, new_email = _model_and_selection(output, 'bob@example.org')
    assert len(new_email) == len('bob@example.org')
    with fitz.open(stream=output, filetype='pdf') as document:
        text = document[0].get_text()
        assert text.count('bob@example.org') == 1 and EMAIL not in text
    # Unselected padding remains real whitespace at its original origin,
    # including the distant old trailing space after a shorter replacement.
    selected_ids = {glyph.id for glyph in selected}
    for old_space in (entire_label[0], entire_label[-1]):
        if old_space.id in selected_ids:
            continue
        matches = [glyph for glyph in updated.glyphs
                   if glyph.text == old_space.text
                   and all(abs(a - b) < .035 for a, b in zip(glyph.origin, old_space.origin))]
        assert len(matches) == 1
        assert matches[0].font == old_space.font
        assert matches[0].size == pytest.approx(old_space.size, abs=.001)
