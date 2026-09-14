"""Validación transaccional de contenido, geometría y apariencia (144 ppp)."""
from collections import Counter
import hashlib
import io
import numpy as np
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream
from .model import EditError, transform_rect


def document_issues(data, doc):
    issues = []
    encrypted=bool(doc.is_encrypted or doc.needs_pass or (doc.metadata or {}).get('encryption'))
    if encrypted:
        issues.append("Documento cifrado: edición y exportación desactivadas en esta versión.")
    if not (doc.permissions & fitz.PDF_PERM_MODIFY):
        issues.append("El documento no concede permiso para modificar contenido.")
    if doc.is_form_pdf:
        issues.append("Contiene campos de formulario; sus valores y cálculos necesitan un editor de formularios.")
    if doc.get_sigflags()>0:
        issues.append("El PDF declara firmas digitales; editar su contenido afectaría a su validación.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt('')  # Empty user password, never bypass owner restrictions.
        root = reader.trailer['/Root']
        form=root.get('/AcroForm')
        if form and form.get_object().get('/XFA'):
            issues.append("Formulario XFA: esta versión no modifica sus datos ni sus apariencias.")
        if root.get('/Perms'):
            issues.append("Documento firmado o certificado: modificar contenido afectaría a la firma.")
        if root.get('/StructTreeRoot'):
            from .tagged import analyze
            try:
                analyze(data)
            except EditError as exc:
                issues.append(str(exc))
        for f in (reader.get_fields() or {}).values():
            if f.get('/FT') == '/Sig':
                issues.append("Contiene un campo de firma digital; se conserva el original y se bloquea la edición.")
    except Exception:
        if not encrypted:
            issues.append("El analizador independiente no puede verificar la estructura de este PDF.")
    return list(dict.fromkeys(issues))


def page_issues(data, number):
    """Analiza operadores con parser PDF, nunca expresiones sobre el binario."""
    issues = []
    try:
        reader = PdfReader(io.BytesIO(data))
        page = reader.pages[number]
        ops = ContentStream(page.get_contents(), reader).operations
        if any(op in (b'W',b'W*') for _,op in ops):
            issues.append("Página con recortes gráficos explícitos: no se puede reconstruir el texto con seguridad.")
        if any(op in (b'BDC', b'BMC') for _,op in ops):
            from .tagged import analyze
            try:
                if analyze(data) is None:
                    issues.append("Página con contenido marcado o capas sin estructura accesible verificable.")
            except EditError as exc:
                issues.append(str(exc))
        resources = page.get('/Resources', {})
        if hasattr(resources,'get_object'):
            resources = resources.get_object()
        for value in resources.get('/ExtGState', {}).values():
            gs = value.get_object()
            if gs.get('/BM', '/Normal') != '/Normal' or gs.get('/SMask', '/None') != '/None':
                issues.append("Página con mezcla de color o máscara de transparencia no reproducible.")
            if gs.get('/OP') or gs.get('/op') or gs.get('/TR') or gs.get('/TR2'):
                issues.append("Página con sobreimpresión o transferencia de color no admitida.")
    except Exception as exc:
        issues.append(f"No se pudo analizar los operadores de esta página: {type(exc).__name__}.")
    return list(dict.fromkeys(issues))


def trace_chars(page):
    return [(chr(c[0]), tuple(c[2]), s['font'], float(s['size']))
            for s in page.get_texttrace() for c in s['chars']]


def assert_characters(expected, page, tolerance=.035):
    actual = trace_chars(page)
    if len(expected) != len(actual):
        raise EditError(f"Validación: se esperaban {len(expected)} caracteres reales y se obtuvieron {len(actual)}.")
    by_char = {}
    for text, origin, *_ in actual:
        by_char.setdefault(text, []).append(origin)
    for text, origin, *_ in expected:
        possibilities = by_char.get(text, [])
        index = next((i for i,p in enumerate(possibilities)
                      if abs(origin[0]-p[0]) <= tolerance and abs(origin[1]-p[1]) <= tolerance), None)
        if index is None:
            raise EditError(f"Validación: el carácter {text!r} cambió o no está en su posición prevista ({origin[0]:.2f}, {origin[1]:.2f}).")
        possibilities.pop(index)


def _canonical(value):
    if isinstance(value, dict):
        # References and paint sequence numbers naturally change after full
        # writing / insertion. Geometry, paint order within this list and all
        # visible properties still must match.
        return {k:_canonical(v) for k,v in value.items() if k not in ('xref','id','seqno','number')}
    if isinstance(value,(tuple,list,fitz.Rect,fitz.Point,fitz.Matrix)):
        return tuple(_canonical(v) for v in value)
    if isinstance(value,float):
        return round(value,3)
    return value


def related(page):
    return _canonical({
        'links':page.get_links(),
        'annots':[(a.type, tuple(a.rect),a.info,a.colors,a.opacity,
                   a.vertices,a.flags,a.border,a.line_ends,a.blendmode) for a in page.annots() or []],
        'widgets':[(w.field_name,w.field_value,w.field_type,tuple(w.rect)) for w in page.widgets() or []],
        'drawings':page.get_drawings(),
        # Compressed stream length can change under a lossless full write.
        # Compare decoded pixel digest, dimensions, mask, placement and colour
        # properties instead; the independent page render checks appearance.
        'images':[{k:v for k,v in info.items() if k!='size'} for info in page.get_image_info(hashes=True)],
    })


def pixel_diff(before, after, excluded=(), dpi=144):
    scale = dpi/72
    if before.rect.width*before.rect.height*scale*scale > 16_000_000:
        raise EditError("Página demasiado grande para la validación visual limitada a 16 millones de píxeles.")
    a = before.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False, colorspace=fitz.csRGB)
    b = after.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False, colorspace=fitz.csRGB)
    if (a.width,a.height) != (b.width,b.height):
        raise EditError("La validación detectó un cambio de dimensiones de página.")
    aa = np.frombuffer(a.samples,dtype=np.uint8).reshape(a.height,a.width,3)
    bb = np.frombuffer(b.samples,dtype=np.uint8).reshape(b.height,b.width,3)
    delta = np.abs(aa.astype(np.int16)-bb.astype(np.int16)).max(axis=2)
    mask = np.ones(delta.shape,dtype=bool)
    for rect in excluded:
        # A small, per-character envelope, NOT a whole block/page exclusion.
        r = fitz.Rect(rect) + (-.75,-.75,.75,.75)
        r = r * before.rotation_matrix * fitz.Matrix(scale,scale)
        x0,y0,x1,y1 = r.irect
        mask[max(0,y0):min(a.height,y1),max(0,x0):min(a.width,x1)] = False
    values = delta[mask]
    maximum = int(values.max()) if values.size else 0
    changed = int(np.count_nonzero(values > 8))
    return {'max_channel_delta': maximum, 'pixels_above_8': changed,
            'checked_pixels': int(values.size), 'dpi':dpi}


