"""Virtual page lists and bounded scenes for very large document page counts."""
from PySide6.QtCore import QSize,Qt
from PySide6.QtWidgets import QApplication

from pdfmodder.continuous_reader_v180 import ContinuousReader
from pdfmodder.progressive_ui_v300 import PageListV300
from pdfmodder.page_layout_v300 import PageLayoutV300


def test_virtual_page_list_has_no_resident_item_per_pdf_page(qtbot):
    pages=PageListV300();qtbot.addWidget(pages)
    pages.setViewMode(PageListV300.IconMode);pages.setFlow(PageListV300.TopToBottom)
    pages.setWrapping(False);pages.setIconSize(QSize(100,135));pages.resize(180,500);pages.show()
    pages.set_page_count_v300(100_000);pages.setCurrentRow(0)
    QApplication.processEvents()
    assert pages.count()==100_000 and pages.item(99_999).text()=='Página 100000'
    assert pages.model().icons=={}
    assert len(pages.visible_page_numbers_v300())<8
    pages.setCurrentRow(3)
    assert pages.currentRow()==3 and pages.row(pages.selectedItems()[0])==3
    pages.clear();assert pages.count()==0


def test_progressive_reader_creates_placeholders_only_for_viewport(qtbot):
    reader=ContinuousReader();qtbot.addWidget(reader);reader.resize(500,450);reader.show()
    reader.reset_document({'page_count':10_000,'default_geometry':{'width':500.,'height':720.},
                           'geometries':{0:{'width':500.,'height':720.}}},zoom=1.)
    QApplication.processEvents()
    assert len(reader._geometries)==10_000 and reader._exact_geometries=={0}
    assert len(reader._placeholders)<6 and len(reader.scene().items())<12
    reader.go_page(9999);QApplication.processEvents()
    assert reader.current_page()==9999 and 9999 in reader._placeholders
    assert len(reader._placeholders)<6 and len(reader.scene().items())<12


def test_measured_geometry_corrects_estimate_without_losing_visible_position(qtbot):
    reader=ContinuousReader();qtbot.addWidget(reader);reader.resize(500,450);reader.show()
    reader.reset_document({'page_count':12,'default_geometry':{'width':500.,'height':720.},
                           'geometries':{0:{'width':500.,'height':720.}}},zoom=1.)
    reader.go_page(6);QApplication.processEvents()
    center=reader.mapToScene(reader.viewport().rect().center())
    relative=center.y()-reader._rects[6].top()
    reader.update_page_geometry_v300(2,720.,500.)
    center_after=reader.mapToScene(reader.viewport().rect().center())
    assert abs(center_after.y()-reader._rects[6].top()-relative)<2.
    assert reader._geometries[2]==(720.,500.) and 2 in reader._exact_geometries


def test_large_mixed_page_geometry_updates_keep_layout_index_and_measurements(qtbot,monkeypatch):
    reader=ContinuousReader();qtbot.addWidget(reader);reader.resize(500,450);reader.show()
    reader.reset_document({'page_count':100_000,'default_geometry':{'width':500.,'height':720.},
                           'geometries':{0:{'width':500.,'height':720.}}},zoom=1.)
    reader.go_page(99_999);QApplication.processEvents()
    layout=reader._rects
    monkeypatch.setattr(reader,'_layout_pages',lambda:(_ for _ in ()).throw(AssertionError('Geometry must not rebuild every page')))
    reader.update_page_geometry_v300(20,720.,500.)
    assert reader._rects is layout
    assert reader._rects[99_999].top()==20.+99_999*744.-220.
    assert reader._rects[20].width()==720. and reader._rects[20].height()==500.
    assert reader._rects.bounds.width()==760.
    assert len(reader._placeholders)<6


def test_page_position_tree_matches_mixed_size_geometry_after_updates():
    geometries=[(500.,720.),(300.,400.),(800.,200.),(600.,900.)]
    layout=PageLayoutV300(geometries,1.5,20.,24.)
    layout.update(1,(1000.,600.));layout.update(2,(400.,180.))
    top=20.
    for number,(width,height) in enumerate(geometries):
        rect=layout[number]
        assert rect.top()==top and rect.width()==width*1.5 and rect.height()==height*1.5
        assert layout.page_at_y(top)==number
        assert layout.page_at_y(rect.bottom()+5.)==number
        top=rect.bottom()+24.
    assert layout.largest_width==1500.
    layout.update(1,(300.,600.))
    assert layout.largest_width==900.


def test_real_window_shows_first_page_before_measuring_all_pages(qtbot,tmp_path):
    import pymupdf as fitz
    from pdfmodder.app import MainWindow
    source=tmp_path/'long-mixed.pdf'
    with fitz.open() as document:
        for number in range(240):
            page=document.new_page(width=500+number%7*20,height=720+number%11*10)
            page.insert_text((35,80),f'Progressive page {number+1}')
        document.save(source)
    window=MainWindow(config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    qtbot.addWidget(window,before_close_func=lambda widget:setattr(widget,'_allow_close',True))
    window.thumbnail_timer.stop();window.show()
    results=[];window.operation_finished.connect(lambda command,result:results.append((command,result)))
    try:
        assert window.open_document(source)
        qtbot.waitUntil(lambda:window.reader.model_for_page(0) is not None,timeout=30000)
        metadata=[result for command,result in results if command=='reading_info']
        assert metadata and metadata[0]['page_count']==240
        assert metadata[0]['geometry_ready_count']==1 and not metadata[0]['geometry_complete']
        assert set(metadata[0]['geometries'])=={0}
        model=window.reader.model_for_page(0)
        assert model.text([glyph.id for glyph in model.glyphs])=='Progressive page 1'
        assert window.pages.count()==240 and window.application_mode=='reading'
        assert window.document_views.currentWidget() is window.reader
        assert len(window.reader._exact_geometries)<240
        assert len(window.reader._placeholders)<6
    finally:
        window._allow_close=True;window.close()
