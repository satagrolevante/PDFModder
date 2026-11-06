"""Structured, pickle-safe font-choice requests from the PDF worker."""
from .model import EditError


def face_identity(style):
    return tuple(style.get(key) for key in ('font_name', 'font_file', 'font_resource', 'font_xref'))


class FontChoiceRequired(EditError):
    def __init__(self, message, source_style=None, text=''):
        super().__init__(message)
        self.source_style = dict(source_style or {})
        self.text = text
