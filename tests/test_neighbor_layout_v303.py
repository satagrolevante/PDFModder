"""Preparing redistribution preserves real source text and stays outside history."""
from copy import deepcopy
from dataclasses import asdict, fields, replace
from hashlib import sha256

import pymupdf as fitz
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError, union
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.selection_v300 import contains, selection_index


def _document(*, cell=False, incomplete_cell=False,
              suffix=' bold neighbors', continuation='stay together.'):
    with fitz.open() as document:
        page = document.new_page(width=400, height=260)
        x = 30.
        for text, font, color in (
            ('Before ', 'helv', (0., 0., 0.)),
            ('tiny', 'helv', (0., 0., 0.)),
            (suffix, 'hebo', (.1, .2, .7)),
        ):
            page.insert_text((x, 55), text, fontname=font, fontsize=11, color=color)
            x += fitz.Font(fontname=font).text_length(text, fontsize=11)
        page.insert_text((30, 71), continuation, fontname='heit',
                         fontsize=11, color=(.1, .5, .2))
        if cell:
            page.insert_text((30, 110), 'Another cell paragraph', fontsize=10)
        page.insert_text((30, 175), 'OUTSIDE PARAGRAPH', fontsize=10)
        if cell:
            page.draw_rect((20, 25, 250, 125), color=(0., 0., 0.))
        elif incomplete_cell:
            page.draw_line((20, 25), (250, 25))
            page.draw_line((20, 125), (250, 125))
            page.draw_line((20, 25), (20, 125))
        control = document.new_page(width=400, height=260)
        control.insert_text((30, 55), 'CONTROL PAGE', fontsize=13)
        control.draw_rect((25, 85, 225, 125), color=(.4, .1, .5))
        document.set_metadata({'title': 'Neighbor preservation', 'author': 'Test fixture'})
        data = document.tobytes()
        model = extract_page(document, 0, data)
    return data, model


def _ids(model, text):
    source = ''.join(glyph.text for glyph in model.glyphs)
    begin = source.index(text)
    return [glyph.id for glyph in model.glyphs[begin:begin+len(text)]]


def _draft(data, model, text='longer replacement with fresh words'):
    ids = _ids(model, 'tiny')
    payload = selection_payload(data, 0, ids, page_model=model)
    return RichTextRequest(
        0, ids, [dict(payload['runs'][0], text=text)],
        rect=(30., payload['rect'][1], 220., 125.),
        revision=sha256(data).hexdigest(), auto_width=True, auto_height=True,
    )


def _prepare(data, request, scope='paragraph', *, model=None):
    from pdfmodder.neighbor_layout_v303 import prepare_neighbor_draft
    return prepare_neighbor_draft(data, request, scope, page_model=model)


def _request(payload):
    names = {field.name for field in fields(RichTextRequest)}
    return RichTextRequest(**{key: value for key, value in payload.items() if key in names})


def _styled_characters(runs):
    return [(character, {key: value for key, value in run.items() if key != 'text'})
            for run in runs for character in run['text']]


def _source_payload(data, model):
    index = selection_index(model)
    chosen = model.selected(_ids(model, 'tiny'))
    ids = index.scope(chosen[0], 'paragraph').ids
    assert set(_ids(model, 'stay together.')) <= set(ids)
    assert not set(_ids(model, 'OUTSIDE PARAGRAPH')) & set(ids)
    return selection_payload(data, 0, ids, page_model=model)