def assert_pixels(before, after, excluded=(), reproduction=False):
    stats = pixel_diff(before, after, excluded)
    # Eight 8-bit levels allow minor decimal serialization/AA differences, but
    # no pixel may exceed this outside the individual changed glyph envelopes.
    if stats['pixels_above_8']:
        what = "La fuente no reproduce exactamente la apariencia original" if reproduction else "Se detectaron cambios visuales fuera de los caracteres editados"
        raise EditError(f"{what}: {stats['pixels_above_8']} píxeles exceden la tolerancia de 8/255 a 144 ppp.")
    return stats


def validate_transition(before_data, after_data, page_number, expected, excluded, tagged_expected=None):
    report = []
    with fitz.open(stream=before_data,filetype='pdf') as before, fitz.open(stream=after_data,filetype='pdf') as after:
        if before.page_count != after.page_count:
            raise EditError("La validación detectó un cambio en el número de páginas.")
        if before.metadata != after.metadata or before.get_xml_metadata() != after.get_xml_metadata():
            raise EditError("La validación detectó cambios ajenos en metadatos.")
        if _canonical(before.get_toc(False)) != _canonical(after.get_toc(False)):
            raise EditError("La validación detectó cambios en los marcadores.")
        for i in range(before.page_count):
            a,b = before[i],after[i]
            if (tuple(a.mediabox),tuple(a.cropbox),a.rotation) != (tuple(b.mediabox),tuple(b.cropbox),b.rotation):
                raise EditError("Se alteraron los límites o la rotación de una página.")
            if related(a) != related(b):
                raise EditError("Se alteraron imágenes, vectores, enlaces, anotaciones o campos; operación cancelada.")
            assert_characters(expected if i==page_number else trace_chars(a), b)
            report.append(assert_pixels(a,b,excluded if i==page_number else ()))
    # Independent parser proves that output is a structurally readable PDF.
    independent = PdfReader(io.BytesIO(after_data), strict=True)
    if len(independent.pages) != len(report):
        raise EditError("El lector independiente no confirma el número de páginas.")
    from .tagged import assert_structure
    assert_structure(before_data,after_data,tagged_expected)
    return {'pages':report, 'independent_parser':'pypdf', 'verified':True}
