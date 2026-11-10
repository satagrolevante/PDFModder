"""Whole-page operations retain exact output intent and decoded ICC graphs."""
from io import BytesIO

from PIL import ImageCms
import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from pdfmodder.model import EditError
from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, merge_pdfs, organize_pages_pdf, _semantic
from pdfmodder.tagged_pages import page_capabilities
from test_pageops import fixture_pdf


ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def with_profile(data, *, identifier='sRGB', profile=ICC):
    reader = PdfReader(BytesIO(data))
    writer = PdfWriter(clone_from=reader)
    writer.pdf_header = max(reader.pdf_header,'%PDF-1.4')
    stream = DecodedStreamObject(); stream.set_data(profile)
    stream[NameObject('/N')] = NumberObject(3)
    intent = DictionaryObject({NameObject('/Type'):NameObject('/OutputIntent'),
        NameObject('/S'):NameObject('/GTS_PDFA1'),
        NameObject('/Info'):TextStringObject('sRGB IEC61966-2.1'),
        NameObject('/OutputConditionIdentifier'):TextStringObject(identifier),
        NameObject('/DestOutputProfile'):writer._add_object(stream)})
    writer.root_object[NameObject('/OutputIntents')] = ArrayObject([writer._add_object(intent)])
    out = BytesIO(); writer.write(out)
    return out.getvalue()


def assert_profile(source, output):
    roots = [PdfReader(BytesIO(b), strict=True).trailer['/Root'] for b in (source, output)]
    assert _semantic(roots[0]['/OutputIntents'], exact_numbers=True) == _semantic(roots[1]['/OutputIntents'], exact_numbers=True)
    assert roots[1]['/OutputIntents'][0].get_object()['/DestOutputProfile'].get_data() == ICC


def assert_pages(source, output, retained):
    assert_profile(source, output)
    with fitz.open(stream=source, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        assert len(after) == len(retained)
        assert before.metadata == after.metadata
        assert PdfReader(BytesIO(output)).pdf_header >= PdfReader(BytesIO(source)).pdf_header
        assert before.get_xml_metadata() == after.get_xml_metadata()
        for new, old in enumerate(retained):
            assert before[old].read_contents() == after[new].read_contents()
            assert before[old].get_texttrace() == after[new].get_texttrace()
            assert before[old].get_pixmap(matrix=fitz.Matrix(2,2)).samples == after[new].get_pixmap(matrix=fitz.Matrix(2,2)).samples


@pytest.mark.parametrize('operation,pages,retained', [
    (delete_pages_pdf,[0],[1,2]), (delete_pages_pdf,[1],[0,2]),
    (delete_pages_pdf,[2],[0,1]), (delete_pages_pdf,[0,2],[1]),
    (extract_pages_pdf,[2,0],[2,0]),
])
def test_select_pages_preserves_color_content_and_appearance(operation, pages, retained):
    source = with_profile(fixture_pdf(links=False))
    output, report = operation(source, pages)
    assert report['verified'] and page_capabilities(source)['delete']
    assert_pages(source, output, retained)


def test_reorder_uses_the_same_profile():
    source = with_profile(fixture_pdf(links=False))
    output, report = organize_pages_pdf(source, [dict(source='current',page=p) for p in (2,0,1)])
    assert report['verified']
    assert_pages(source, output, [2,0,1])


def test_tagged_page_writer_preserves_output_profile_and_accessibility():
    from tagged_corpus import make_tagged_pdf, audit_tagged
    source = with_profile(make_tagged_pdf())
    output, report = delete_pages_pdf(source, [1])
    assert report['verified'] and audit_tagged(output)
    assert_pages(source, output, [0])


@pytest.mark.parametrize('organizer', [False,True])
@pytest.mark.parametrize('change', ['drop','icc','identifier'])
def test_candidate_with_lost_or_changed_output_profile_is_rejected(monkeypatch, organizer, change):
    import pdfmodder.pageops as ops
    source = with_profile(fixture_pdf(links=False))
    name = '_build_organized' if organizer else '_build_pdf'
    build = getattr(ops,name)
    def corrupted(*args, **kwargs):
        candidate = build(*args, **kwargs)
        with fitz.open(stream=candidate, filetype='pdf') as doc:
            if change=='drop':
                doc.xref_set_key(doc.pdf_catalog(),'OutputIntents','null')
            else:
                reader = PdfReader(BytesIO(candidate))
                intent = reader.trailer['/Root']['/OutputIntents'][0]
                if change=='identifier':
                    doc.xref_set_key(intent.idnum,'OutputConditionIdentifier','(Changed)')
                else:
                    profile = intent.get_object().raw_get('/DestOutputProfile')
                    changed = bytearray(ICC); changed[-1] ^= 1
                    doc.update_stream(profile.idnum,bytes(changed))
            return doc.tobytes(garbage=2)
    monkeypatch.setattr(ops,name,corrupted)
    with pytest.raises(EditError, match='color|catálogo'):
        if organizer:
            organize_pages_pdf(source, [dict(source='current',page=1)])
        else:
            delete_pages_pdf(source, [0])


@pytest.mark.parametrize('organizer', [False,True])
def test_importing_identical_profiles_is_allowed(organizer):
    source = with_profile(fixture_pdf(links=False,count=1))
    addition = with_profile(fixture_pdf(prefix='OTHER',links=False,count=1))
    if organizer:
        output, report = organize_pages_pdf(source,[dict(source='other',page=0),dict(source='current',page=0)],{'other':addition})
    else:
        output, report = merge_pdfs(source,[addition])
    assert report['verified']
    assert_profile(source,output)


@pytest.mark.parametrize('difference', ['identifier','icc','missing_current','missing_added'])
def test_different_imported_profiles_are_not_silently_dropped(difference):
    plain = fixture_pdf(links=False,count=1)
    source = plain if difference=='missing_current' else with_profile(plain)
    if difference=='missing_added':
        addition = plain
    elif difference=='icc':
        addition = with_profile(plain,profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes())
    else:
        addition = with_profile(plain,identifier='Different' if difference=='identifier' else 'sRGB')
    with pytest.raises(EditError, match='perfiles de color'):
        merge_pdfs(source,[addition])
    # Even replacing every current page retains the current catalog and must
    # not reassign another document's page to that output condition.
    with pytest.raises(EditError, match='perfiles de color'):
        organize_pages_pdf(source,[dict(source='other',page=0)],{'other':addition})