def test_paragraph_splice_preserves_source_styles_and_the_current_draft():
    data, model = _document()
    request = _draft(data, model)
    request.runs = [dict(request.runs[0], text='fresh ', size=13, color=(.8, .1, .1),
                         font_features={'kern': 0}),
                    dict(request.runs[0], text='words', underline=True, char_spacing=.2)]
    request.allow_overlap = True
    request.paragraphs = [{'index': 0, 'alignment': 'center', 'line_spacing': 18}]
    before = deepcopy(asdict(request))
    digest = sha256(data).hexdigest()
    source = _source_payload(data, model)
    payload = _prepare(data, request, model=model)
    styled = _styled_characters(payload['runs'])
    original = _styled_characters(source['runs'])
    assert payload['text'] == 'Before fresh words bold neighbors stay together.'
    assert styled[:7] == original[:7]
    assert styled[7:18] == _styled_characters(request.runs)
    # The original second row's visual break becomes a wrapping separator;
    # its style and all other suffix characters remain the source's properties.
    assert styled[18:] == [(' ' if c == '\u2028' else c, s) for c, s in original[11:]]
    assert payload['ids'] == source['ids']
    assert payload['carets'] == []
    assert payload['auto_width'] is False
    assert payload['auto_height'] is True
    assert payload['allow_overlap'] is True
    assert payload['neighbor_layout_info']['scope'] == 'paragraph'
    assert payload['neighbor_layout_info']['neighbor_count'] == len(source['ids'])-len(request.ids)
    assert payload['paragraphs'] == request.paragraphs
    assert asdict(request) == before
    assert sha256(data).hexdigest() == digest
    offset = 0
    for run in payload['runs']:
        if offset <= 7 < offset+len(run['text']):
            run['color'] = (1., 1., 1.)
            run['font_features']['kern'] = 1
            break
        offset += len(run['text'])
    payload['paragraphs'][0]['alignment'] = 'right'
    assert asdict(request) == before


def test_prepared_paragraph_reflows_once_and_preserves_outside_text_and_control_page():
    data, model = _document()
    request = _draft(data, model)
    selected = set(_source_payload(data, model)['ids'])
    untouched = [glyph for glyph in model.glyphs if glyph.id not in selected]
    payload = _prepare(data, request, model=model)
    output, report = edit_rich_pdf(data, _request(payload))
    assert report['verified']
    assert report['replacement'] == payload['text']
    assert report['line_count'] >= 2
    assert report['pages'][0]['pixels_above_8'] == 0
    assert {glyph['size'] for glyph in report['glyphs']} == {11.}
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        current = extract_page(after, 0, output)
        assert ''.join(glyph.text for glyph in current.glyphs).count(request.runs[0]['text']) == 1
        assert 'tiny' not in ''.join(glyph.text for glyph in current.glyphs)
        original_neighbors = model.selected(_ids(model, 'bold neighbors'))
        redistributed_neighbors = current.selected(_ids(current, 'bold neighbors'))
        assert any(original.origin != relocated.origin
                   for original, relocated in zip(original_neighbors, redistributed_neighbors))
        for original in untouched:
            assert any((glyph.text, glyph.origin, glyph.font, glyph.size, glyph.color) ==
                       (original.text, original.origin, original.font, original.size, original.color)
                       for glyph in current.glyphs)
        assert after[1].get_pixmap().samples == before[1].get_pixmap().samples
        assert after[1].get_text() == before[1].get_text()
        assert after.metadata == before.metadata
    # Reopening proves the inserted prefix and suffix still use their source faces/colors.
    actual = selection_payload(output, 0, _ids(current, payload['text']))
    styles = _styled_characters(actual['runs'])
    assert [character for character, _ in styles] == list(payload['text'])
    expected = _styled_characters(payload['runs'])
    for (_, source), (_, current_style) in zip(expected, styles):
        assert current_style['font_name'] == source['font_name']
        assert current_style['size'] == pytest.approx(source['size'], abs=.001)
        assert current_style['color'] == pytest.approx(source['color'], abs=.001)
    assert sha256(data).hexdigest() == request.revision


