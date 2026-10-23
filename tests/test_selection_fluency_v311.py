"""Selection work is reused without altering text order or selected IDs."""
from pdfmodder.reading_order_v180 import ordered_glyphs, ordered_lines, selection_text
from test_continuous_reader_v180 import model, reader, png, position
from test_reading_canvas_v171 import make_canvas


def test_reading_order_is_built_once_per_snapshot_and_invalidated(monkeypatch):
    import pdfmodder.reading_order_v180 as reading
    page, _ = model(0)
    builds = []
    original = reading._build_ordered_lines_v311
    monkeypatch.setattr(reading, '_build_ordered_lines_v311', lambda value: builds.append(value.revision) or original(value))
    expected = selection_text(page)
    for _ in range(100):
        assert ordered_lines(page)
        assert ordered_glyphs(page)
        assert selection_text(page) == expected
    assert builds == [None]
    page.revision = 'new-snapshot'
    assert selection_text(page) == expected
    assert builds == [None, 'new-snapshot']


def test_unchanged_endpoint_does_not_redraw_or_notify(qtbot, monkeypatch):
    view = reader(qtbot, 1)
    page, rows = model(0)
    view.set_page(0, png(), page, 1.)
    endpoint = {'page': 0, 'id': rows[0][0].id}
    view._anchor = view._focus = view._gesture_anchor = endpoint
    notifications, draws = [], []
    view.selection_changed.connect(notifications.append)
    monkeypatch.setattr(view, '_draw_selection', lambda: draws.append(1))
    point = position(view, 0, rows[0][0])
    for _ in range(100):
        view._extend_selection(point)
    assert draws == [] and notifications == []
    view._extend_selection(position(view, 0, rows[0][-1]))
    assert len(draws) == 1 and len(notifications) == 1
    assert view.selection_text() == 'Primer párrafo'


def test_canvas_coalesces_drag_notifications_and_flushes_exact_final_selection(qtbot):
    canvas, rows = make_canvas(qtbot, reading=True)
    seen = []
    canvas.selection_changed.connect(lambda ids: seen.append(ids[:]))
    canvas._reading_dragging = True
    for length in range(1, len(rows['top'])+1):
        canvas.set_selection([g.id for g in rows['top'][:length]])
    assert seen == []
    assert canvas.ids == sorted(g.id for g in rows['top'])
    canvas._flush_selection_v311()
    assert seen == [canvas.ids]
    assert canvas.reading_text() == 'UNO DOS'
    assert len(canvas.overlays) < len(canvas.ids)
    for _ in range(100):
        canvas.set_selection(canvas.ids)
    assert len(seen) == 1


def test_reading_change_marks_follow_toggle_without_changing_pdf_or_selection(qtbot):
    view = reader(qtbot, 1)
    page, rows = model(0)
    image = png()
    view.set_page(0, image, page, 1., changes=[rows[0][0].bbox])
    assert view._change_overlays_v311 == []
    original = view._images[0][0].toImage()
    view.highlight_changes_v311 = True
    view._draw_changes_v311()
    assert len(view._change_overlays_v311) == 1
    assert view._images[0][0].toImage() == original
    assert view.selection_endpoints() is None
    view.highlight_changes_v311 = False
    view._draw_changes_v311()
    assert view._change_overlays_v311 == []
