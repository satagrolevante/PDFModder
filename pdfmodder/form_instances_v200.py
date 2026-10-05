"""Expand only selected Form invocations into a page-local content stream.

The original Form objects are never updated. Resource names are remapped with
a PDF parser and each invocation keeps its matrix, bounding clip and paint
position. A disposable coloured probe binds text to invocation paths. Groups,
optional content and tagged Forms stay blocked because flattening their
semantics requires more than q/cm/Q. No raster content is exported.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import copy
import math

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream, DictionaryObject, FloatObject, NameObject, NumberObject

from .model import EditError
from .clipping import SHOW, _serialize


def _dictionary(value):
    value = value.get_object() if hasattr(value, 'get_object') else value
    return value if isinstance(value, dict) else {}


def _copy_dict(value):
    return DictionaryObject({key: value.raw_get(key) if hasattr(value, 'raw_get') else item
                             for key, item in value.items()})


def _pdf_object(value):
    output = BytesIO()
    value.write_to_stream(output)
    return output.getvalue().decode('latin1')


class _Expansion:
    def __init__(self, reader, number, targets=None, probing=False):
        self.reader, self.page = reader, reader.pages[number]
        self.base = _dictionary(self.page['/Resources'])
        self.resources = _copy_dict(self.base)
        self.targets, self.probing = targets, probing
        self.names, self.owners, self.forms = {}, {}, {}
        self.counter = self.marker = self.op_count = 0

    def _rename(self, resources, category, name):
        if resources is self.base:
            return name
        source = _dictionary(resources.get(category, {}))
        if name not in source:
            raise EditError('El Form usa un recurso sin declarar: '+str(name)+'.')
        raw = source.raw_get(name) if hasattr(source, 'raw_get') else source[name]
        pointer = getattr(raw, 'idnum', None)
        identity = (category, pointer if pointer is not None else id(raw), str(name))
        if identity not in self.names:
            destination = _dictionary(self.resources.get(category, {}))
            if self.resources.get(category) is not destination:
                destination = _copy_dict(destination)
                self.resources[NameObject(category)] = destination
            else:
                # Do not mutate the source reader's resource dictionary.
                if destination is _dictionary(self.base.get(category, {})):
                    destination = _copy_dict(destination)
                    self.resources[NameObject(category)] = destination
            while True:
                self.counter += 1
                candidate = NameObject('/PMForm'+str(self.counter))
                if candidate not in destination:
                    break
            destination[candidate] = raw
            self.names[identity] = candidate
        return self.names[identity]

    def _should_expand(self, path):
        return self.targets is None or any(target[:len(path)] == path for target in self.targets)

    def walk(self, operations, resources, path=(), ancestors=()):
        if len(path) > 16:
            raise EditError('El contenido Form supera 16 niveles; no puede aislarse con seguridad.')
        result = []
        for index, (original_args, op) in enumerate(operations):
            self.op_count += 1
            if self.op_count > 250000:
                raise EditError('La página supera el límite de operaciones para aislar un Form.')
            args = copy.copy(original_args)
            if op == b'Do':
                objects = _dictionary(resources.get('/XObject', {}))
                obj = objects.get(args[0])
                obj = obj.get_object() if hasattr(obj, 'get_object') else obj
                invocation = path+(index,)
                if isinstance(obj, dict) and obj.get('/Subtype') == '/Form' and self._should_expand(invocation):
                    pointer = getattr(getattr(obj, 'indirect_reference', None), 'idnum', id(obj))
                    if pointer in ancestors:
                        raise EditError('El Form contiene una referencia recursiva; no se ha modificado.')
                    self.forms[invocation] = obj
                    if not self.probing:
                        forbidden = [key for key in ('/Group', '/OC', '/Ref', '/StructParent', '/StructParents') if obj.get(key) is not None]
                        if forbidden:
                            raise EditError('Esta instancia Form requiere conservar '+', '.join(forbidden)+
                                            '; edita otro elemento. Sus recursos compartidos siguen intactos.')
                    matrix = [float(v) for v in obj.get('/Matrix', (1, 0, 0, 1, 0, 0))]
                    bounds = [float(v) for v in obj.get('/BBox', ())]
                    if (len(matrix) != 6 or len(bounds) != 4 or not all(math.isfinite(v) for v in matrix+bounds)
                            or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]
                            or abs(matrix[0]*matrix[3]-matrix[1]*matrix[2]) < 1e-12):
                        raise EditError('La matriz o el límite del Form no es verificable.')
                    nested = _dictionary(obj.get('/Resources', resources))
                    result.extend([([], b'q'), ([FloatObject(v) for v in matrix], b'cm'),
                                   ([FloatObject(v) for v in (bounds[0], bounds[1], bounds[2]-bounds[0], bounds[3]-bounds[1])], b're'),
                                   ([], b'W'), ([], b'n')])
                    result.extend(self.walk(ContentStream(obj, self.reader).operations, nested, invocation, ancestors+(pointer,)))
                    result.append(([], b'Q'))
                    continue
                args[0] = self._rename(resources, '/XObject', args[0])
            elif op == b'Tf':
                args[0] = self._rename(resources, '/Font', args[0])
            elif op == b'gs':
                args[0] = self._rename(resources, '/ExtGState', args[0])
            elif op in (b'cs', b'CS') and args[0] not in ('/DeviceRGB', '/DeviceCMYK', '/DeviceGray', '/Pattern'):
                args[0] = self._rename(resources, '/ColorSpace', args[0])
            elif op == b'sh':
                args[0] = self._rename(resources, '/Shading', args[0])
            elif op in (b'BDC', b'DP') and isinstance(args[-1], NameObject):
                args[-1] = self._rename(resources, '/Properties', args[-1])
            elif op in (b'scn', b'SCN') and args and isinstance(args[-1], NameObject):
                args[-1] = self._rename(resources, '/Pattern', args[-1])
            if self.probing and op in SHOW:
                self.marker += 1
                if self.marker >= 0xffffff:
                    raise EditError('Demasiadas operaciones de texto para identificar la instancia.')
                self.owners[self.marker] = path
                rgb = [FloatObject(v/255) for v in ((self.marker >> 16)&255, (self.marker >> 8)&255, self.marker&255)]
                result.extend([(rgb, b'rg'), (rgb, b'RG')])
            result.append((args, op))
        return result

    def write(self, data, number, operations):
        with fitz.open(stream=data, filetype='pdf') as doc:
            resource = doc.get_new_xref()
            doc.update_object(resource, _pdf_object(self.resources))
            stream = doc.get_new_xref()
            doc.update_object(stream, '<<>>')
            doc.update_stream(stream, _serialize(operations))
            doc.xref_set_key(doc[number].xref, 'Resources', f'{resource} 0 R')
            doc[number].set_contents(stream)
            return doc.tobytes(garbage=0, deflate=True, no_new_id=True)


def isolate_selected_forms(data, request):
    """Return (local PDF, rebound request, report), or None outside Forms.

    Immutable glyph IDs are preserved by an exact trace-order/position check.
    The production expansion must pass complete-page appearance validation
    with no excluded regions before the caller can edit any text.
    """
    with fitz.open(stream=data, filetype='pdf') as doc:
        if not doc[request.page].get_xobjects():
            return None
        original = [(chr(c[0]), tuple(c[2]), span) for span in doc[request.page].get_texttrace() for c in span['chars']]
        if any(index < 0 or index >= len(original) for index in request.ids):
            raise EditError('La selección del Form está desactualizada; vuelve a seleccionarla.')
    reader = PdfReader(BytesIO(data), strict=True)
    operations = ContentStream(reader.pages[request.page].get_contents(), reader).operations
    probe = _Expansion(reader, request.page, probing=True)
    probe_data = probe.write(data, request.page, probe.walk(operations, probe.base))
    with fitz.open(stream=probe_data, filetype='pdf') as doc:
        traced = [(chr(c[0]), tuple(c[2]), span) for span in doc[request.page].get_texttrace() for c in span['chars']]
    if len(traced) != len(original):
        raise EditError('No se pudo identificar la instancia Form sin alterar su texto.')
    ownership = {}
    for index, ((text, point, _), (actual, origin, span)) in enumerate(zip(original, traced)):
        if text != actual or any(abs(a-b) > .025 for a, b in zip(point, origin)) or len(span['color']) != 3:
            raise EditError('No se pudo verificar la posición de la instancia Form.')
        rgb = [round(v*255) for v in span['color']]
        marker = (rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
        if marker not in probe.owners:
            # Invisible OCR cannot be safely identified by a colour marker.
            ownership[index] = None
        else:
            ownership[index] = probe.owners[marker]
    targets = {ownership[index] for index in request.ids if ownership[index]}
    if not targets:
        return None
    if any(ownership[index] is None for index in request.ids):
        raise EditError('La instancia contiene texto invisible sin un operador verificable.')
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        raise EditError('El texto está en un Form etiquetado; falta preservar sus relaciones de estructura al aislar esta instancia.')
    expanded = _Expansion(reader, request.page, targets=targets)
    local = expanded.write(data, request.page, expanded.walk(operations, expanded.base))
    from .validation import assert_pixels, related
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=local, filetype='pdf') as after:
        a, b = before[request.page], after[request.page]
        actual = [(chr(c[0]), tuple(c[2]), span) for span in b.get_texttrace() for c in span['chars']]
        if len(actual) != len(original):
            raise EditError('El aislamiento de la instancia cambió el número de caracteres.')
        for (text, point, style), (new_text, new_point, new_style) in zip(original, actual):
            if (text != new_text or any(abs(x-y) > .025 for x, y in zip(point, new_point))
                    or any(style.get(key) != new_style.get(key) for key in ('font', 'size', 'color', 'opacity', 'type', 'dir'))):
                raise EditError('El aislamiento cambió la tipografía o distribución del texto.')
        if related(a) != related(b):
            raise EditError('El aislamiento alteró imágenes, vectores o elementos relacionados.')
        pixels = assert_pixels(a, b, reproduction=True)
    return local, replace(request, revision=sha256(local).hexdigest()), {
        'selected_instance_count': len(targets), 'shared_objects_unchanged': True,
        'vectors_retained': True, 'paint_order_retained': True, 'isolation_visual': pixels,
    }