@pytest.mark.parametrize('side', ['before', 'after'])
def test_soft_wrap_with_adjacent_source_whitespace_does_not_add_an_extra_space(side):
    data, model = _document(
        suffix=' bold neighbors ' if side == 'before' else ' bold neighbors',
        continuation=' stay together.' if side == 'after' else 'stay together.',
    )
    request = _draft(data, model, 'fresh words')
    payload = _prepare(data, request, model=model)
    assert payload['text'] == 'Before fresh words bold neighbors stay together.'
    assert '\u2028' not in payload['text']


@pytest.mark.parametrize('replacement', ['', 'x'])
def test_deletion_and_shorter_replacement_keep_the_surrounding_source_text(replacement):
    data, model = _document()
    request = _draft(data, model, replacement)
    payload = _prepare(data, request, model=model)
    assert payload['text'] == f'Before {replacement} bold neighbors stay together.'
    assert payload['neighbor_layout_info']['neighbor_count'] == 36
    assert payload['ids'] == _source_payload(data, model)['ids']


@pytest.mark.parametrize('revision', [None, '', 'stale'])
def test_revision_is_required_and_must_match(revision):
    data, model = _document()
    request = replace(_draft(data, model), revision=revision)
    with pytest.raises(EditError):
        _prepare(data, request, model=model)


@pytest.mark.parametrize('case', ['duplicate', 'missing', 'disjoint'])
def test_selection_ids_must_be_unique_current_and_contiguous(case):
    data, model = _document()
    request = _draft(data, model)
    ids = {'duplicate': request.ids+[request.ids[0]],
           'missing': request.ids+[max(glyph.id for glyph in model.glyphs)+1],
           'disjoint': [request.ids[0], request.ids[2]]}[case]
    with pytest.raises(EditError):
        _prepare(data, replace(request, ids=ids), model=model)


def test_selection_cannot_escape_into_another_paragraph():
    data, model = _document()
    request = _draft(data, model)
    ids = [_source_payload(data, model)['ids'][-1]]+_ids(model, 'OUTSIDE PARAGRAPH')
    assert ids == list(range(ids[0], ids[-1]+1))
    with pytest.raises(EditError):
        _prepare(data, replace(request, ids=ids), model=model)


def test_paragraph_area_unites_the_full_scope_and_effective_draft_dimensions():
    data, model = _document()
    request = _draft(data, model)
    request = replace(request, rect=(30., 35., 35., 40.), width=205., height=90.)
    payload = _prepare(data, request, model=model)
    source_bounds = union(glyph.bbox for glyph in model.selected(payload['ids']))
    assert contains(payload['rect'], source_bounds, .001)
    assert contains(payload['rect'], (30., 35., 235., 125.), .001)
    assert tuple(payload['rect']) == pytest.approx((30., 35., 235., 125.), abs=.001)
    assert payload['width'] == pytest.approx(payload['rect'][2]-payload['rect'][0])
    assert payload['height'] == pytest.approx(payload['rect'][3]-payload['rect'][1])


@pytest.mark.parametrize('dimensions', [{'width': 500.}, {'height': 500.}])
def test_paragraph_area_cannot_expand_beyond_the_page(dimensions):
    data, model = _document()
    request = replace(_draft(data, model), **dimensions)
    with pytest.raises(EditError):
        _prepare(data, request, model=model)


def test_cell_uses_a_real_enclosure_and_disables_automatic_height_growth():
    data, model = _document(cell=True)
    request = _draft(data, model)
    payload = _prepare(data, request, 'cell', model=model)
    cell_ids = list(selection_index(model).scope(model.selected(request.ids)[0], 'cell').ids)
    assert payload['ids'] == cell_ids
    assert payload['text'] == ('Before longer replacement with fresh words bold neighbors '
                               'stay together.\nAnother cell paragraph')
    source = selection_payload(data, 0, cell_ids, page_model=model)
    source_breaks = [(char, style) for char, style in _styled_characters(source['runs'])
                     if char == '\u2028']
    assert len(source_breaks) == 2
    assert [(char, style) for char, style in _styled_characters(payload['runs'])
            if char == '\n'] == [('\n', source_breaks[-1][1])]
    assert payload['neighbor_layout_info']['neighbor_count'] == len(cell_ids)-len(request.ids)
    assert payload['neighbor_layout_info']['scope'] == 'cell'
    assert payload['auto_width'] is False
    assert payload['auto_height'] is False
    assert contains((20., 25., 250., 125.), payload['rect'], .001)
    assert contains(payload['rect'], union(glyph.bbox for glyph in model.selected(payload['ids'])), .001)
    assert not set(_ids(model, 'OUTSIDE PARAGRAPH')) & set(payload['ids'])


