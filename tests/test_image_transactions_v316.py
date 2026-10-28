"""Image speed paths retain final bytes and reject unrelated changes."""
import pymupdf as fitz
import pytest

from pdfmodder import media
from pdfmodder.image_transform_v160 import transform_image_instance_pdf
from pdfmodder.model import EditError
from test_media import picture,simple


def test_unchanged_image_pages_use_exact_graph_without_rasterization(monkeypatch):
    source=simple()
    related=media.related;pixels=media.assert_pixels
    related_pages=[];pixel_pages=[]
    def record_related(page):
        related_pages.append(page.number);return related(page)
    def record_pixels(before,after,*args,**kwargs):
        pixel_pages.append(before.number);return pixels(before,after,*args,**kwargs)
    monkeypatch.setattr(media,'related',record_related)
    monkeypatch.setattr(media,'assert_pixels',record_pixels)
    _,report=media.add_image_pdf(source,0,picture(),(40,120,200,200))
    assert report['verified']
    assert report['pages'][1]['verification']=='identical_page_graph_sha256'
    assert report['pages'][1]['rasterized'] is False
    assert related_pages==[0,0] and pixel_pages==[0]


def test_unrelated_page_vector_damage_cannot_use_unchanged_proof():
    source=simple()
    with fitz.open(stream=source,filetype='pdf') as doc:
        doc[1].draw_rect((200,200,220,220),fill=(1,0,0))
        damaged=media._write_image_transaction(doc)
    with pytest.raises(EditError,match='otra página'):
        media._validate(source,damaged,0)


def test_final_image_candidate_is_written_once_and_validated_exactly(monkeypatch):
    source=simple()
    written=[];checked=[]
    write=media._write_image_transaction;validate=media._validate
    def record_write(doc):
        result=write(doc);written.append(result);return result
    def record_validate(before,after,*args,**kwargs):
        checked.append(after);return validate(before,after,*args,**kwargs)
    monkeypatch.setattr(media,'_write_image_transaction',record_write)
    monkeypatch.setattr(media,'_validate',record_validate)
    added,report=media.add_image_pdf(source,0,picture(),(40,120,200,200))
    assert report['verified'] and written==checked==[added]


def test_modification_scans_graphics_once_and_retains_finite_destination_guard(monkeypatch):
    added,_=media.add_image_pdf(simple(),0,picture(),(40,120,200,200))
    scan=media._graphics_scan;scans=[]
    def record_scan(doc,page,infos):
        scans.append(bool(infos));return scan(doc,page,infos)
    monkeypatch.setattr(media,'_graphics_scan',record_scan)
    moved,report=transform_image_instance_pdf(added,0,'0',(170,230,330,310))
    assert report['verified'] and scans==[True]
    with pytest.raises(EditError,match='finitas'):
        transform_image_instance_pdf(moved,0,'0',(float('nan'),230,330,310))


def test_image_writer_keeps_original_streams_byte_identical():
    source=simple()
    with fitz.open(stream=source,filetype='pdf') as before:
        original_streams=[before.xref_stream_raw(x) for x in before[0].get_contents()]
    output,_=media.add_image_pdf(source,0,picture(),(40,120,200,200))
    with fitz.open(stream=output,filetype='pdf') as after:
        final_streams=[after.xref_stream_raw(x) for x in after[0].get_contents()]
    assert all(stream in final_streams for stream in original_streams)


def test_image_analysis_propagates_cooperative_cancellation(monkeypatch):
    from pdfmodder.draft_control_v305 import DraftCancelled
    def cancelled(*args):
        raise DraftCancelled('A newer edit superseded this analysis')
    monkeypatch.setattr(media,'_graphics_scan',cancelled)
    with fitz.open(stream=simple(),filetype='pdf') as doc:
        with pytest.raises(DraftCancelled):media.image_items(doc,0)
