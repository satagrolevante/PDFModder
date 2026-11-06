"""Explicit replacement of an unavailable face; the draft remains uncommitted."""
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QLabel, QPushButton, QVBoxLayout)

from .fonts import FontError, FontResolver, normalized_name


class FontChoiceDialog(QDialog):
    def __init__(self, source_name, text, catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Elegir fuente compatible')
        self.setMinimumWidth(440)
        self.text = text
        self.entry = None
        self.resolver = FontResolver()
        layout = QVBoxLayout(self)
        message = QLabel(f'La fuente «{source_name}» no permite escribir este texto.\n'
                         'Elige otra fuente o importa su versión completa. Se aplicará '
                         'solo a los fragmentos del borrador que usan esa fuente. '
                         'El aspecto puede cambiar; podrás revisar el PDF antes de aceptar.')
        message.setWordWrap(True)
        layout.addWidget(message)
        self.fonts = QComboBox()
        self.fonts.setObjectName('compatibleFontV321')
        # Prefer the exact available face, then the bundled sans face. Nothing
        # changes until the user explicitly presses "Usar en el borrador".
        entries = [dict(e) for e in catalog if e.get('editable') is not False]
        entries.sort(key=lambda e:(normalized_name(e.get('name', '')) != normalized_name(source_name),
                                   'LiberationSans' not in e.get('name', ''), e.get('name', '')))
        for entry in entries:
            self.fonts.addItem(entry.get('name', 'Fuente'), entry)
        layout.addWidget(self.fonts)
        self.import_button = QPushButton('Importar fuente TTF/OTF…')
        self.import_button.clicked.connect(self.import_font)
        layout.addWidget(self.import_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Usar en el borrador')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _verified_entry(self, entry):
        resolved = self.resolver.resolve_explicit(entry['name'], self.text,
            font_file=entry.get('path') or entry.get('font_file'), font_axes=entry.get('font_axes'))
        return dict(entry, buffer=bytes(resolved.buffer or resolved.font.buffer), metadata=resolved.metadata)

    def import_font(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar fuente completa', '', 'Fuentes (*.ttf *.otf)')
        if not path:
            return
        try:
            entry = self._verified_entry({'name':Path(path).stem, 'path':path})
            entry['name'] = entry['metadata'].get('postscript_name') or entry['name']
        except (FontError, OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.fonts.addItem(entry['name'], entry)
        self.fonts.setCurrentIndex(self.fonts.count()-1)
        self.status.setText('Fuente importada. Pulsa «Usar en el borrador» para elegirla.')

    def accept(self):
        entry = self.fonts.currentData()
        if not entry:
            self.status.setText('Elige una fuente o importa un archivo TTF/OTF.')
            return
        try:
            self.entry = self._verified_entry(entry)
        except (FontError, OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        super().accept()