def test_cell_visual_rows_in_the_same_paragraph_remain_free_to_wrap():
    data, model = _document(cell=True)
    request = _draft(data, model, 'fresh words')
    index = selection_index(model)
    first = model.selected(_ids(model, 'Before'))[0]
    continuation = model.selected(_ids(model, 'stay together.'))[0]
    assert set(index.group(first, 'paragraph')) == set(index.group(continuation, 'paragraph'))
    payload = _prepare(data, request, 'cell', model=model)
    assert payload['text'].split('\n')[0] == 'Before fresh words bold neighbors stay together.'
    assert payload['text'].count('\n') == 1
    assert '\u2028' not in payload['text']


def test_actual_cell_edit_preserves_separate_neighbor_paragraphs_after_reopening():
    data, model = _document(cell=True)
    request = _draft(data, model, 'fresh words')
    payload = _prepare(data, request, 'cell', model=model)
    output, report = edit_rich_pdf(data, _request(payload))
    assert report['verified'] and report['pages'][0]['pixels_above_8'] == 0
    assert report['replacement'] == ('Before fresh words bold neighbors '
                                     'stay together.\nAnother cell paragraph')
    assert report['line_count'] >= 3
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        current = extract_page(after, 0, output)
        flat_text = payload['text'].replace('\n', '')
        current_ids = _ids(current, flat_text)
        reopened = selection_payload(output, 0, current_ids, page_model=current)
        assert reopened['text'] == payload['text']
        assert len(current_ids) == len(payload['text'])-1
        assert set(_ids(current, 'Another cell paragraph')) <= set(current_ids)
        expected = _styled_characters(payload['runs'])
        actual = _styled_characters(reopened['runs'])
        assert [char for char, _ in actual] == [char for char, _ in expected]
        for (_, source_style), (_, current_style) in zip(expected, actual):
            assert current_style['font_name'] == source_style['font_name']
            assert current_style['size'] == pytest.approx(source_style['size'], abs=.001)
            assert current_style['color'] == pytest.approx(source_style['color'], abs=.001)
        drawings_before = [{key: value for key, value in drawing.items() if key != 'seqno'}
                           for drawing in before[0].get_drawings()]
        drawings_after = [{key: value for key, value in drawing.items() if key != 'seqno'}
                          for drawing in after[0].get_drawings()]
        assert drawings_before == drawings_after
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
    assert sha256(data).hexdigest() == request.revision


def test_explicit_area_keeps_distinct_unselected_neighbor_paragraphs_separate():
    data, model = _document(cell=True)
    request = _draft(data, model, 'fresh words')
    payload = _prepare(data, request, 'area', model=model)
    assert payload['text'] == 'Before fresh words bold neighbors stay together.\nAnother cell paragraph'
    assert payload['ids'] == list(selection_index(model).scope(model.selected(request.ids)[0], 'cell').ids)


def test_overlapping_neighbor_paragraph_scopes_reject_an_ambiguous_boundary(monkeypatch):
    data, model = _document(cell=True)
    request = _draft(data, model, 'fresh words')
    index = selection_index(model)
    previous = model.selected(_ids(model, 'stay together.'))[-1]
    following = model.selected(_ids(model, 'Another cell paragraph'))[0]
    original_group = index.group

    def ambiguous_group(glyph, scope):
        ids = original_group(glyph, scope)
        if scope == 'paragraph' and glyph.id == previous.id:
            return ids+[following.id]
        return ids

    monkeypatch.setattr(index, 'group', ambiguous_group)
    with pytest.raises(EditError, match='ambiguo'):
        _prepare(data, request, 'cell', model=model)


