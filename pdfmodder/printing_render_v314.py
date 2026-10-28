"""Apply PDF annotation print flags to a private rendering snapshot only."""
import pymupdf as fitz

from .draft_control_v305 import checkpoint


def _annotation_flags_v314(document, xref):
    kind, value = document.xref_get_key(xref, 'F')
    if kind == 'xref':
        # PDF integer values may be indirect; preserve their value while
        # replacing only the annotation's own /F entry in this private copy.
        try:
            value = document.xref_object(int(value.split()[0]), compressed=True).strip()
        except (ValueError, IndexError, RuntimeError):
            return 0
    try:
        return int(value) if kind in ('int', 'xref') else 0
    except (TypeError, ValueError):
        return 0


def _print_flags_v314(flags):
    printable = bool(flags & fitz.PDF_ANNOT_IS_PRINT
                     and not flags & (fitz.PDF_ANNOT_IS_INVISIBLE | fitz.PDF_ANNOT_IS_HIDDEN))
    if printable:
        return flags & ~(fitz.PDF_ANNOT_IS_NO_VIEW | fitz.PDF_ANNOT_IS_TOGGLE_NO_VIEW)
    return flags | fitz.PDF_ANNOT_IS_HIDDEN | fitz.PDF_ANNOT_IS_NO_VIEW


def _direct_annotations_v314(document, page):
    # Valid PDFs can place annotation dictionaries directly in /Annots. Those
    # have no xref for the public setter. Use the pinned MuPDF object API only
    # for this case, changing the same /F integer and leaving /AP untouched.
    pdf = fitz._as_pdf_document(document)
    page_object = fitz.mupdf.pdf_lookup_page_obj(pdf, page.number)
    annotations = fitz.mupdf.pdf_dict_gets(page_object, 'Annots')
    changed = False
    for index in range(fitz.mupdf.pdf_array_len(annotations)):
        checkpoint()
        annotation = fitz.mupdf.pdf_array_get(annotations, index)
        if fitz.mupdf.pdf_is_indirect(annotation):
            continue
        flags = fitz.mupdf.pdf_to_int(fitz.mupdf.pdf_dict_gets(annotation, 'F'))
        adjusted = _print_flags_v314(flags)
        if adjusted != flags:
            fitz.mupdf.pdf_dict_puts(annotation, 'F', fitz.mupdf.pdf_new_int(adjusted))
            changed = True
    return changed


def print_annotation_page_v314(document, page):
    """Use print visibility, retaining existing annotation/widget appearances.

    MuPDF's ordinary pixmap operation uses screen visibility. This document is
    opened afresh from immutable history bytes by the print worker; modifying
    its flags does not alter those bytes or any cached on-screen document.
    """
    changed = False
    direct = False
    for xref, *_ in page.annot_xrefs():
        checkpoint()
        if not xref:
            direct = True
            continue
        flags = _annotation_flags_v314(document, xref)
        adjusted = _print_flags_v314(flags)
        if adjusted != flags:
            document.xref_set_key(xref, 'F', str(adjusted))
            changed = True
    if direct:
        changed = _direct_annotations_v314(document, page) or changed
    return document.reload_page(page) if changed else page
