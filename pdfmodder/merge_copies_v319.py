"""Private, independently checked consultation copies for whole-PDF merging.

This module never relaxes the editor's signature checks. Only the explicit
``as_copy`` merge transaction calls it, and ordinary PDFs return unchanged.
Widget appearances become ordinary PDF artwork, never page-sized bitmaps.
"""
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import math

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, StreamObject

from .model import EditError
from .untag_v180 import _metadata_and_bookmarks, _remove_associations
from .validation import (_canonical, assert_characters, assert_pixels,
                         assert_text_object_structure, trace_chars)
from .draft_control_v305 import checkpoint


def _obj(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def _nodes(root):
    pending, seen = [root], set()
    while pending:
        checkpoint()
        value = _obj(pending.pop())
        if not isinstance(value, (dict, list, tuple)) or id(value) in seen:
            continue
        seen.add(id(value))
        yield value
        pending.extend(value.values() if isinstance(value, dict) else value)


def _clone(reader):
    writer = PdfWriter(clone_from=reader)
    writer.pdf_header = reader.pdf_header
    if '/Info' in reader.trailer:
        writer._info_obj = writer._add_object(reader.trailer['/Info'].clone(writer))
    return writer


def _write(writer):
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _writer_view(writer, source):
    """Read a planned graph before any serializer can damage its metadata."""
    from types import SimpleNamespace
    trailer = {'/Root': writer.root_object}
    if writer._info_obj is not None:
        trailer['/Info'] = writer._info_obj
    # PdfWriter normalizes /ID strings to ByteStringObject while a reader may
    # decode those same bytes as TextStringObject. Keep the original read view
    # for this proof; the final parsed bytes must reproduce it exactly.
    if '/ID' in source.trailer:
        trailer['/ID'] = source.trailer['/ID']
    return SimpleNamespace(trailer=trailer, pages=writer.pages)


def _signature(node):
    return (isinstance(node, dict) and
            (node.get('/FT') == '/Sig' or node.get('/Type') in ('/Sig', '/DocTimeStamp')
             or '/ByteRange' in node))


def _normal_appearance(annotation, *, context):
    appearance = _obj(annotation.get('/AP', {}))
    normal = _obj(appearance.get('/N')) if isinstance(appearance, dict) else None
    if isinstance(normal, dict) and not isinstance(normal, StreamObject):
        state = annotation.get('/AS')
        normal = _obj(normal.get(state)) if state is not None else None
    if not isinstance(normal, StreamObject):
        raise EditError(f'{context}: el campo visible no tiene una apariencia normal reproducible; se conserva el original.')
    bbox = _obj(normal.get('/BBox', []))
    if len(bbox) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
        raise EditError(f'{context}: la apariencia del campo tiene límites no verificables.')
    return normal


def _visible(annotation):
    rect = _obj(annotation.get('/Rect', []))
    if len(rect) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect):
        raise EditError('Un campo contiene un rectángulo no verificable.')
    # Hidden and NoView widgets have no screen appearance to preserve. A zero
    # area signature is a normal timestamp/certification use case.
    return (rect[0] != rect[2] and rect[1] != rect[3]
            and not int(annotation.get('/F', 0)) & (2 | 32))


def _adjust_claims(writer, *, tagged, signed):
    """Retain unrelated XMP, including custom namespaces and packet wrappers."""
    changes = []
    info = writer._info
    if info:
        for key in list(info):
            name = str(key).lower().lstrip('/')
            if ((tagged and name in ('pdfuaid:part', 'pdfuaid:rev', 'pdfuaid:amd'))
                    or (signed and name in ('signed', 'signature', 'signatures', 'signaturestatus'))):
                del info[key]
                changes.append('Info ' + str(key))
    metadata = _obj(writer.root_object.get('/Metadata'))
    if not isinstance(metadata, StreamObject):
        return changes
    raw = metadata.get_data()
    # The PDF/UA identifier is a conformance assertion about the resulting
    # structure. Signature namespaces likewise cannot describe this copy.
    targets = set()
    if tagged:
        targets.add('http://www.aiim.org/pdfua/ns/id/')
    if signed:
        targets.update(('http://ns.adobe.com/pdf-signature/1.0/',
                        'http://ns.adobe.com/pdf-signature/1.0'))
    if not any(namespace.encode() in raw for namespace in targets):
        return changes
    from lxml import etree
    try:
        tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
        for element in list(tree.iter()):
            if not isinstance(element.tag, str):
                continue
            for key in list(element.attrib):
                if key.startswith('{') and key[1:].split('}', 1)[0] in targets:
                    changes.append('XMP ' + key)
                    del element.attrib[key]
            if element.tag.startswith('{') and element.tag[1:].split('}', 1)[0] in targets:
                parent = element.getparent()
                if parent is None:
                    raise ValueError('conformance claim is the XMP document root')
                changes.append('XMP ' + element.tag)
                parent.remove(element)
        if changes and any(item.startswith('XMP ') for item in changes):
            metadata.set_data(etree.tostring(tree.getroottree(), encoding='utf-8'))
    except Exception as exc:
        raise EditError('No se pueden ajustar las declaraciones XMP de firma o PDF/UA sin perder metadatos.') from exc
    return changes