def test_paragraph_preserves_explicit_fixed_height():
    data, model = _document()
    request = replace(_draft(data, model), auto_height=False)
    payload = _prepare(data, request, model=model)
    assert payload['auto_height'] is False


def test_cell_fallback_to_a_suggested_paragraph_is_rejected():
    data, model = _document(incomplete_cell=True)
    request = _draft(data, model)
    assert selection_index(model).cell_rect(model.selected(request.ids)[0]) is None
    with pytest.raises(EditError):
        _prepare(data, request, 'cell', model=model)


def test_cell_cannot_accept_draft_dimensions_outside_its_enclosure():
    data, model = _document(cell=True)
    request = replace(_draft(data, model), width=240.)
    with pytest.raises(EditError):
        _prepare(data, request, 'cell', model=model)


def test_area_redistribution_keeps_original_ids_inside_the_explicit_area():
    data, model = _document()
    request = _draft(data, model)
    payload = _prepare(data, request, 'area', model=model)
    assert set(request.ids) <= set(payload['ids'])
    assert payload['neighbor_layout_info']['scope'] == 'area'
    assert payload['text'] == 'Before longer replacement with fresh words bold neighbors stay together.'
    with pytest.raises(EditError):
        _prepare(data, replace(request, rect=(30., 35., 60., 75.)), 'area', model=model)


@pytest.mark.parametrize('mapping', ['missing', 'duplicate', 'wrong_index'])
def test_incomplete_or_ambiguous_source_carets_cannot_splice_text(monkeypatch, mapping):
    import pdfmodder.neighbor_layout_v303 as neighbor_layout
    import pdfmodder.richtext as richtext
    data, model = _document()
    request = _draft(data, model)
    original = richtext.selection_payload

    def broken_payload(*args, **kwargs):
        payload = deepcopy(original(*args, **kwargs))
        mapped = [caret for caret in payload['carets'] if 'id' in caret]
        if mapping == 'missing':
            payload['carets'].remove(mapped[0])
        elif mapping == 'duplicate':
            mapped[1]['id'] = mapped[0]['id']
        else:
            mapped[0]['index'] += 1
        return payload

    monkeypatch.setattr(richtext, 'selection_payload', broken_payload)
    monkeypatch.setattr(neighbor_layout, 'selection_payload', broken_payload, raising=False)
    with pytest.raises(EditError):
        _prepare(data, request, model=model)
    assert sha256(data).hexdigest() == request.revision


def test_hard_paragraph_breaks_survive_neighbor_redistribution():
    data, model = _document()
    source = _source_payload(data, model)
    runs = [dict(run, text=run['text'].replace('\u2028', '\n')) for run in source['runs']]
    seeded, _ = edit_rich_pdf(data, RichTextRequest(
        0, source['ids'], runs, rect=(30., source['rect'][1], 220., 125.),
        revision=source['revision'], paragraphs=[{'index': 0, 'line_spacing': 16},
                                                {'index': 1, 'line_spacing': 17}],
    ))
    with fitz.open(stream=seeded, filetype='pdf') as document:
        seeded_model = extract_page(document, 0, seeded)
    request = _draft(seeded, seeded_model, 'fresh words')
    payload = _prepare(seeded, request, model=seeded_model)
    assert payload['text'] == 'Before fresh words bold neighbors\nstay together.'
    assert '\u2028' not in payload['text']
    assert any(paragraph.get('index') == 1 and paragraph.get('line_spacing') == 17
               for paragraph in payload['paragraphs'])
