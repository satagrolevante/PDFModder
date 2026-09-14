"""Superficie de selección; sólo consume geometría y un PNG del proceso PDF."""
from time import monotonic

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPixmap, QKeyEvent
from PySide6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene, QPlainTextEdit

from .model import transform, transform_rect, union


class PageEditor(QPlainTextEdit):
    preview = Signal(str)
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.preview.emit(self.toPlainText())
            return
        super().keyPressEvent(event)


class PdfCanvas(QGraphicsView):
    selection_changed = Signal(object)
    move_requested = Signal(float, float)
    edit_requested = Signal()
    preview_text = Signal(str)
    cancel_requested = Signal()
    delete_requested = Signal()
    arrow_requested = Signal(int, int, bool)
    placement_clicked = Signal(float,float)
    image_selected = Signal(object)
    image_transform_requested = Signal(str,object)
    image_delete_requested = Signal(str)
    zone_selected = Signal(object)
    image_context_requested = Signal(str,object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pdfCanvas")
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#626b76"))
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.model = None
        self.zoom = 1.
        self.ids = []
        self.mode = "word"
        self.image_mode=False
        self.zone_mode=False
        self.zone_rect=None
        self._zone_start=None
        self.placement_mode=False
        self.images=[]
        self.image_id=None
        self.lock_image_ratio=True
        self._image_drag_rect=None
        self._image_resize=False
        self.read_only = False
        # A thumbnail may be rendering in the PDF process while this local
        # typing session starts. It never replaces the displayed PageModel.
        self.allow_background_edit = False
        self.show_guides = True
        self.changes = []
        self.highlight_changes = True
        self.search_rects = []
        self.overlays = []
        self._press = None
        self._press_scene = None
        self._drag = None
        self._anchor_id = None
        self._click_selection_before = None
        self._click_revision = None
        self._last_pointer_press = 0.
        self.editor = PageEditor(self.viewport())
        self.editor.setObjectName("onPageEditor")
        self.editor.setStyleSheet("QPlainTextEdit { background: #fff9da; color: #122033; border: 2px solid #0075b0; }")
        self.editor.setToolTip("Ctrl+Enter: previsualizar el PDF real · Escape: cancelar")
        self.editor.preview.connect(self.preview_text)
        self.editor.cancelled.connect(self.cancel_requested)
        self.editor.hide()
        self.horizontalScrollBar().valueChanged.connect(self._place_editor)
        self.verticalScrollBar().valueChanged.connect(self._place_editor)

    def set_page(self, png, model, zoom, changes=None):
        self.zone_rect=None
        self._zone_start=None
        self.editor.hide()
        self.scene().clear()
        self.overlays = []
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG"):
            raise ValueError("No se pudo mostrar la página renderizada.")
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.model, self.zoom = model, zoom
        self.ids = []
        self._anchor_id = None
        self._click_selection_before = None
        self._click_revision = None
        self._last_pointer_press = 0.
        self.changes = changes or []
        self._draw_overlays()
        return pixmap

    def pdf_point(self, viewport_point):
        scene = self.mapToScene(viewport_point)
        return transform((scene.x()/self.zoom, scene.y()/self.zoom), self.model.derotation_matrix)

    def viewport_point(self, pdf_point):
        x, y = transform(pdf_point, self.model.rotation_matrix)
        return self.mapFromScene(QPointF(x*self.zoom, y*self.zoom))

    def scene_rect(self, rect):
        x0, y0, x1, y1 = transform_rect(rect, self.model.rotation_matrix)
        return QRectF(x0*self.zoom, y0*self.zoom, (x1-x0)*self.zoom, (y1-y0)*self.zoom)

    def set_selection(self, ids, notify=True):
        allowed = {g.id for g in self.model.glyphs} if self.model else set()
        self.ids = sorted(set(ids) & allowed)
        if self.ids:
            self.image_id=None
            self.image_selected.emit(None)
        self._draw_overlays()
        if notify:
            self.selection_changed.emit(self.ids)

    def set_images(self,items,restore_rect=None):
        self.images=items
        self.image_id=None
        if restore_rect:
            item=next((im for im in reversed(items) if all(abs(a-b)<.06 for a,b in zip(im['rect'],restore_rect))),None)
            if item:
                self.image_id=item['id']
        self.image_selected.emit(self.selected_image())
        self._draw_overlays()

    def selected_image(self):
        return next((im for im in self.images if im['id']==self.image_id),None)

    def select_image(self,item):
        self.set_selection([])
        self.image_id=item['id'] if item else None
        self.image_selected.emit(item)
        self._draw_overlays()

    def _rect_item(self, rect, color, fill=None, dashed=False):
        pen = QPen(QColor(color), 1.)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.DashLine)
        item = self.scene().addRect(self.scene_rect(rect), pen, QBrush(QColor(fill)) if fill else QBrush(Qt.NoBrush))
        item.setZValue(2)
        self.overlays.append(item)

    def _draw_overlays(self):
        for item in self.overlays:
            self.scene().removeItem(item)
        self.overlays = []
        if not self.model:
            return
        if self.zone_rect:self._rect_item(self.zone_rect,'#aa44bb','#11aa44bb',True)
        if self.highlight_changes:
            for rect in self.changes:
                self._rect_item(rect, "#e08b00", "#22ffba30", True)
        for rect in self.search_rects:
            self._rect_item(rect, "#a88500", "#55ffdb00")
        selected = self.model.selected(self.ids)
        for glyph in selected:
            self._rect_item(glyph.bbox, "#007cc2", "#440099dd")
        if selected and self.show_guides:
            bounds = union(g.bbox for g in selected)
            self._rect_item(bounds, "#007cc2", None, True)
            r = self.scene_rect(bounds)
            pen = QPen(QColor("#55c3d5e1"), 1., Qt.DashLine)
            for x in (r.left(), r.right()):
                item = self.scene().addLine(x, 0, x, self.scene().height(), pen)
                self.overlays.append(item)
        if self._drag and selected:
            dx,dy = self._drag
            bounds = union(g.bbox for g in selected)
            moved = (bounds[0]+dx,bounds[1]+dy,bounds[2]+dx,bounds[3]+dy)
            self._rect_item(moved, "#21ba82", "#3321ba82", True)
        selected_image=self.selected_image()
        if selected_image:
            rect=self._image_drag_rect or selected_image['rect']
            self._rect_item(rect,'#007cc2',None,True)
            corner=transform((rect[2],rect[3]),self.model.rotation_matrix)
            handle=self.scene().addRect(corner[0]*self.zoom-4,corner[1]*self.zoom-4,8,8,QPen(QColor('#ffffff')),QBrush(QColor('#007cc2')))
            self.overlays.append(handle)

    def mousePressEvent(self, event):
        if self.editor.isVisible():
            # The typing session is bound to its initial selection until
            # preview/cancel. An outside click must never retarget its draft.
            event.accept()
            return
        if not self.model or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        point = self.pdf_point(event.position().toPoint())
        if self.zone_mode:
            self._zone_start=point
            self.zone_rect=(*point,*point)
            event.accept()
            return
        self._click_selection_before = self.ids[:]
        self._click_revision = self.model.revision
        self._last_pointer_press = monotonic()
        if self.placement_mode and not self.read_only:
            self.placement_clicked.emit(*point)
            event.accept()
            return
        if self.image_mode:
            self._press_scene=event.position().toPoint()
            item=self.selected_image()
            self._image_resize=False
            if item:
                handle=self.viewport_point(item['rect'][2:])
                self._image_resize=(event.position().toPoint()-handle).manhattanLength()<14
            if not self._image_resize:
                item=next((im for im in reversed(self.images) if im['rect'][0]<=point[0]<=im['rect'][2] and im['rect'][1]<=point[1]<=im['rect'][3]),None)
                self.select_image(item)
            self._press=point if item and item.get('editable') and not self.read_only else None
            self._image_drag_rect=None
            event.accept()
            return
        hit = self.model.hit(point)
        self._press_scene = event.position().toPoint()
        if not hit:
            self.set_selection([])
            self._press = None
            return
        group = self.model.group(hit, self.mode)
        if event.modifiers() & Qt.ControlModifier:
            selected = set(self.ids)
            selected.difference_update(group) if set(group).issubset(selected) else selected.update(group)
            self.set_selection(selected)
        elif event.modifiers() & Qt.ShiftModifier and self._anchor_id is not None:
            anchor = next((g for g in self.model.glyphs if g.id == self._anchor_id), None)
            # A range never silently sweeps a different extraction line/column.
            if anchor and anchor.line == hit.line and anchor.mode == hit.mode and (anchor.opacity>0)==(hit.opacity>0):
                lo,hi = sorted((anchor.id, hit.id))
                self.set_selection([g.id for g in self.model.glyphs if g.line == hit.line and g.mode == hit.mode
                                    and (g.opacity>0)==(hit.opacity>0) and lo <= g.id <= hi])
            else:
                self.set_selection(set(self.ids) | set(group))
        elif hit.id not in self.ids:
            self.set_selection(group)
            self._anchor_id = hit.id
        self._press = point if not self.read_only else None
        event.accept()

    def mouseMoveEvent(self, event):
        if self._zone_start:
            point=self.pdf_point(event.position().toPoint())
            x,y=self._zone_start
            self.zone_rect=(min(x,point[0]),min(y,point[1]),max(x,point[0]),max(y,point[1]))
            self._draw_overlays();event.accept();return
        if self.image_mode and self._press and self.selected_image():
            if (event.position().toPoint()-self._press_scene).manhattanLength()>4:
                rect=self.selected_image()['rect']
                point=self.pdf_point(event.position().toPoint())
                dx,dy=point[0]-self._press[0],point[1]-self._press[1]
                if self._image_resize:
                    width=max(1.,rect[2]-rect[0]+dx)
                    height=max(1.,rect[3]-rect[1]+dy)
                    if self.lock_image_ratio:
                        ratio=(rect[2]-rect[0])/(rect[3]-rect[1])
                        scale=max(width/(rect[2]-rect[0]),height/(rect[3]-rect[1]))
                        width=(rect[2]-rect[0])*scale
                        height=width/ratio
                    self._image_drag_rect=(rect[0],rect[1],rect[0]+width,rect[1]+height)
                else:
                    self._image_drag_rect=(rect[0]+dx,rect[1]+dy,rect[2]+dx,rect[3]+dy)
                self._draw_overlays()
            event.accept()
            return
        if self._press and self.ids and (event.position().toPoint()-self._press_scene).manhattanLength() > 4:
            point = self.pdf_point(event.position().toPoint())
            self._drag = (point[0]-self._press[0], point[1]-self._press[1])
            self._draw_overlays()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._zone_start:
            self._zone_start=None
            if self.zone_rect and self.zone_rect[2]-self.zone_rect[0]>.1 and self.zone_rect[3]-self.zone_rect[1]>.1:
                self.zone_selected.emit(self.zone_rect)
            event.accept();return
        if self.image_mode:
            rect=self._image_drag_rect
            image_id=self.image_id
            self._press=self._drag=self._image_drag_rect=None
            self._image_resize=False
            self._draw_overlays()
            if rect and image_id and not self.read_only:
                self.image_transform_requested.emit(image_id,rect)
            event.accept()
            return
        delta = self._drag
        self._press = self._drag = None
        if delta:
            self._draw_overlays()
            self.move_requested.emit(*delta)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self,event):
        if self.model and not self.editor.isVisible():
            point=self.pdf_point(event.pos())
            hits=[item for item in self.images if item['rect'][0]<=point[0]<=item['rect'][2] and item['rect'][1]<=point[1]<=item['rect'][3]]
            if hits:
                chosen=next((item for item in hits if item['id']==self.image_id),hits[-1])
                self.select_image(chosen)
                self.image_context_requested.emit(chosen['id'],event.globalPos())
                event.accept();return
        super().contextMenuEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._press = self._drag = None
        if self.editor.isVisible() or self.image_mode or self.placement_mode or self.zone_mode:
            event.accept()
            return
        if self.model and event.button() == Qt.LeftButton and (not self.read_only or self.allow_background_edit):
            point = self.pdf_point(event.position().toPoint())
            # The first press can clear a line selection when the pointer is
            # in a gap between words. Restore only a contiguous selection on
            # the same line, inside its bounds, and from this page revision.
            previous = self.ids
            if self._click_revision == self.model.revision and self.pointer_gesture_pending():
                previous = self._click_selection_before or []
            self._click_selection_before = None
            self._click_revision = None
            keep = self._coherent_selection_at(previous, point)
            hit = self.model.hit(point)
            if keep:
                if self.ids != keep:
                    self.set_selection(keep)
            elif hit:
                self.set_selection(self.model.group(hit, "word"))
                self._anchor_id = hit.id
            else:
                self.set_selection([])
            if self.ids:
                self.edit_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def pointer_gesture_pending(self):
        """Keep background scheduling out of a possible second click."""
        interval = QApplication.doubleClickInterval() / 1000.
        return self._press is not None or monotonic() - self._last_pointer_press <= interval

    def _coherent_selection_at(self, ids, point):
        selected = self.model.selected(ids)
        if not selected or len({(g.line,g.mode,g.opacity>0) for g in selected}) != 1:
            return []
        line = [g.id for g in self.model.glyphs if g.line == selected[0].line and g.mode == selected[0].mode
                and (g.opacity>0)==(selected[0].opacity>0)]
        positions = [line.index(g.id) for g in selected]
        if max(positions) - min(positions) + 1 != len(positions):
            return []
        x0,y0,x1,y1 = union(g.bbox for g in selected)
        return [g.id for g in selected] if x0 <= point[0] <= x1 and y0 <= point[1] <= y1 else []

    def start_editor(self, text):
        if not self.ids or (self.read_only and not self.allow_background_edit):
            return
        self.editor.setReadOnly(False)
        self.editor.setPlainText(text)
        selected = self.model.selected(self.ids)
        font = self.editor.font()
        font.setPointSizeF(max(8., min(36., selected[0].size)))
        self.editor.setFont(font)
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _place_editor(self):
        if self.model and self.ids:
            rect = self.scene_rect(union(g.bbox for g in self.model.selected(self.ids)))
            start = self.mapFromScene(rect.topLeft())
            width = min(max(240, int(rect.width()+28)), max(240,self.viewport().width()-16))
            height = min(max(74, int(rect.height()+35)), 250)
            x = max(4,min(start.x(),self.viewport().width()-width-4))
            y = max(4,min(start.y(),self.viewport().height()-height-4))
            self.editor.setGeometry(x,y,width,height)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._press = self._drag = None
            self._image_drag_rect=None
            self._draw_overlays()
            self.editor.hide()
            self.cancel_requested.emit()
            return
        if self.image_mode and self.image_id and not self.read_only:
            directions={Qt.Key_Left:(-1,0),Qt.Key_Right:(1,0),Qt.Key_Up:(0,-1),Qt.Key_Down:(0,1)}
            if event.key() in directions:
                self.arrow_requested.emit(*directions[event.key()],bool(event.modifiers()&Qt.ShiftModifier))
                return
            if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):
                self.image_delete_requested.emit(self.image_id)
                return
        if self.ids and not self.read_only:
            directions = {Qt.Key_Left:(-1,0),Qt.Key_Right:(1,0),Qt.Key_Up:(0,-1),Qt.Key_Down:(0,1)}
            if event.key() in directions:
                self.arrow_requested.emit(*directions[event.key()], bool(event.modifiers() & Qt.ShiftModifier))
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
                self.edit_requested.emit()
                return
            if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):
                self.delete_requested.emit()
                return
        super().keyPressEvent(event)
