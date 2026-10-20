"""Office conversion runs serially in the PDF process, also without an open PDF."""
from pathlib import Path

from .draft_control_v305 import DraftCancelled, controlled_draft
from .shell_requests_v305 import validate_selection


def convert_office_batch(paths, destination_dir=None, _office_ticket=None):
    from .office_conversion_v305 import convert_document_to_pdf, ConversionCancelled

    paths = validate_selection('convert', paths)
    destination = None
    if destination_dir is not None:
        destination = Path(destination_dir)
        if not destination.is_absolute() or not destination.is_dir():
            raise ValueError('La carpeta de destino no existe.')

    def cancelled():
        if _office_ticket is None:
            return False
        try:
            with controlled_draft(_office_ticket):
                pass
        except DraftCancelled:
            return True
        return False

    result = {'results': [], 'errors': [], 'cancelled': False}
    for source in paths:
        if cancelled():
            result['cancelled'] = True
            break
        target = destination / Path(source).with_suffix('.pdf').name if destination else None
        try:
            report = convert_document_to_pdf(source, target, cancel=cancelled)
        except ConversionCancelled:
            result['cancelled'] = True
            break
        except Exception as exc:
            result['errors'].append({'source': source, 'error': str(exc)})
        else:
            result['results'].append(report)
    return result