def _annotation_graph(reader, page_number, *, strip_structure=False):
    from .pageops import _semantic
    page_refs = {(p.indirect_reference.idnum, p.indirect_reference.generation): n
                 for n, p in enumerate(reader.pages)}
    refs = [ref for ref in _obj(reader.pages[page_number].get('/Annots', []))
            if _obj(ref).get('/Subtype') != '/Widget']
    annotation_refs = {(ref.idnum, ref.generation): n for n, ref in enumerate(refs)
                       if isinstance(ref, IndirectObject)}
    result = []
    for ref in refs:
        annotation = dict(_obj(ref))
        annotation.pop('/P', None)
        if strip_structure:
            annotation.pop('/StructParent', None)
            annotation.pop('/ObjectStructParent', None)
        result.append(_semantic(annotation, page_refs=page_refs, annotation_refs=annotation_refs,
                                exact_numbers=True))
    return result


def _geometry(page):
    return (tuple(page.mediabox), tuple(page.cropbox), tuple(page.bleedbox),
            tuple(page.trimbox), tuple(page.artbox), page.rotation, tuple(page.rect))


def _validate_preparation(original, candidate, expected_metadata, *, baked, tagged,
                          appearance_text, planned):
    """No cached proof: inspect every source page and render its complete area."""
    from .pageops import _semantic
    before_reader = PdfReader(BytesIO(original), strict=True)
    after_reader = PdfReader(BytesIO(candidate), strict=True)
    planned_reader = PdfReader(BytesIO(planned), strict=True)
    if _metadata_and_bookmarks(after_reader) != expected_metadata:
        raise EditError('La copia para consulta alteró metadatos, XMP o destinos de marcadores ajenos a la conversión.')
    if any(_signature(node) or (isinstance(node, dict) and any(key in node for key in ('/SigFlags', '/DSS', '/Perms')))
           for node in _nodes(after_reader.trailer['/Root'])):
        raise EditError('La copia todavía contiene firmas o permisos de firma activos.')
    if after_reader.get_fields():
        raise EditError('No se han fijado todos los campos del formulario en la copia.')
    stats = []
    with ExitStack() as stack:
        before = stack.enter_context(fitz.open(stream=original, filetype='pdf'))
        after = stack.enter_context(fitz.open(stream=candidate, filetype='pdf'))
        artwork = before
        if baked:
            artwork = stack.enter_context(fitz.open(stream=original, filetype='pdf'))
            # get_texttrace includes annotation appearances, including zero-size
            # timestamp glyphs outside the page. Inspect original page artwork
            # separately; visible widget text has its own AP/pixel proof below.
            for page in artwork:
                while (widget := next(page.widgets() or iter(()), None)) is not None:
                    page.delete_widget(widget)
        if len(before) != len(after) or len(after_reader.pages) != len(before):
            raise EditError('La copia para consulta cambió el número de páginas.')
        if _canonical(before.get_toc(False)) != _canonical(after.get_toc(False)):
            raise EditError('La copia para consulta cambió los marcadores.')
        for number, (left, right) in enumerate(zip(before, after)):
            checkpoint()
            if _geometry(left) != _geometry(right):
                raise EditError(f'La copia cambió la geometría de la página {number+1}.')
            if (_canonical(left.get_links()) != _canonical(right.get_links())
                    or _annotation_graph(before_reader, number, strip_structure=tagged)
                    != _annotation_graph(after_reader, number)):
                raise EditError(f'La copia cambió enlaces o anotaciones de la página {number+1}.')
            source_content = left.read_contents()
            if (source_content not in right.read_contents() if baked else source_content != right.read_contents()):
                raise EditError(f'La copia cambió los operadores originales de la página {number+1}.')
            # Every original resource is still PDF artwork. Baking may add
            # form XObjects but must never replace fonts/images with a bitmap.
            source_resources = _obj(planned_reader.pages[number].get('/Resources', {}))
            target_resources = _obj(after_reader.pages[number].get('/Resources', {}))
            for key, value in source_resources.items():
                expected, actual = _obj(value), _obj(target_resources.get(key, {}))
                if isinstance(expected, dict):
                    if not isinstance(actual, dict) or any(name not in actual or _semantic(item) != _semantic(actual[name]) for name, item in expected.items()):
                        raise EditError(f'La copia cambió recursos originales de la página {number+1}.')
                elif _semantic(expected) != _semantic(actual):
                    raise EditError(f'La copia cambió recursos originales de la página {number+1}.')
            original_chars, final_chars = trace_chars(artwork[number]), trace_chars(right)
            if not baked:
                assert_characters(original_chars, right)
            else:
                # Widget text was annotation artwork before baking, so the
                # page extractor legitimately gains those characters.
                positions = {}
                for char, point, *_ in final_chars:
                    positions.setdefault(char, []).append(point)
                for char, point, *_ in original_chars:
                    matches = positions.get(char, [])
                    match = next((index for index, target in enumerate(matches)
                                  if abs(point[0]-target[0]) <= .035
                                  and abs(point[1]-target[1]) <= .035), None)
                    if match is None:
                        raise EditError(f'La copia perdió texto original en la página {number+1}.')
                    matches.pop(match)
            compact = lambda text: ''.join((text or '').split())
            expected_text = compact(before_reader.pages[number].extract_text())
            if baked:
                expected_text += ''.join(compact(text) for text in appearance_text[number])
            final_text = compact(after_reader.pages[number].extract_text())
            if expected_text != final_text:
                raise EditError(f'El extractor independiente detectó texto añadido, perdido o modificado en la página {number+1}.')
            stats.append({'page': number, 'text_preserved': True, 'original_resources_preserved': True,
                          **assert_pixels(left, right, excluded=())})
    assert_text_object_structure(candidate, reader=after_reader)
    return stats


