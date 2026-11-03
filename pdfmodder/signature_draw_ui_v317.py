"""Mouse handwriting with stroke undo and transparent black PNG output."""
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .manual_signatures_v317 import normalise_manual_signature_png_v317


class SignatureDrawingPadV317(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('signatureDrawingPadV317')
        self.setMinimumSize(520, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self.setAccessibleName('Dibujar firma con el ratón')
        self._strokes = []
        self._current = None

    def _point(self, point):
        # A fixed aspect ratio keeps the handwriting undistorted on resize.
        if isinstance(point, QPointF):
            x, y = point.x(), point.y()
        else:
            x, y = point
        scale, left, top = self._viewport()
        return (max(0., min(1., (float(x) - left) / (1600 * scale))),
                max(0., min(1., (float(y) - top) / (640 * scale))))

    def _viewport(self):
        scale = min(max(1, self.width()) / 1600, max(1, self.height()) / 640)
        return scale, (self.width() - 1600 * scale) / 2, (self.height() - 640 * scale) / 2

    def has_ink(self):
        return bool(self._strokes or self._current)

    def add_stroke(self, points):
        points = [self._point(point) for point in points]
        if points:
            self._strokes.append(points)
            self.changed.emit()
            self.update()

    def undo_stroke(self):
        if self._current:
            self._current = None
        elif self._strokes:
            self._strokes.pop()
        else:
            return
        self.changed.emit()
        self.update()

    def clear(self):
        self._current = None
        self._strokes.clear()
        self.changed.emit()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._current = [self._point(event.position())]
            self.changed.emit()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._current is not None and event.buttons() & Qt.LeftButton:
            point = self._point(event.position())
            if point != self._current[-1]:
                self._current.append(point)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._current is not None:
            point = self._point(event.position())
            if point != self._current[-1]:
                self._current.append(point)
            self._strokes.append(self._current)
            self._current = None
            self.changed.emit()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _paint_ink(self, painter, width, height):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('black'), max(1., height / 100.), Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        for stroke in [*self._strokes, *([self._current] if self._current else [])]:
            if len(stroke) == 1:
                painter.drawPoint(QPointF(stroke[0][0] * width, stroke[0][1] * height))
                continue
            path = QPainterPath(QPointF(stroke[0][0] * width, stroke[0][1] * height))
            for x, y in stroke[1:]:
                path.lineTo(x * width, y * height)
            painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        # This white workspace is never included in the exported artwork.
        painter.fillRect(self.rect(), QColor('white'))
        painter.setPen(QColor('#b0bac4'))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        scale, left, top = self._viewport()
        painter.translate(left, top)
        painter.scale(scale, scale)
        self._paint_ink(painter, 1600, 640)
        painter.end()

    def png_data(self):
        if not self.has_ink():
            raise ValueError('Dibuja una firma antes de guardarla.')
        # Stable output resolution does not depend on display DPI or dialog size.
        width, height = 1600, 640
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self._paint_ink(painter, width, height)
        painter.end()
        output = QBuffer()
        output.open(QIODevice.WriteOnly)
        if not image.save(output, 'PNG'):
            raise ValueError('No se ha podido preparar la firma.')
        return normalise_manual_signature_png_v317(bytes(output.data()))


class SignatureDrawingDialogV317(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('signatureDrawingDialogV317')
        self.setWindowTitle('Crear firma manual')
        self.resize(660, 360)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('Nombre'))
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName('signatureDrawingNameV317')
        self.name_edit.setMaxLength(100)
        self.name_edit.setPlaceholderText('Por ejemplo, Firma habitual')
        row.addWidget(self.name_edit)
        layout.addLayout(row)
        hint = QLabel('Dibuja con el ratón. Se guardará en negro y con fondo transparente.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.pad = SignatureDrawingPadV317()
        layout.addWidget(self.pad, 1)
        tools = QHBoxLayout()
        self.undo_button = QPushButton('Deshacer trazo')
        self.undo_button.setObjectName('signatureDrawingUndoV317')
        self.clear_button = QPushButton('Borrar dibujo')
        self.clear_button.setObjectName('signatureDrawingClearV317')
        tools.addWidget(self.undo_button)
        tools.addWidget(self.clear_button)
        tools.addStretch()
        layout.addLayout(tools)
        self.message = QLabel()
        self.message.setObjectName('signatureDrawingMessageV317')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText('Guardar firma')
        self.buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.undo_button.clicked.connect(self.pad.undo_stroke)
        self.clear_button.clicked.connect(self.pad.clear)
        self.pad.changed.connect(self._refresh)
        self.name_edit.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        enabled = self.pad.has_ink()
        self.undo_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(enabled and bool(self.name_edit.text().strip()))
        self.message.clear()

    def signature_data(self):
        name = ' '.join(self.name_edit.text().split())
        if not name:
            raise ValueError('Escribe un nombre para la firma.')
        return name, self.pad.png_data()

    def accept(self):
        try:
            self.signature_data()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        super().accept()
