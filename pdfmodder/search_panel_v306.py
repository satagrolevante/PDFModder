"""A lightweight, non-modal search list; document work stays in the PDF worker."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListView,
    QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolButton,
    QVBoxLayout, QWidget,
)


class SearchResultsModel(QAbstractListModel):
    """Keep one list of worker values, without allocating a widget per result."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.matches = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.matches)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.matches):
            return None
        match = self.matches[index.row()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.AccessibleTextRole):
            return f"Página {match['page'] + 1} · {self.context(match)}"
        if role == Qt.UserRole:
            return index.row()
        return None

    @staticmethod
    def context(match):
        return str(match.get('context') or match.get('text') or 'Coincidencia')

    def set_matches(self, matches):
        self.beginResetModel()
        self.matches = list(matches or [])
        self.endResetModel()


class SearchResultDelegate(QStyledItemDelegate):
    """Render plain text with a marked fragment, using only visible list rows."""

    def sizeHint(self, option, index):
        return QSize(220, QFontMetrics(option.font).lineSpacing() * 4 + 14)

    def document(self, option, index):
        match = index.model().matches[index.row()]
        context = index.model().context(match)
        heading = f"Página {match['page'] + 1}\n"
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(option.font)
        # Context may contain HTML characters or source XML. Never interpret it.
        document.setPlainText(heading + context)
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.Document)
        base = QTextCharFormat()
        selected = bool(option.state & QStyle.State_Selected)
        base.setForeground(option.palette.highlightedText() if selected else option.palette.text())
        cursor.setCharFormat(base)
        cursor.setPosition(0)
        cursor.setPosition(len(heading) - 1, QTextCursor.KeepAnchor)
        label = QTextCharFormat()
        label.setFontWeight(QFont.DemiBold)
        cursor.mergeCharFormat(label)
        try:
            start = int(match['context_start'])
            end = int(match['context_end'])
        except (KeyError, TypeError, ValueError):
            start, end = 0, 0
        if 0 <= start < end <= len(context):
            # Worker offsets count Python characters; Qt cursor positions are
            # UTF-16 units. Emoji before the match must not shift its highlight.
            first = len((heading + context[:start]).encode('utf-16-le')) // 2
            last = len((heading + context[:end]).encode('utf-16-le')) // 2
            cursor.setPosition(first)
            cursor.setPosition(last, QTextCursor.KeepAnchor)
            marker = QTextCharFormat()
            marker.setBackground(QColor('#ffe69a'))
            marker.setForeground(QColor('#201b00'))
            marker.setFontWeight(QFont.Bold)
            cursor.mergeCharFormat(marker)
        return document

    def paint(self, painter, option, index):
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ''
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, background, painter, option.widget)
        area = option.rect.adjusted(10, 5, -10, -5)
        if area.width() <= 0 or area.height() <= 0:
            return
        document = self.document(option, index)
        document.setTextWidth(area.width())
        painter.save()
        painter.setClipRect(area)
        painter.translate(area.topLeft())
        document.drawContents(painter, QRectF(0, 0, area.width(), area.height()))
        painter.restore()