def prepare_source(data, index):
    """Return immutable input bytes unchanged, or a fully validated private copy."""
    label = 'Documento actual' if index == 0 else f'PDF añadido {index}'
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        with fitz.open(stream=data, filetype='pdf') as doc:
            if reader.is_encrypted or doc.is_encrypted or doc.needs_pass or (doc.metadata or {}).get('encryption'):
                raise EditError(f'{label}: PDF cifrado; no se genera una copia para combinar.')
            if not doc.permissions & fitz.PDF_PERM_MODIFY:
                raise EditError(f'{label}: el PDF no concede permiso de modificación.')
            if doc.is_repaired or not doc.page_count:
                raise EditError(f'{label}: PDF reparado o sin páginas; no se puede verificar la copia.')
            root = reader.trailer['/Root']
            nodes = list(_nodes(root))
            if any(isinstance(node, dict) and ('/JS' in node or '/JavaScript' in node
                   or node.get('/S') == '/JavaScript') for node in nodes):
                raise EditError(f'{label}: contiene JavaScript; la copia no elimina acciones silenciosamente.')
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if '/XFA' in node:
                    raise EditError(f'{label}: formulario XFA; no se pueden fijar sus apariencias con seguridad.')
                if '/AA' in node or '/OpenAction' in node:
                    raise EditError(f'{label}: contiene acciones automáticas que no se pueden conservar en la copia.')
            form = _obj(root.get('/AcroForm', {}))
            fields = bool(_obj(form.get('/Fields', []))) if isinstance(form, dict) else False
            signed = bool(root.get('/Perms') or root.get('/DSS') or doc.get_sigflags() > 0
                          or any(_signature(node) for node in nodes))
            marked = _obj(root.get('/MarkInfo', {}))
            tagged = bool(root.get('/StructTreeRoot') or (isinstance(marked, dict) and marked.get('/Marked')))
            widgets, appearance_text = 0, []
            for number, page in enumerate(reader.pages):
                texts = []
                for ref in _obj(page.get('/Annots', [])):
                    annotation = _obj(ref)
                    if annotation.get('/Subtype') != '/Widget':
                        continue
                    widgets += 1
                    if _visible(annotation):
                        normal = _normal_appearance(annotation, context=f'{label}, página {number+1}')
                        texts.append(page.extract_xform_text(normal))
                appearance_text.append(texts)
            fields = fields or bool(widgets)
            if not (signed or tagged or fields):
                return data, None
        writer = _clone(reader)
        if _metadata_and_bookmarks(_writer_view(writer, reader)) != _metadata_and_bookmarks(reader):
            raise EditError('La clonación no conserva el grafo completo de metadatos y marcadores.')
        associations = 0
        if tagged:
            writer.root_object.pop(NameObject('/StructTreeRoot'), None)
            writer.root_object.pop(NameObject('/MarkInfo'), None)
            associations = _remove_associations(writer.root_object)
        if signed:
            writer.root_object.pop(NameObject('/Perms'), None)
            writer.root_object.pop(NameObject('/DSS'), None)
        changes = _adjust_claims(writer, tagged=tagged, signed=signed)
        expected_metadata = _metadata_and_bookmarks(_writer_view(writer, reader))
        prepared = _write(writer)
        # The metadata proof is recorded from the complete planned graph before
        # baking; the only intended metadata differences are reported above.
        with fitz.open(stream=prepared, filetype='pdf') as working:
            if fields:
                working.bake(annots=False, widgets=True)
            baked = working.tobytes(garbage=1, deflate=False, incremental=False, no_new_id=True)
        cleaned = _clone(PdfReader(BytesIO(baked), strict=True))
        if fields or signed:
            cleaned.root_object.pop(NameObject('/AcroForm'), None)
        with fitz.open(stream=_write(cleaned), filetype='pdf') as working:
            candidate = working.tobytes(garbage=1, deflate=False, incremental=False, no_new_id=True)
        stats = _validate_preparation(data, candidate, expected_metadata, baked=fields,
                                      tagged=tagged, appearance_text=appearance_text, planned=prepared)
        return candidate, {'index': index, 'signed': signed, 'fields': fields, 'tagged': tagged,
                           'signatures_removed': signed, 'accessibility_removed': tagged,
                           'widgets_baked': widgets, 'metadata_claims_adjusted': changes,
                           'structure_associations_removed': associations, 'verified': True,
                           'original_sha256': sha256(data).hexdigest(),
                           'derived_sha256': sha256(candidate).hexdigest(), 'pages': stats}
    except EditError:
        raise
    except Exception as exc:
        raise EditError(f'{label}: no se puede preparar una copia para consulta verificable ({type(exc).__name__}: {exc}).') from exc


