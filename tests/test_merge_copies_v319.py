"""Consultation copies retain page content while explicitly retiring active features."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, ByteStringObject, DecodedStreamObject, DictionaryObject,
    IndirectObject, NameObject, NumberObject, TextStringObject,
)
import pytest

from pdfmodder.model import EditError
from pdfmodder.pageops import merge_pdfs
from tagged_corpus import DATE_TEXT, dictionary, make_tagged_pdf


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def ordinary_pdf(label='BASE'):
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=420)
        page.insert_text((45, 65), label + ' texto conservado', fontsize=12)
        page.draw_rect((40, 100, 300, 170), color=(.2, .4, .7), fill=(.8, .9, 1))
        page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(40, 200, 150, 220),
                          'uri': 'https://example.org/' + label})
        page.add_text_annot((330, 180), 'Nota conservada ' + label)
        doc.set_metadata({'title': 'Titulo ' + label, 'author': 'Autor conservado'})
        doc.set_xml_metadata('<?xml version="1.0"?><custom>' + label + '</custom>')
        doc.set_toc([[1, 'Marcador ' + label, 1]])
        payload = doc.tobytes()
    writer = PdfWriter(clone_from=PdfReader(BytesIO(payload)))
    writer.add_metadata({'/CustomRecord': 'Registro propio ' + label})
    return serialize(writer)


def serialize(writer):
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def widget_pdf(*, signed=False, appearance=True):
    with fitz.open(stream=ordinary_pdf('FIRMA' if signed else 'FORMULARIO')) as doc:
        widget = fitz.Widget()
        widget.field_name = 'Firma visible' if signed else 'Dato'
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = 'Firma visible conservada' if signed else 'Valor conservado'
        widget.rect = fitz.Rect(40, 260, 300, 300)
        doc[0].add_widget(widget)
        source = doc.tobytes()
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    if signed:
        form = writer.root_object['/AcroForm']
        field = form['/Fields'][0].get_object()
        field[NameObject('/FT')] = NameObject('/Sig')
        signature = writer._add_object(dictionary(
            Type=NameObject('/Sig'), Filter=NameObject('/Adobe.PPKLite'),
            SubFilter=NameObject('/adbe.pkcs7.detached'),
            ByteRange=ArrayObject([NumberObject(0), NumberObject(1), NumberObject(2), NumberObject(3)]),
            Contents=ByteStringObject(b'fixture signature value')))
        field[NameObject('/V')] = signature
        form[NameObject('/SigFlags')] = NumberObject(3)
        writer.root_object[NameObject('/Perms')] = dictionary(DocMDP=signature)
        writer.root_object[NameObject('/DSS')] = dictionary(VRI=DictionaryObject())
        if not appearance:
            field.pop(NameObject('/AP'), None)
    return serialize(writer)


def nodes(root):
    pending, seen = [root], set()
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if not isinstance(value, (dict, list, tuple)) or id(value) in seen:
            continue
        seen.add(id(value))
        yield value
        pending.extend(value.values() if isinstance(value, dict) else value)


def assert_source_pages(source, output, offset=0):
    with fitz.open(stream=source) as before, fitz.open(stream=output) as after:
        for index, original in enumerate(before):
            copied = after[offset + index]
            assert original.get_text() == copied.get_text()
            assert (original.mediabox, original.cropbox, original.rotation) == (
                copied.mediabox, copied.cropbox, copied.rotation)
            assert original.get_pixmap(matrix=fitz.Matrix(2, 2)).samples == copied.get_pixmap(matrix=fitz.Matrix(2, 2)).samples
            assert [link.get('uri') for link in original.get_links()] == [link.get('uri') for link in copied.get_links()]


@pytest.mark.parametrize('source', [
    pytest.param(lambda: widget_pdf(signed=True), id='signed'),
    pytest.param(lambda: widget_pdf(), id='form'),
    pytest.param(lambda: make_tagged_pdf(), id='tagged'),
])
def test_strict_default_still_blocks_special_sources(source):
    payload = source()
    with pytest.raises(EditError):
        merge_pdfs(ordinary_pdf(), [payload])


def test_consultation_copy_retires_signatures_but_keeps_visible_appearance():
    signed, addition = widget_pdf(signed=True), ordinary_pdf('ANEXO')
    digests = [sha256(payload).hexdigest() for payload in (signed, addition)]
    output, report = merge_pdfs(signed, [addition], as_copy=True)
    assert_source_pages(signed, output)
    assert_source_pages(addition, output, 1)
    assert [sha256(payload).hexdigest() for payload in (signed, addition)] == digests
    assert report['original_source_sha256'] == digests
    assert report['result_unsigned'] and report['warning']
    assert report['transformed_sources'][0]['index'] == 0
    assert report['transformed_sources'][0]['signed']
    reader = PdfReader(BytesIO(output), strict=True)
    root = reader.trailer['/Root']
    assert not any(key in root for key in ('/Perms', '/DSS'))
    assert not reader.get_fields()
    assert not any(isinstance(node, dict) and
                   (node.get('/Type') == '/Sig' or node.get('/FT') == '/Sig' or '/SigFlags' in node)
                   for node in nodes(root))
    assert reader.metadata['/CustomRecord'] == 'Registro propio FIRMA'
    with fitz.open(stream=output) as doc:
        assert not doc.is_form_pdf and doc.get_sigflags() < 1
        assert doc.get_xml_metadata() == '<?xml version="1.0"?><custom>FIRMA</custom>'
        assert doc.get_toc() == [[1, 'Marcador FIRMA', 1], [1, 'Marcador ANEXO', 2]]


def test_consultation_copy_flattens_ordinary_form_without_rasterizing():
    base, form = ordinary_pdf(), widget_pdf()
    output, report = merge_pdfs(base, [form], as_copy=True)
    assert_source_pages(form, output, 1)
    assert report['transformed_sources'][0]['index'] == 1
    assert report['transformed_sources'][0]['fields']
    with fitz.open(stream=output) as result:
        assert not result.is_form_pdf
        assert 'Valor conservado' in result[1].get_text()
        assert result[1].get_drawings() and not result[1].get_images()


@pytest.mark.parametrize('named_properties', [False, True])
def test_tagged_copy_keeps_actualtext_images_links_and_custom_metadata(named_properties):
    tagged = make_tagged_pdf(named_properties=named_properties, actual_text=DATE_TEXT,
                             actual_on='content', include_objr=True)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(tagged)))
    writer.add_metadata({'/CustomRecord': 'Registro etiquetado conservado'})
    xmp = DecodedStreamObject()
    xmp.set_data(b'<?xml version="1.0"?><custom>Conservar XMP</custom>')
    xmp.update(dictionary(Type=NameObject('/Metadata'), Subtype=NameObject('/XML')))
    writer.root_object[NameObject('/Metadata')] = writer._add_object(xmp)
    tagged = serialize(writer)
    output, report = merge_pdfs(tagged, [ordinary_pdf('ANEXO')], as_copy=True)
    assert_source_pages(tagged, output)
    reader = PdfReader(BytesIO(output), strict=True)
    assert '/StructTreeRoot' not in reader.trailer['/Root']
    assert '/MarkInfo' not in reader.trailer['/Root']
    assert reader.metadata['/CustomRecord'] == 'Registro etiquetado conservado'
    assert report['transformed_sources'][0]['tagged']
    assert report['warning']
    assert all(not any(key in node for key in ('/StructParents', '/StructParent', '/ObjectStructParent'))
               for node in nodes(reader.trailer['/Root']) if isinstance(node, dict))
    source_reader = PdfReader(BytesIO(tagged), strict=True)
    assert source_reader.pages[0].get_contents().get_data() == reader.pages[0].get_contents().get_data()
    assert source_reader.pages[0].extract_text() == reader.pages[0].extract_text()
    with fitz.open(stream=output) as doc:
        assert doc.get_xml_metadata() == '<?xml version="1.0"?><custom>Conservar XMP</custom>'
        assert len(doc[0].get_images()) == 1 and doc[1].get_drawings()


def test_ordinary_copy_merge_does_not_transform_sources_and_keeps_metadata():
    base, addition = ordinary_pdf(), ordinary_pdf('ANEXO')
    output, report = merge_pdfs(base, [addition], as_copy=True)
    assert report['transformed_sources'] == []
    assert_source_pages(base, output)
    assert_source_pages(addition, output, 1)
    assert PdfReader(BytesIO(output)).metadata['/CustomRecord'] == 'Registro propio BASE'


def test_tagged_copy_keeps_optional_layer_visibility_and_identity():
    with fitz.open(stream=make_tagged_pdf(actual_text=DATE_TEXT, actual_on='content')) as doc:
        layer = doc.add_ocg('Capa conservada', on=False)
        doc[0].insert_text((48, 380), 'Texto oculto de capa', oc=layer)
        source = doc.tobytes()
    output, _ = merge_pdfs(source, [ordinary_pdf('ANEXO')], as_copy=True)
    assert_source_pages(source, output)
    with fitz.open(stream=output) as result:
        assert [layer['name'] for layer in result.get_ocgs().values()] == ['Capa conservada']
        assert not next(iter(result.get_ocgs().values()))['on']


def test_tagged_copy_removes_obsolete_pdfua_claim_and_keeps_other_xmp():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    xmp = DecodedStreamObject()
    xmp.set_data(b'<?xml version="1.0"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
                 b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                 b'<rdf:Description rdf:about="" xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/" '
                 b'xmlns:custom="urn:pdfmodder:test" pdfuaid:part="1" custom:record="Conservar"/>'
                 b'</rdf:RDF></x:xmpmeta>')
    xmp.update(dictionary(Type=NameObject('/Metadata'), Subtype=NameObject('/XML')))
    writer.root_object[NameObject('/Metadata')] = writer._add_object(xmp)
    output, report = merge_pdfs(serialize(writer), [ordinary_pdf('ANEXO')], as_copy=True)
    with fitz.open(stream=output) as result:
        xml = result.get_xml_metadata()
        assert 'Conservar' in xml
        assert 'pdfuaid:part' not in xml
    assert report['warning']


@pytest.mark.parametrize('kind', ['XFA', 'JavaScript', 'missing_signature_appearance'])
def test_unsafe_copy_sources_fail_with_concrete_reason(kind):
    source = widget_pdf(signed=kind == 'missing_signature_appearance', appearance=False)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    if kind == 'XFA':
        writer.root_object['/AcroForm'][NameObject('/XFA')] = TextStringObject('<xfa/>')
    elif kind == 'JavaScript':
        writer.root_object[NameObject('/OpenAction')] = dictionary(
            S=NameObject('/JavaScript'), JS=TextStringObject('app.alert("fixture")'))
    source = serialize(writer)
    digest = sha256(source).digest()
    pattern = {'XFA': 'XFA', 'JavaScript': 'JavaScript|script|acción',
               'missing_signature_appearance': 'apariencia|apariencias'}[kind]
    with pytest.raises(EditError, match=pattern):
        merge_pdfs(ordinary_pdf(), [source], as_copy=True)
    assert sha256(source).digest() == digest


@pytest.mark.parametrize('filename', ['encrypted.pdf', 'restricted.pdf'])
def test_consultation_copy_does_not_bypass_encryption_or_permissions(filename):
    with pytest.raises(EditError, match='cifrad|permiso|contraseña'):
        merge_pdfs(ordinary_pdf(), [(EXAMPLES / filename).read_bytes()], as_copy=True)


def test_duplicate_sources_report_original_hash_and_all_input_indices():
    base, signed = ordinary_pdf(), widget_pdf(signed=True)
    output, report = merge_pdfs(base, [signed, signed], as_copy=True)
    digest = sha256(signed).hexdigest()
    assert report['duplicate_sources'] == [{'sha256': digest, 'indices': [1, 2]}]
    assert report['original_source_sha256'] == [sha256(base).hexdigest(), digest, digest]
    assert [source['index'] for source in report['transformed_sources']] == [1, 2]
    assert_source_pages(signed, output, 1)
    assert_source_pages(signed, output, 2)


@pytest.mark.parametrize('loss', ['custom_info', 'link', 'signature_appearance', 'invisible_text'])
def test_preparation_serialization_losses_are_detected(monkeypatch, loss):
    source, addition = widget_pdf(signed=True), ordinary_pdf('ANEXO')
    original_write = PdfWriter.write
    with fitz.open(stream=source) as doc:
        original_content = doc[0].read_contents()
    injected = False

    def damaged_write(writer, stream):
        nonlocal injected
        if loss == 'custom_info':
            writer._info.pop(NameObject('/CustomRecord'), None)
        elif loss == 'invisible_text' and not injected:
            # A text change can render identically: complete text validation
            # must still reject material injected during widget preparation.
            injected = True
            page = writer.pages[0]
            content = DecodedStreamObject()
            content.set_data(original_content +
                             b'\nq BT /helv 12 Tf 3 Tr 1 0 0 1 40 20 Tm '
                             b'(UNEXPECTED HIDDEN TEXT) Tj ET Q\n')
            page[NameObject('/Contents')] = writer._add_object(content)
        else:
            for page in writer.pages:
                for ref in page.get('/Annots', []):
                    annotation = ref.get_object()
                    if loss == 'link' and annotation.get('/Subtype') == '/Link':
                        annotation['/A'][NameObject('/URI')] = TextStringObject('https://example.org/CORRUPTED')
                    elif loss == 'signature_appearance' and annotation.get('/FT') == '/Sig':
                        annotation.pop(NameObject('/AP'), None)
        return original_write(writer, stream)

    monkeypatch.setattr(PdfWriter, 'write', damaged_write)
    with pytest.raises(EditError):
        merge_pdfs(source, [addition], as_copy=True)


def test_tagged_copy_preserves_complex_indirect_info_graph():
    from test_untag_v180 import metadata_fixture

    source = metadata_fixture()
    output, _ = merge_pdfs(source, [ordinary_pdf('ANEXO')], as_copy=True)
    reader = PdfReader(BytesIO(output), strict=True)
    info = reader.trailer['/Info']
    assert info['/CustomRecord'] == 'Metadatos propios, ñ'
    assert info['/CustomIndirect'] == 'Valor indirecto conservado'
    assert info['/CustomNested']['/Label'] == 'Dato propio'
    assert info['/CustomNested']['/Enabled'].value is True
    assert list(info['/CustomNested']['/Values']) == [7, 'siete']
    assert info['/CustomNested'].raw_get('/OwnerInfo') == reader.trailer.raw_get('/Info')
    assert reader.trailer['/Root']['/Metadata']['/CustomFlag'] == 'Conservar atributo'
    assert_source_pages(source, output)


def test_tagged_copy_removes_associations_in_direct_and_xobject_resources():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(include_objr=True))))
    resources = writer.pages[0]['/Resources']
    resources[NameObject('/DirectProperty')] = dictionary(StructParents=NumberObject(12))
    form = DecodedStreamObject()
    form.set_data(b'0 0 10 10 re S')
    form.update(dictionary(Type=NameObject('/XObject'), Subtype=NameObject('/Form'),
                           BBox=ArrayObject([NumberObject(0), NumberObject(0),
                                             NumberObject(10), NumberObject(10)]),
                           Resources=dictionary(), StructParents=NumberObject(13)))
    resources['/XObject'][NameObject('/FormFixture')] = writer._add_object(form)
    source = serialize(writer)
    output, _ = merge_pdfs(source, [ordinary_pdf('ANEXO')], as_copy=True)
    resources = PdfReader(BytesIO(output)).pages[0]['/Resources']
    assert '/StructParents' not in resources['/DirectProperty']
    assert '/StructParents' not in resources['/XObject']['/FormFixture']
    assert_source_pages(source, output)


@pytest.mark.parametrize('layered_base', [False, True])
def test_addition_layers_retain_each_source_default_visibility(layered_base):
    def layered(label, enabled):
        with fitz.open(stream=ordinary_pdf(label)) as doc:
            group = doc.add_ocg('Capa ' + label, on=enabled)
            doc[0].insert_text((45, 380), 'Contenido de capa ' + label, oc=group)
            return doc.tobytes()

    base = layered('BASE', True) if layered_base else ordinary_pdf()
    hidden, visible = layered('OCULTA', False), layered('VISIBLE', True)
    output, report = merge_pdfs(base, [hidden, visible], as_copy=True)
    assert report['transformed_sources'] == []
    assert_source_pages(base, output)
    assert_source_pages(hidden, output, 1)
    assert_source_pages(visible, output, 2)
    with fitz.open(stream=output) as result:
        assert {layer['name']: layer['on'] for layer in result.get_ocgs().values()} == {
            **({'Capa BASE': True} if layered_base else {}),
            'Capa OCULTA': False, 'Capa VISIBLE': True,
        }
