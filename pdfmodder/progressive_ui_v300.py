"""Progressive geometry and virtual thumbnails for file-backed PDF sessions."""
from PySide6.QtCore import QAbstractListModel,QItemSelectionModel,QModelIndex,QPoint,QSize,Qt,Signal
from PySide6.QtGui import QIcon,QPixmap
from PySide6.QtWidgets import QApplication,QListView


class _PageModelV300(QAbstractListModel):
    def __init__(self,parent=None):
        super().__init__(parent);self.count=0;self.icons={}

    def rowCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else self.count

    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<self.count:return None
        if role==Qt.DisplayRole:return f'Página {index.row()+1}'
        if role==Qt.DecorationRole:return self.icons.get(index.row(),QIcon())
        if role==Qt.SizeHintRole:return QSize(118,158)
        if role==Qt.TextAlignmentRole:return int(Qt.AlignHCenter)
        return None

    def reset_count(self,count):
        self.beginResetModel();self.count=max(0,int(count));self.icons.clear();self.endResetModel()


class _PageItemV300:
    """Short-lived compatibility proxy; pages have no resident QListWidgetItem."""
    def __init__(self,view,row):self.view=view;self.number=row
    def text(self):return f'Página {self.number+1}'
    def setIcon(self,icon):
        model=self.view._page_model_v300
        if icon.isNull():model.icons.pop(self.number,None)
        else:model.icons[self.number]=icon
        index=model.index(self.number)
        model.dataChanged.emit(index,index,[Qt.DecorationRole])
    def icon(self):return self.view._page_model_v300.icons.get(self.number,QIcon())
    def setSizeHint(self,size):pass
    def setTextAlignment(self,alignment):pass
    def isSelected(self):return self.view.selectionModel().isSelected(self.view.model().index(self.number))
    def setSelected(self,selected):
        flag=QItemSelectionModel.Select if selected else QItemSelectionModel.Deselect
        self.view.selectionModel().select(self.view.model().index(self.number),flag)


class PageListV300(QListView):
    """Virtual page rows with the small QListWidget API the existing UI uses."""
    currentRowChanged=Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._page_model_v300=_PageModelV300(self)
        self.setModel(self._page_model_v300)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched);self.setBatchSize(64)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)

    def currentChanged(self,current,previous):
        super().currentChanged(current,previous)
        self.currentRowChanged.emit(current.row())

    def count(self):return self._page_model_v300.count
    def clear(self):self._page_model_v300.reset_count(0)
    def set_page_count_v300(self,count):self._page_model_v300.reset_count(count)
    def currentRow(self):return self.currentIndex().row()
    def setCurrentRow(self,row):self.setCurrentIndex(self.model().index(row))
    def currentItem(self):return self.item(self.currentRow())
    def setCurrentItem(self,item):self.setCurrentRow(item.number)
    def item(self,row):return _PageItemV300(self,row) if 0<=row<self.count() else None
    def row(self,item):return item.number
    def selectedItems(self):return [self.item(index.row()) for index in self.selectionModel().selectedIndexes()]
    def visualItemRect(self,item):return self.visualRect(self.model().index(item.number))
    def scrollToItem(self,item,hint=QListView.EnsureVisible):self.scrollTo(self.model().index(item.number),hint)

    def addItem(self,item):
        # Older extensions may still append rows; retain compatibility without
        # keeping the Qt item or its per-page text/icon allocations.
        model=self._page_model_v300;number=model.count
        model.beginInsertRows(QModelIndex(),number,number);model.count+=1;model.endInsertRows()

    def clear_icons(self):
        model=self._page_model_v300
        if not model.icons:return
        model.icons.clear()
        if model.count:model.dataChanged.emit(model.index(0),model.index(model.count-1),[Qt.DecorationRole])

    def visible_page_numbers_v300(self):
        viewport=self.viewport().rect();found=[]
        for y in range(0,max(1,viewport.height()),32):
            for x in (min(20,viewport.width()-1),viewport.center().x()):
                index=self.indexAt(QPoint(x,y))
                if index.isValid():found.append(index.row())
        if not found:return []
        return [row for row in range(max(0,min(found)-1),min(self.count(),max(found)+2))
                if self.visualRect(self.model().index(row)).intersects(viewport)]


class ProgressiveOpeningV300Mixin:
    def _populate_pages_v300(self,count,current=0):
        blocked=self.pages.blockSignals(True)
        try:
            self.pages.set_page_count_v300(count)
            if count:self.pages.setCurrentRow(max(0,min(int(current),count-1)))
        finally:self.pages.blockSignals(blocked)

    def _sync_page_list(self):
        if not self.state:return
        count=self.state['page_count'];self.page_number=max(0,min(self.page_number,count-1))
        if self.pages.count()!=count:
            self._populate_pages_v300(count,self.page_number)
            self._thumbnail_pages.clear();self._thumbnail_order.clear()

    def _ensure_reader_v180(self):
        if not self.state or self.busy:return
        key=(self.state.get('document_revision'),bool(self.compare_action.isChecked()))
        if self._reader_key_v180==key:
            self.reader.go_page(self.page_number);return
        self._reader_generation_v180+=1;generation=self._reader_generation_v180
        self._reader_queue_v180.clear()
        self.statusBar().showMessage(f'Lectura · Preparando página {self.page_number+1} de {self.state["page_count"]}…')
        def ready(result):
            if generation!=self._reader_generation_v180 or self.application_mode!='reading':return
            self._reader_key_v180=key
            self.reader.reset_document(result,zoom=self.zoom)
            self.reader.go_page(min(self.page_number,result['page_count']-1))
            # First render is explicitly queued before viewport prefetch and
            # thumbnail work. Unvisited geometry remains an estimate.
            self._reader_queue_v180=[self.page_number]
            self._pump_reader_v180()
        self._submit('reading_info',{'original':self.compare_action.isChecked(),
                     'progressive':True,'pages':[self.page_number]},ready)

    def _load_visible_thumbnail(self):
        if self.application_mode=='reading' and (self._reader_queue_v180 or self._reader_copy_v180 or self._reader_key_v180 is None):return
        if (self.busy or not self.model or self.state.get('preview') or self._closed
            or self.canvas.editor.isVisible() or self.canvas.pointer_gesture_pending()
            or self._placement or QApplication.activeModalWidget() is not None):return
        for number in self.pages.visible_page_numbers_v300():
            if number in self._thumbnail_pages:continue
            def loaded(result):
                pixmap=QPixmap();pixmap.loadFromData(result['png'],'PNG')
                self._set_thumbnail(result['number'],pixmap)
            self._submit('page',{'number':number,'zoom':.18,'thumbnail':True,
                         'reading':True,'original':self.compare_action.isChecked()},loaded)
            break