def prepare_sources(inputs):
    prepared, transformed = [], []
    for index, data in enumerate(inputs):
        try:
            payload, report = prepare_source(data, index)
        except EditError as exc:
            label = 'Documento actual' if index == 0 else f'PDF añadido {index}'
            if str(exc).startswith(label + ':') or str(exc).startswith(label + ','):
                raise
            raise EditError(f'{label}: {exc}') from exc
        prepared.append(payload)
        if report is not None:
            transformed.append(report)
    hashes = [sha256(data).hexdigest() for data in inputs]
    duplicates = [{'sha256': digest, 'indices': [i for i, item in enumerate(hashes) if item == digest]}
                  for digest in dict.fromkeys(hashes) if hashes.count(digest) > 1]
    warnings = ['Copia para consulta sin firmas digitales activas: las firmas originales no se trasladan ni conservan su validez en el PDF combinado.']
    if any(item['tagged'] for item in transformed):
        warnings.append('Se retiran las etiquetas de accesibilidad para combinar; se pierde su estructura y orden de lectura lógico. Se conservan ActualText y las capas.')
    if any(item['fields'] for item in transformed):
        warnings.append('Los campos se fijan como apariencia PDF; sus valores y firmas dejan de ser interactivos.')
    return prepared, {'as_copy': True, 'result_unsigned': True, 'warnings': warnings,
                      'original_source_sha256': hashes, 'transformed_sources': transformed,
                      'duplicate_sources': duplicates}


