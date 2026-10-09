"""Graph identity skips unchanged pages without weakening change detection."""
from io import BytesIO
import zlib

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, ByteStringObject, DecodedStreamObject, DictionaryObject,
    FloatObject, NameObject, NumberObject,
    TextStringObject,
)

from pdfmodder.page_fingerprint import PageProof, _Graph


def dictionary(**items):
    return DictionaryObject({NameObject('/' + key): value for key, value in items.items()})


def numbers(*values):
    return ArrayObject([NumberObject(value) for value in values])


def corpus(*, garbage=0, compressed=False, mutate=None, inherited=False):
    writer = PdfWriter()
    for _ in range(garbage):
        writer._add_object(dictionary(Unused=TextStringObject('unreferenced')))

    objects = {}

    def stream(name, data, **items):
        result = DecodedStreamObject()
        result.set_data(data)
        result.update(dictionary(**items))
        if compressed:
            result = result.flate_encode()
        reference = writer._add_object(result)
        objects[name] = result
        return reference

    program = stream('program', b'font-program')
    font = dictionary(Type=NameObject('/Font'), Subtype=NameObject('/TrueType'),
                      BaseFont=NameObject('/ProofFont'), FirstChar=NumberObject(65),
                      LastChar=NumberObject(65), Widths=numbers(600),
                      FontDescriptor=writer._add_object(dictionary(FontFile2=program)))
    image = stream('image', b'\xff\x00\x00', Type=NameObject('/XObject'),
                   Subtype=NameObject('/Image'), Width=NumberObject(1),
                   Height=NumberObject(1), BitsPerComponent=NumberObject(8),
                   ColorSpace=NameObject('/DeviceRGB'))
    form = stream('form', b'q 1 0 0 1 0 0 cm Q', Type=NameObject('/XObject'),
                  Subtype=NameObject('/Form'), BBox=numbers(0, 0, 20, 20),
                  Resources=DictionaryObject())
    state = dictionary(Type=NameObject('/ExtGState'), ca=FloatObject(.8))
    resources = dictionary(Font=dictionary(F1=writer._add_object(font)),
                           XObject=dictionary(Im=image, Fm=form),
                           ExtGState=dictionary(GS=writer._add_object(state)),
                           ColorSpace=dictionary(CS=ArrayObject([
                               NameObject('/CalRGB'), dictionary(WhitePoint=numbers(1, 1, 1)),
                           ])))
    resource_ref = writer._add_object(resources)
    contents = stream('contents', b'BT /F1 12 Tf 10 50 Td (A) Tj ET')
    annotation = dictionary(Type=NameObject('/Annot'), Subtype=NameObject('/Square'),
                            Rect=numbers(10, 10, 20, 20), C=numbers(1, 0, 0),
                            Contents=TextStringObject('annotation'))
    parent = writer._pages.get_object()
    pages = [writer.add_blank_page(width=100, height=100) for _ in range(2)]
    for page in pages:
        page[NameObject('/Resources')] = resource_ref
        page[NameObject('/Contents')] = contents
    pages[0][NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
    if inherited:
        parent[NameObject('/Resources')] = resource_ref
        parent[NameObject('/MediaBox')] = numbers(0, 0, 100, 100)
        for page in pages:
            del page['/Resources']
            del page['/MediaBox']
    objects.update(writer=writer, font=font, state=state, resources=resources,
                   annotation=annotation, pages=pages, parent=parent)
    if mutate:
        mutate(objects)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_recompression_renumbering_and_unreferenced_objects_preserve_proof():
    original = corpus()
    rewritten = corpus(garbage=11, compressed=True)
    assert original != rewritten
    proof = PageProof(original, rewritten)
    assert proof.unchanged(0) and proof.unchanged(1)
    report = proof.report(0)
    assert report['verification'] == 'identical_page_graph_sha256'
    assert len(report['fingerprint']) == 64
    assert report['rasterized'] is False and report['pixel_measurements'] is False
    assert report['pixels_above_8'] == report['max_channel_delta'] == report['mean_channel_delta'] == 0
    assert report['verified_ink_regions'] == []


@pytest.mark.parametrize('mutation', [
    lambda o: o['program'].set_data(b'other-font-program'),
    lambda o: o['font'].__setitem__(NameObject('/Widths'), numbers(601)),
    lambda o: o['resources']['/ColorSpace']['/CS'][1].__setitem__(NameObject('/WhitePoint'), numbers(1, 2, 1)),
    lambda o: o['image'].set_data(b'\x00\xff\x00'),
    lambda o: o['form'].set_data(b'q 2 0 0 2 0 0 cm Q'),
    lambda o: o['state'].__setitem__(NameObject('/ca'), FloatObject(.7)),
    lambda o: o['contents'].set_data(b'BT /F1 12 Tf 10 50 Td (B) Tj ET'),
    lambda o: o['annotation'].__setitem__(NameObject('/Contents'), TextStringObject('changed')),
    lambda o: o['pages'][0].__setitem__(NameObject('/CropBox'), numbers(0, 0, 90, 90)),
    lambda o: o['pages'][0].__setitem__(NameObject('/Rotate'), NumberObject(90)),
    lambda o: o['pages'][0].__setitem__(NameObject('/UserUnit'), FloatObject(2)),
])
def test_every_appearance_dependency_invalidates_the_page(mutation):
    proof = PageProof(corpus(), corpus(mutate=mutation))
    assert not proof.unchanged(0)
    assert proof.report(0) == {}


def test_editing_one_page_keeps_the_other_page_provably_identical():
    def change(o):
        new = DecodedStreamObject()
        new.set_data(b'BT /F1 12 Tf 10 50 Td (B) Tj ET')
        o['pages'][0][NameObject('/Contents')] = o['writer']._add_object(new)
    proof = PageProof(corpus(), corpus(mutate=change))
    assert not proof.unchanged(0)
    assert proof.unchanged(1)


def test_lossless_writers_can_normalize_integer_valued_pdf_reals():
    def original(o):
        o['font'][NameObject('/Widths')] = ArrayObject([FloatObject(600)])
        o['pages'][0][NameObject('/MediaBox')] = ArrayObject([
            FloatObject(0), FloatObject(0), FloatObject(100), FloatObject(100),
        ])
    assert PageProof(corpus(mutate=original), corpus()).unchanged(0)


@pytest.mark.parametrize('key', ['OCProperties', 'OutputIntents', 'AcroForm'])
def test_catalog_appearance_dependencies_apply_to_every_page(key):
    def change(o):
        o['writer']._root_object[NameObject('/' + key)] = dictionary(Test=NumberObject(1))
    proof = PageProof(corpus(), corpus(mutate=change))
    assert not proof.unchanged(0) and not proof.unchanged(1)


def test_inherited_page_resources_are_resolved():
    source = corpus(inherited=True)
    assert PageProof(source, corpus(inherited=True, compressed=True, garbage=3)).unchanged(0)
    changed = corpus(inherited=True, mutate=lambda o: o['font'].__setitem__(NameObject('/Widths'), numbers(700)))
    assert not PageProof(source, changed).unchanged(0)


@pytest.mark.parametrize('key,value', [
    ('MediaBox', numbers(0, 0, 120, 120)),
    ('Resources', DictionaryObject()),
    ('UserUnit', FloatObject(2)),
    ('UnknownInheritance', ByteStringObject(b'new-value')),
])
def test_all_ancestor_values_are_part_of_the_identity_proof(key, value):
    changed = corpus(inherited=True, mutate=lambda o: o['parent'].__setitem__(NameObject('/' + key), value))
    assert not PageProof(corpus(inherited=True), changed).unchanged(0)


@pytest.mark.parametrize('kind', ['recursive_form', 'resource_cycle', 'external', 'nonascii_name'])
def test_unverifiable_graphs_fall_back_even_when_bytes_are_identical(kind):
    def change(o):
        if kind == 'recursive_form':
            form = o['resources']['/XObject'].raw_get('/Fm')
            o['form'][NameObject('/Resources')] = dictionary(XObject=dictionary(Self=form))
        elif kind == 'resource_cycle':
            resources = o['pages'][0].raw_get('/Resources')
            o['resources'][NameObject('/Cycle')] = resources
        elif kind == 'external':
            o['contents'][NameObject('/F')] = TextStringObject('external.txt')
        else:
            o['resources'][NameObject('/caf\u00e9')] = NumberObject(1)
    data = corpus(mutate=change)
    assert not PageProof(data, data).unchanged(0)


@pytest.mark.parametrize('limits', [
    {'max_nodes': 1}, {'max_depth': 1}, {'max_stream_bytes': 1},
    {'max_total_stream_bytes': 1},
])
def test_budgets_never_turn_an_incomplete_graph_into_a_proof(limits):
    data = corpus()
    assert not PageProof(data, data, **limits).unchanged(0)


def test_malformed_input_invalid_indices_and_page_count_fall_back():
    data = corpus()
    assert not PageProof(b'broken', data).unchanged(0)
    proof = PageProof(data, data)
    for index in (-1, 2, True, '0'):
        assert not proof.unchanged(index)
    with fitz.open(stream=data, filetype='pdf') as document:
        document.delete_page(1)
        assert not PageProof(data, document.tobytes()).unchanged(0)


def test_shared_font_and_stream_resources_are_hashed_once_per_reader(monkeypatch):
    calls = []
    original = _Graph._decoded
    def counted(graph, data, filters):
        calls.append((id(graph), data))
        return original(graph, data, filters)
    monkeypatch.setattr(_Graph, '_decoded', counted)
    data = corpus(compressed=True)
    proof = PageProof(data, data)
    assert proof.unchanged(0)
    first_count = len(calls)
    assert proof.unchanged(1)
    assert len(calls) == first_count
    # A new transition owns independent readers and must inspect resources anew.
    assert PageProof(data, data).unchanged(0)
    assert len(calls) == 2 * first_count


def test_opaque_image_decode_parameters_are_not_discarded():
    def build(transform):
        def change(o):
            image = o['image']
            image[NameObject('/Filter')] = NameObject('/DCTDecode')
            image[NameObject('/DecodeParms')] = dictionary(ColorTransform=NumberObject(transform))
        return corpus(mutate=change)
    first = build(0)
    assert PageProof(first, first).unchanged(0)
    assert not PageProof(first, build(1)).unchanged(0)


def test_broken_flate_never_uses_decoder_recovery_as_identity():
    def change(o):
        stream = o['contents']
        stream[NameObject('/Filter')] = NameObject('/FlateDecode')
        stream._data = zlib.compress(b'BT (A) Tj ET')[:-3]
    data = corpus(mutate=change)
    assert not PageProof(data, data).unchanged(0)


def png_xref(data, *, truncated=False):
    """Generated incremental xref uses the same Predictor12 as the supplied PDF."""
    reader = PdfReader(BytesIO(data), strict=True)
    number = int(reader.trailer['/Size'])
    root = reader.trailer.raw_get('/Root')
    entries = [b'\x00' + b'\x00' * 4 + b'\xff\xff']
    for index in range(1, number):
        entries.append(b'\x01' + reader.xref[0][index].to_bytes(4, 'big') + b'\x00\x00')
    entries.append(b'\x01' + len(data).to_bytes(4, 'big') + b'\x00\x00')
    previous = bytes(7)
    encoded = bytearray()
    for entry in entries:
        encoded.extend(b'\x02' + bytes((byte - old) % 256 for byte, old in zip(entry, previous)))
        previous = entry
    if truncated:
        encoded.pop()
    compressed = zlib.compress(encoded)
    header = (f'{number} 0 obj\n<< /Type /XRef /Size {number + 1} /W [1 4 2] '
              f'/Root {root.idnum} {root.generation} R /Filter /FlateDecode '
              f'/DecodeParms << /Columns 7 /Predictor 12 >> /Length {len(compressed)} >>\nstream\n')
    return (data + header.encode('ascii') + compressed + b'\nendstream\nendobj\nstartxref\n'
            + str(len(data)).encode('ascii') + b'\n%%EOF\n')


def test_strict_png_prediction_xref_preserves_identity():
    original = corpus()
    proof = PageProof(original, png_xref(original))
    assert proof.unchanged(0) and proof.unchanged(1)


def test_incomplete_png_prediction_xref_cannot_be_repaired_into_a_proof():
    malformed = png_xref(corpus(), truncated=True)
    assert not PageProof(malformed, malformed).unchanged(0)
