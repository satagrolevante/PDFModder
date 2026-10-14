"""A narrowly owned URI-link transaction for the native text compositor.

The source annotation is never removed or recreated. Only its rectangle and,
when the complete visible address identifies its recipient, its URI may change.
All annotation dictionaries, shared dependencies and document metadata receive
an independent semantic proof after the final PDF write.
"""
from copy import deepcopy
from io import BytesIO
import hashlib
import math
import re
from urllib.parse import quote, unquote

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import (ArrayObject, BooleanObject, ByteStringObject,
    DictionaryObject, FloatObject, IndirectObject, NameObject, NullObject,
    StreamObject, TextStringObject)

from .model import EditError, intersects, union
from .pdf_object_identity_v303 import _stream_encoding_keys


def _fail(detail):
    raise EditError('Enlace de texto: '+detail)


def _object(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def _annotation_snapshot(reader):
    """Canonical graph, including aliases/cycles, independent of xref numbering."""
    pages = {(p.indirect_reference.idnum, p.indirect_reference.generation): n
             for n, p in enumerate(reader.pages)}
    seen, pending = {}, []

    def encode(value):
        if isinstance(value, IndirectObject):
            identity = (value.idnum, value.generation)
            if identity in pages:
                return ('page', pages[identity])
            value = value.get_object()
        if isinstance(value, (dict, list, tuple)):
            identity = id(value)
            if identity not in seen:
                if len(pending) >= 100000:
                    _fail('las dependencias de las anotaciones superan el análisis verificable.')
                seen[identity] = len(pending)
                pending.append(value)
            return ('object', seen[identity])
        if isinstance(value, NullObject) or value is None:
            return ('null',)
        if isinstance(value, BooleanObject):
            return ('boolean', value.value)
        if isinstance(value, bool):
            return ('boolean', value)
        if isinstance(value, NameObject):
            return ('name', str(value))
        if isinstance(value, ByteStringObject):
            return ('bytes', bytes(value).hex())
        if isinstance(value, str):
            return ('text', value)
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                _fail('una propiedad de anotación contiene un número no finito.')
            return ('number', round(float(value), 8))
        _fail('una propiedad de anotación no tiene un tipo PDF verificable.')

    catalog = reader.trailer['/Root']
    roots = (tuple(encode(page.get('/Annots')) for page in reader.pages),
             encode(reader.trailer.get('/Info')), encode(catalog.get('/Metadata')))
    graph = []
    for value in pending:
        if isinstance(value, dict):
            if isinstance(value, StreamObject) and '/F' in value:
                _fail('una dependencia de anotación usa un archivo externo.')
            # JPEG/JPX/JBIG2 decoders can return their opaque payload unchanged.
            # Its codec and parameters therefore remain part of the proof.
            omitted = _stream_encoding_keys(value) if isinstance(value, StreamObject) else set()
            node = tuple((str(key), encode(item)) for key, item in sorted(value.items())
                         if key not in omitted)
            if isinstance(value, StreamObject):
                node = ('stream', node, hashlib.sha256(value.get_data()).hexdigest())
            else:
                node = ('dictionary', node)
        else:
            node = ('array', tuple(encode(item) for item in value))
        graph.append(node)
    return roots, tuple(graph)


def _glyph_key(glyph):
    return (glyph.text, glyph.font, round(glyph.size, 6),
            tuple(round(v, 5) for v in glyph.origin),
            tuple(round(v, 5) for v in glyph.bbox))


def _link_key(link):
    # Only serialization object numbers may change. In particular /NM-derived
    # IDs and destination page/number properties are not a blanket allowance.
    if isinstance(link, dict):
        return {key: _link_key(value) for key, value in link.items() if key != 'xref'}
    if isinstance(link, (list, tuple, fitz.Rect, fitz.Point)):
        return tuple(_link_key(value) for value in link)
    if isinstance(link, float):
        return round(link, 3)
    return link


def _email(value):
    if not isinstance(value, str) or len(value) > 254 or value.count('@') != 1:
        return False
    local, domain = value.split('@')
    if not local or len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in local:
        return False
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return False
    return bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
                            r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+', domain))


def _same_email(first, second):
    if not _email(first) or not _email(second):
        return False
    a, ad = first.rsplit('@', 1)
    b, bd = second.rsplit('@', 1)
    return a == b and ad.lower() == bd.lower()


def _destination(uri, before, after):
    if not after:
        return uri, 'disabled', 'Texto eliminado: el enlace queda sin área activa y conserva su destino como metadato.'
    if uri[:7].lower() != 'mailto:':
        return uri, 'preserved_label', 'Se cambió la etiqueta visible; se conserva el destino URI del enlace.'
    address_and_query, marker, fragment = uri[7:].partition('#')
    address, query_marker, query = address_and_query.partition('?')
    if re.search(r'%(?![0-9A-Fa-f]{2})', address):
        _fail('el destinatario mailto contiene escapes porcentuales no verificables.')
    try:
        decoded = unquote(address, encoding='utf-8', errors='strict')
    except UnicodeDecodeError:
        _fail('el destinatario mailto no tiene una codificación UTF-8 verificable.')
    before_address, after_address = before.strip(), after.strip()
    if not _same_email(before_address, decoded):
        return uri, 'preserved_label', 'La etiqueta visible no identifica un único destinatario mailto; se conserva el destino.'
    if not _email(after_address):
        return uri, 'preserved_label', 'El nuevo texto es una etiqueta, no una dirección de correo completa; se conserva el destino.'
    if before_address == after_address:
        return uri, 'preserved_address', 'La dirección visible no cambió; se conserva el destino mailto original.'
    # Never use unquote_plus: a plus sign is part of an email local-part.
    destination = uri[:7]+quote(after_address, safe='@')
    if query_marker:
        destination += '?'+query
    if marker:
        destination += '#'+fragment
    return destination, 'updated_mailto', 'Se actualizó el destinatario mailto junto con la dirección visible; se conservan sus parámetros.'


class LinkedTextEdit:
    """Prepared from an immutable snapshot; a guard allowance owns exact glyphs."""
    def __init__(self, data, page, model, selected, replacement, links, link,
                 reader, index, annotation, source_rect, pdf_matrix, rotation, bounds):
        self.page, self.xref, self.index = page, link['xref'], index
        self.revision = hashlib.sha256(data).hexdigest()
        self._reader = reader
        self._before_snapshot = _annotation_snapshot(reader)
        self._expected_snapshot = None
        self._annotation = annotation
        self._original_link = deepcopy(link)
        self.expected_links = deepcopy(links)
        self._source_keys = {_glyph_key(g) for g in selected}
        self._planned_keys = set()
        self._model, self._selected = model, selected
        self._source_rect, self._pdf_matrix = source_rect, pdf_matrix
        self._rotation, self._bounds = rotation, bounds
        self._source_bbox = fitz.Rect(union(g.bbox for g in selected))
        before = ''.join(g.text for g in selected)
        self.uri, self.destination_policy, self.reason = _destination(link['uri'], before, replacement)
        self._replacement = replacement
        self._planned = False
        self.active_area_disabled = not replacement
        self.area_updated = False

    def allows_link(self, page, link, glyph):
        """Only the bound original annotation and original/planned glyphs qualify."""
        return (page.number == self.page and link.get('xref') == self.xref
                and _link_key(link) == _link_key(self._original_link)
                and _glyph_key(glyph) in self._source_keys | self._planned_keys)

    def plan(self, planned):
        if ''.join(g.text for g in planned) != self._replacement.replace('\n', '').replace('\u2028', '').replace('\t', ''):
            _fail('los glifos previstos no corresponden al texto solicitado.')
        if planned:
            box = fitz.Rect(union(g.bbox for g in planned))
            offsets = [a-b for a, b in zip(self._source_rect, self._source_bbox)]
            area = fitz.Rect([v+delta for v, delta in zip(box, offsets)])
            if area.is_empty or not self._bounds.contains(area):
                _fail('el área activa nueva queda fuera de la página o no es verificable.')
            # Never acquire neighboring text by enlarging a clickable rectangle.
            chosen = {g.id for g in self._selected}
            for glyph in self._model.glyphs:
                if glyph.id not in chosen and glyph.mode != 3 and glyph.opacity > 0:
                    center = fitz.Point((glyph.bbox[0]+glyph.bbox[2])/2, (glyph.bbox[1]+glyph.bbox[3])/2)
                    if area.contains(center) and not self._source_rect.contains(center):
                        _fail('el área activa nueva incluiría texto vecino ajeno al enlace.')
            for link in self.expected_links:
                if link['xref'] != self.xref:
                    other = fitz.Rect(link['from'])*~self._rotation
                    if intersects(tuple(area), tuple(other), .035) and not intersects(tuple(self._source_rect), tuple(other), .035):
                        _fail('el área activa nueva se superpone con otro enlace.')
            raw_rect = area*self._pdf_matrix
            self._raw_rect = tuple(round(v, 3) for v in raw_rect)
            # Match the rectangle readers will observe after numeric serialization.
            stored_area = fitz.Rect(self._raw_rect)*~self._pdf_matrix
            expected_area = stored_area*self._rotation
        else:
            self._raw_rect = (0., 0., 0., 0.)
            expected_area = fitz.Rect(self._raw_rect)*~self._pdf_matrix*self._rotation
        self._planned_keys = {_glyph_key(g) for g in planned}
        self.area_updated = tuple(self._raw_rect) != tuple(float(v) for v in self._annotation['/Rect'])
        annotation = self._annotation
        annotation[NameObject('/Rect')] = ArrayObject([FloatObject(v) for v in self._raw_rect])
        if self.uri != self._original_link['uri']:
            action = DictionaryObject(dict(_object(annotation['/A'])))
            action[NameObject('/URI')] = TextStringObject(self.uri)
            annotation[NameObject('/A')] = action
        self._expected_snapshot = _annotation_snapshot(self._reader)
        for link in self.expected_links:
            if link['xref'] == self.xref:
                link['from'], link['uri'] = expected_area, self.uri
        self._planned = True
        return self

    def apply(self, document):
        if not self._planned:
            _fail('el cambio de enlace no tiene una planificación completa.')
        current = PdfReader(BytesIO(document.tobytes(garbage=0, no_new_id=True)), strict=True)
        if _annotation_snapshot(current) != self._before_snapshot:
            _fail('una anotación o sus dependencias cambiaron desde la planificación.')
        refs = _object(current.pages[self.page].get('/Annots', []))
        reference = refs[self.index]
        if not isinstance(reference, IndirectObject) or reference.idnum != self.xref:
            _fail('la identidad de la anotación cambió antes de aplicar el enlace.')
        document.xref_set_key(self.xref, 'Rect', '['+' '.join(f'{v:.3f}' for v in self._raw_rect)+']')
        if self.uri != self._original_link['uri']:
            action = _object(self._annotation['/A'])
            buffer = BytesIO()
            action.write_to_stream(buffer)
            document.xref_set_key(self.xref, 'A', buffer.getvalue().decode('latin1'))

    def validate(self, output):
        if not self._planned or _annotation_snapshot(PdfReader(BytesIO(output), strict=True)) != self._expected_snapshot:
            _fail('la edición alteró anotaciones, sus propiedades, recursos o metadatos fuera del cambio previsto.')
        with fitz.open(stream=output, filetype='pdf') as document:
            if _link_key(document[self.page].get_links()) != _link_key(self.expected_links):
                _fail('el destino o el área activa resultante no coincide con el enlace previsto.')
        return {'verified': True, 'annotation_properties_preserved': True,
                'annotation_resources_preserved': True, 'metadata_preserved': True}

    def report(self):
        result = {'link_xref': self.xref, 'destination_policy': self.destination_policy,
                  'reason': self.reason, 'area_updated': self.area_updated,
                  'active_area_disabled': self.active_area_disabled}
        if self.active_area_disabled:
            result['warnings'] = ['El texto visible se eliminó y el enlace quedó sin área activa. Su destino se conserva como metadato; usa Censurar para retirarlo del archivo.']
        return result


def prepare_linked_text(data, page_number, model, selected, replacement):
    """Bind one complete URI-linked label, or retain the ordinary strict guard."""
    if not selected:
        return None
    if model.revision and model.revision != hashlib.sha256(data).hexdigest():
        _fail('la selección pertenece a otra revisión.')
    with fitz.open(stream=data, filetype='pdf') as document:
        page = document[page_number]
        links = page.get_links()
        derotation, rotation = page.derotation_matrix, page.rotation_matrix
        hits = [link for link in links if any(intersects(tuple(fitz.Rect(link['from'])*derotation), glyph.bbox) for glyph in selected)]
        if not hits:
            return None
        if len(hits) != 1 or hits[0].get('kind') != fitz.LINK_URI or not hits[0].get('uri'):
            _fail('selecciona una etiqueta completa de un único enlace URI verificable.')
        link = hits[0]
        area = fitz.Rect(link['from'])*derotation
        associated = [g for g in model.glyphs if g.mode == 0 and g.opacity > 0 and area.contains(
            fitz.Point((g.bbox[0]+g.bbox[2])/2, (g.bbox[1]+g.bbox[3])/2))]
        # Exporters can include boundary space advances in the hotspot. They
        # paint no label; selecting the visible word need not select that pad.
        visible = list(associated)
        while visible and visible[0].text.isspace():
            visible.pop(0)
        while visible and visible[-1].text.isspace():
            visible.pop()
        selected_ids = {g.id for g in selected}
        if (not visible or not {g.id for g in visible} <= selected_ids
                or not selected_ids <= {g.id for g in associated}):
            _fail('selecciona todo el texto visible del enlace; un fragmento no identifica su destino y área activa.')
        old_rotation = page.rotation
        page.set_rotation(0)
        pdf_matrix = ~page.transformation_matrix
        bounds = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        page.set_rotation(old_rotation)
    reader = PdfReader(BytesIO(data), strict=True)
    matches = [(n, i, reference) for n, pdf_page in enumerate(reader.pages)
               for i, reference in enumerate(_object(pdf_page.get('/Annots', [])))
               if isinstance(reference, IndirectObject) and reference.idnum == link['xref']]
    if len(matches) != 1 or matches[0][0] != page_number or matches[0][2].generation != 0:
        _fail('la anotación está compartida o no tiene una identidad única verificable.')
    _, index, reference = matches[0]
    annotation = reference.get_object()
    action = _object(annotation.get('/A'))
    if (annotation.get('/Subtype') != '/Link' or not isinstance(action, dict)
            or action.get('/S') != '/URI' or not isinstance(action.get('/URI'), str)
            or action['/URI'] != link['uri']):
        _fail('la acción original del enlace no corresponde a un URI verificable.')
    if any(key in annotation for key in ('/AA', '/AP', '/QuadPoints', '/Dest', '/OC')) or '/Next' in action:
        _fail('el enlace contiene apariencias, áreas o acciones adicionales que requieren una edición específica.')
    is_map = _object(action.get('/IsMap', False))
    if isinstance(is_map, BooleanObject):
        is_map = is_map.value
    if set(action)-{'/S', '/URI', '/IsMap'} or is_map is not False:
        _fail('la acción URI tiene propiedades adicionales o coordenadas de mapa no compatibles.')
    return LinkedTextEdit(data, page_number, model, selected, str(replacement), links,
                          link, reader, index, annotation, area, pdf_matrix, rotation, bounds)