def preflight_layers(reader):
    """Only deterministic default layer configurations can be combined."""
    props = _obj(reader.trailer['/Root'].get('/OCProperties'))
    if props is None:
        return
    if not isinstance(props, dict) or set(props) - {'/OCGs', '/D'}:
        raise EditError('Capas: configuraciones alternativas o propiedades no compatibles; no se eliminan en la copia.')
    groups, config = _obj(props.get('/OCGs', [])), _obj(props.get('/D', {}))
    allowed = {'/Name', '/Creator', '/BaseState', '/ON', '/OFF', '/Order', '/RBGroups',
               '/Locked', '/ListMode', '/AS', '/Intent'}
    if not isinstance(groups, (list, tuple)) or not isinstance(config, dict) or set(config) - allowed:
        raise EditError('Capas: el catálogo contiene una configuración no verificable.')
    if config.get('/BaseState', '/ON') not in ('/ON', '/OFF'):
        raise EditError('Capas: el estado inicial depende de una configuración externa.')
    for group in groups:
        if not isinstance(_obj(group), dict) or _obj(group).get('/Type') != '/OCG':
            raise EditError('Capas: un grupo de contenido opcional no es válido.')
    for key in ('/ON', '/OFF', '/Order', '/RBGroups', '/Locked', '/AS'):
        if key in config and not isinstance(_obj(config[key]), (list, tuple)):
            raise EditError(f'Capas: la propiedad {key} no es una lista verificable.')


def _layer_plan(readers):
    from .pageops import _semantic
    props = [_obj(reader.trailer['/Root'].get('/OCProperties')) for reader in readers]
    present = [item for item in props if item is not None]
    if not present:
        return None
    for reader in readers:
        preflight_layers(reader)
    result = DictionaryObject({NameObject('/OCGs'): ArrayObject()})
    first = _obj(present[0].get('/D', {}))
    default = DictionaryObject({NameObject(key): value for key, value in first.items()
                                if key in ('/Name', '/Creator', '/ListMode', '/Intent')})
    default[NameObject('/BaseState')] = NameObject('/ON')
    on, off = ArrayObject(), ArrayObject()
    for item in present:
        groups = _obj(item.get('/OCGs', []))
        config = _obj(item.get('/D', {}))
        if _semantic(config.get('/Intent', '/View')) != _semantic(first.get('/Intent', '/View')):
            raise EditError('Capas: los documentos utilizan intenciones de visibilidad incompatibles.')
        result['/OCGs'].extend(groups)
        explicit_on = _obj(config.get('/ON', []))
        explicit_off = _obj(config.get('/OFF', []))
        # Preserve both default-on and default-off sources with one unambiguous
        # output default; /OFF wins if a malformed source lists both.
        for group in groups:
            enabled = config.get('/BaseState', '/ON') != '/OFF'
            if group in explicit_on:
                enabled = True
            if group in explicit_off:
                enabled = False
            (on if enabled else off).append(group)
        for key in ('/Order', '/RBGroups', '/Locked', '/AS'):
            if key in config:
                default.setdefault(NameObject(key), ArrayObject()).extend(_obj(config[key]))
    if on:
        default[NameObject('/ON')] = on
    if off:
        default[NameObject('/OFF')] = off
    result[NameObject('/D')] = default
    return result


def rebuild_layers(writer, readers):
    plan = _layer_plan(readers)
    if plan is not None:
        # Clone each source through append()'s existing translation map so
        # catalog OCGs and page-resource OCGs retain shared object identities.
        def clone(value):
            if isinstance(value, IndirectObject):
                return value.clone(writer)
            if isinstance(value, DictionaryObject):
                return DictionaryObject({key: clone(item) for key, item in value.items()})
            if isinstance(value, ArrayObject):
                return ArrayObject([clone(item) for item in value])
            return value.clone(writer)
        writer.root_object[NameObject('/OCProperties')] = clone(plan)


def validate_layers(readers, result):
    from .pageops import _semantic
    expected = _layer_plan(readers)
    actual = result.trailer['/Root'].get('/OCProperties')
    if _semantic(expected) != _semantic(actual):
        raise EditError('La combinación cambió las capas, su orden o sus estados de visibilidad.')
