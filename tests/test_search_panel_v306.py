from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QStyleOptionViewItem, QWidget
import pytest

from pdfmodder.search_panel_v306 import SearchPanel


def matches():
    return [
        {'page': 0, 'rect': [10, 10, 20, 20], 'text': 'correo',
         'context': 'Un correo de contacto.', 'context_start': 3, 'context_end': 9},
        {'page': 7, 'rect': [20, 10, 40, 20], 'text': 'correo',
         'context': 'Otro correo de contacto.', 'context_start': 5, 'context_end': 11},
    ]


@pytest.fixture
def panel(qtbot):
    widget = SearchPanel()
    qtbot.addWidget(widget)
    widget.resize(420, 500)
    widget.show()
    return widget


def test_counter_empty_and_programmatic_selection_do_not_jump(panel, qtbot):
    activated = []
    panel.match_requested.connect(activated.append)
    assert panel.count_label.text() == 'Sin resultados'
    assert not panel.previous_button.isEnabled() and not panel.next_button.isEnabled()
    panel.set_matches(matches())
    assert panel.count_label.text() == '2 resultados'
    assert panel.results_view.currentIndex().row() == -1
    panel.set_current_index(1)
    assert panel.count_label.text() == 'Resultado 2 de 2'
    assert panel.results_view.currentIndex().row() == 1
    assert not activated
    panel.set_matches([])
    assert panel.count_label.text() == 'Sin resultados'
    assert not panel.next_button.isEnabled()


def test_single_click_phrase_and_enter_activate_its_exact_index(panel, qtbot):
    panel.set_matches(matches())
    activated = []
    panel.match_requested.connect(activated.append)
    index = panel.model.index(1)
    qtbot.mouseClick(panel.results_view.viewport(), Qt.LeftButton,
                     pos=panel.results_view.visualRect(index).center())
    assert activated == [1]
    assert panel.count_label.text() == 'Resultado 2 de 2'
    panel.results_view.setFocus()
    qtbot.keyClick(panel.results_view, Qt.Key_Return)
    assert activated == [1, 1]


def test_arrows_emit_navigation_and_remain_disabled_while_busy(panel, qtbot):
    previous, following = [], []
    panel.previous_requested.connect(lambda: previous.append(True))
    panel.next_requested.connect(lambda: following.append(True))
    panel.set_matches(matches(), current_index=0)
    qtbot.mouseClick(panel.next_button, Qt.LeftButton)
    qtbot.mouseClick(panel.previous_button, Qt.LeftButton)
    assert previous == [True] and following == [True]
    panel.set_busy(True)
    assert not panel.results_view.isEnabled()
    assert not panel.previous_button.isEnabled() and not panel.next_button.isEnabled()
    assert panel.message.text() == 'Buscando…'
    panel.set_busy(False)
    assert panel.previous_button.isEnabled() and panel.next_button.isEnabled()


def test_enter_button_and_changed_criteria_submit_latest_query_even_while_busy(panel, qtbot):
    requests, changes = [], []
    panel.find_requested.connect(lambda *args: requests.append(args))
    panel.criteria_changed.connect(lambda: changes.append(True))
    panel.set_query('Primera')
    panel.query.setFocus()
    qtbot.keyClick(panel.query, Qt.Key_Return)
    assert requests == [('Primera', False, False)]
    panel.set_busy(True)
    assert panel.query.isEnabled()
    panel.set_query('Última & (final)')
    panel.case_box.setChecked(True)
    panel.whole_box.setChecked(True)
    qtbot.mouseClick(panel.find_button, Qt.LeftButton)
    assert requests[-1] == ('Última & (final)', True, True)
    assert panel.options() == {'case_sensitive': True, 'whole_word': True}
    assert len(changes) == 4
    panel.set_query(' ')
    assert not panel.find_button.isEnabled()
    qtbot.keyClick(panel.query, Qt.Key_Return)
    assert len(requests) == 2


def test_context_is_plain_text_and_highlight_uses_unicode_character_offsets(panel):
    context = '🌾 <b>correo</b> & contacto'
    start = context.index('correo')
    panel.set_matches([{'page': 2, 'context': context, 'text': 'correo',
                        'context_start': start, 'context_end': start + 6}], 0)
    option = QStyleOptionViewItem()
    option.initFrom(panel.results_view)
    document = panel.results_view.itemDelegate().document(option, panel.model.index(0))
    assert document.toPlainText() == 'Página 3\n' + context
    assert context in panel.model.data(panel.model.index(0), Qt.AccessibleTextRole)
    first = len(('Página 3\n' + context[:start]).encode('utf-16-le')) // 2
    cursor = QTextCursor(document)
    cursor.setPosition(first)
    cursor.setPosition(first + 6, QTextCursor.KeepAnchor)
    assert cursor.selectedText() == 'correo'
    assert cursor.charFormat().background().color().name() == '#ffe69a'
    assert '<b>' in document.toPlainText()


def test_large_result_set_keeps_a_model_and_reveals_selected_row_without_row_widgets(panel):
    rows = [dict(matches()[0], page=index // 10) for index in range(10000)]
    panel.set_matches(rows, 9999)
    assert panel.model.rowCount() == 10000
    assert panel.count_label.text() == 'Resultado 10000 de 10000'
    assert panel.results_view.currentIndex().row() == 9999
    assert not panel.results_view.indexWidget(panel.model.index(9999))
    panel.clear_results('Los criterios cambiaron. Pulsa Buscar.')
    assert panel.model.rowCount() == 0
    assert panel.message.text() == 'Los criterios cambiaron. Pulsa Buscar.'