class SearchPanel(QWidget):
    find_requested = Signal(str, bool, bool)
    criteria_changed = Signal()
    match_requested = Signal(int)
    next_requested = Signal()
    previous_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('searchResultsPanel')
        self._busy = False
        self._current_index = -1
        self._message = 'Escribe un texto y pulsa Enter o Buscar.'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setObjectName('searchPanelQuery')
        self.query.setPlaceholderText('Buscar en el documento…')
        self.query.setAccessibleName('Texto que buscar en el PDF')
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self._request_find)
        self.find_button = QPushButton('Buscar')
        self.find_button.setObjectName('searchPanelFind')
        self.find_button.clicked.connect(self._request_find)
        self.close_button = QToolButton()
        self.close_button.setObjectName('closeSearchPanel')
        self.close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_button.setToolTip('Cerrar la búsqueda')
        self.close_button.setAccessibleName('Cerrar la búsqueda')
        self.close_button.clicked.connect(self.close_requested)
        controls.addWidget(self.query, 1)
        controls.addWidget(self.find_button)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        options = QHBoxLayout()
        self.case_box = QCheckBox('Mayúsculas y minúsculas')
        self.case_box.setObjectName('searchCaseSensitive')
        self.case_box.setToolTip('Distinguir entre mayúsculas y minúsculas')
        self.whole_box = QCheckBox('Palabras completas')
        self.whole_box.setObjectName('searchWholeWords')
        options.addWidget(self.case_box)
        options.addWidget(self.whole_box)
        options.addStretch(1)
        layout.addLayout(options)
        navigation = QHBoxLayout()
        self.count_label = QLabel('Sin resultados')
        self.count_label.setObjectName('searchResultCount')
        self.count_label.setTextFormat(Qt.PlainText)
        self.count_label.setAccessibleName('Número de resultados de búsqueda')
        self.previous_button = QToolButton()
        self.previous_button.setObjectName('previousSearchResult')
        self.previous_button.setArrowType(Qt.LeftArrow)
        self.previous_button.setToolTip('Resultado anterior · Mayús+F3')
        self.previous_button.setAccessibleName('Resultado anterior')
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button = QToolButton()
        self.next_button.setObjectName('nextSearchResult')
        self.next_button.setArrowType(Qt.RightArrow)
        self.next_button.setToolTip('Resultado siguiente · F3')
        self.next_button.setAccessibleName('Resultado siguiente')
        self.next_button.clicked.connect(self.next_requested)
        navigation.addWidget(self.count_label, 1)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        layout.addLayout(navigation)
        self.results_view = QListView()
        self.results_view.setObjectName('searchResultsList')
        self.results_view.setAccessibleName('Frases con coincidencias; pulsa para ir al texto')
        self.model = SearchResultsModel(self)
        self.results_view.setModel(self.model)
        self.results_view.setItemDelegate(SearchResultDelegate(self.results_view))
        self.results_view.setUniformItemSizes(True)
        self.results_view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.results_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_view.setSelectionMode(QListView.SingleSelection)
        self.results_view.setEditTriggers(QListView.NoEditTriggers)
        self.results_view.clicked.connect(self._choose_match)
        self.results_view.activated.connect(self._choose_match)
        layout.addWidget(self.results_view, 1)
        self.message = QLabel(self._message)
        self.message.setObjectName('searchResultsMessage')
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.query.textChanged.connect(self._criteria_edited)
        self.case_box.toggled.connect(self._criteria_edited)
        self.whole_box.toggled.connect(self._criteria_edited)
        self._refresh_controls()
        self.setFocusProxy(self.query)

    def set_query(self, text):
        self.query.setText(str(text or ''))

    def query_text(self):
        return self.query.text()

    def options(self):
        return {'case_sensitive': self.case_box.isChecked(), 'whole_word': self.whole_box.isChecked()}

    def _criteria_edited(self, *_):
        self._refresh_controls()
        self.criteria_changed.emit()

    def _request_find(self):
        if not self.query.text().strip():
            self._message = 'Escribe el texto que deseas buscar.'
            self._refresh_controls()
            self.query.setFocus()
            return
        self.find_requested.emit(self.query.text(), self.case_box.isChecked(), self.whole_box.isChecked())

    def set_matches(self, matches, current_index=-1):
        self.model.set_matches(matches)
        self._message = '' if self.model.matches else 'Prueba otro texto o cambia las opciones.'
        self.set_current_index(current_index)

    def set_current_index(self, index):
        count = self.model.rowCount()
        self._current_index = index if 0 <= index < count else -1
        if self._current_index >= 0:
            model_index = self.model.index(self._current_index)
            self.results_view.setCurrentIndex(model_index)
            self.results_view.scrollTo(model_index, QListView.EnsureVisible)
        else:
            self.results_view.clearSelection()
            self.results_view.setCurrentIndex(QModelIndex())
        self._refresh_controls()

    def _choose_match(self, index):
        if not self._busy and index.isValid() and 0 <= index.row() < self.model.rowCount():
            self.set_current_index(index.row())
            self.match_requested.emit(index.row())

    def clear_results(self, message='Escribe un texto y pulsa Enter o Buscar.'):
        self.model.set_matches([])
        self._current_index = -1
        self._message = str(message or '')
        self._refresh_controls()

    def set_busy(self, busy):
        self._busy = bool(busy)
        self._refresh_controls()

    def _refresh_controls(self):
        count = self.model.rowCount()
        if self._current_index >= 0 and count:
            self.count_label.setText(f'Resultado {self._current_index + 1} de {count}')
        else:
            self.count_label.setText(('1 resultado' if count == 1 else f'{count} resultados')
                                     if count else 'Sin resultados')
        self.previous_button.setEnabled(bool(count) and not self._busy)
        self.next_button.setEnabled(bool(count) and not self._busy)
        self.results_view.setEnabled(not self._busy)
        # Searching again replaces the pending query in the controller instead
        # of making the user wait for a stale calculation.
        self.find_button.setEnabled(bool(self.query.text().strip()))
        self.message.setText('Buscando…' if self._busy else self._message)
        self.message.setVisible(self._busy or bool(self._message))
