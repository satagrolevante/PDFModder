"""Request expensive page inventories only for the tool that needs them."""
from PySide6.QtCore import QSignalBlocker,QTimer,Qt
from PySide6.QtWidgets import QApplication


class LazyPageUiV318Mixin:
    def _submit(self,command,payload=None,callback=None):
        if command in ('page','prepare_editing'):
            payload=dict(payload or {})
            # Reading/thumbnail routes already omit editing capabilities.
            payload.setdefault('lazy',True)
            if command=='page' and getattr(self.canvas,'image_mode',False):
                payload.setdefault('capabilities',('images',))
        return super()._submit(command,payload,callback)

    def _inventory_context_v318(self):
        model=getattr(self,'model',None)
        if model is None or self.application_mode!='editing':return None
        return (self.state.get('session_id',self._active_session_v200),model.revision,
                self.page_number,self.compare_action.isChecked())

    def _loaded_page(self,result):
        restore=self._restore_image_rect
        super()._loaded_page(result)
        self._inventory_view_v318=self._inventory_context_v318()
        self._inventory_ready_v318=dict(result.get('inventory_ready_v318',{'fonts':True,'images':True}))
        self._inventory_image_restore_v318=(restore if not self._inventory_ready_v318.get('images') else None)
        if self.application_mode=='editing' and self.canvas.image_mode:
            self._ensure_page_inventory_v318(('images',))

    def _ensure_page_inventory_v318(self,needs,callback=None):
        context=self._inventory_context_v318()
        if context is None:return False
        # Legacy/full page providers have already supplied their inventories.
        # Only an explicit lazy-page result opts a view into deferred loading.
        if not hasattr(self,'_inventory_view_v318'):return False
        ready=(getattr(self,'_inventory_ready_v318',{})
               if getattr(self,'_inventory_view_v318',None)==context else {})
        missing=set(needs)-{key for key,value in ready.items() if value}
        if not missing:return False
        inflight=getattr(self,'_inventory_inflight_v318',None)
        if (inflight is not None and inflight['context']==context
                and missing<=inflight['needs'] and self.busy
                and getattr(self,'_command',None)=='page_capabilities_v318'):
            if callback is not None and callback not in inflight['callbacks']:
                inflight['callbacks'].append(callback)
            return True
        request=getattr(self,'_inventory_request_v318',None)
        if request is None or request['context']!=context:
            request={'context':context,'needs':set(),'callbacks':[]}
            self._inventory_request_v318=request
        request['needs'].update(missing)
        if callback is not None and callback not in request['callbacks']:
            request['callbacks'].append(callback)
        timer=getattr(self,'_inventory_timer_v318',None)
        if timer is None:
            timer=self._inventory_timer_v318=QTimer(self)
            timer.setSingleShot(True);timer.setInterval(25)
            timer.timeout.connect(self._prepare_page_inventory_v318)
        timer.start(0)
        return True

    def _prepare_page_inventory_v318(self):
        request=getattr(self,'_inventory_request_v318',None)
        if request is None:return
        if self._closed or request['context']!=self._inventory_context_v318():
            self._inventory_request_v318=None;return
        if (self.busy or QApplication.activeModalWidget() is not None
                or getattr(self,'_placement',None)
                or getattr(self,'_rich_active',False) or getattr(self,'_rich_loading',False)
                or getattr(self.canvas,'pointer_gesture_pending',lambda:False)()):
            self._inventory_timer_v318.start();return
        # Navigation gets priority over an inventory for the departing page.
        if getattr(self,'_navigation_pending_v310',lambda:False)():
            self._inventory_timer_v318.start();return
        self._inventory_request_v318=None
        sid,revision,page,original=request['context']
        def loaded(result):
            if getattr(self,'_inventory_inflight_v318',None) is request:
                self._inventory_inflight_v318=None
            if request['context']!=self._inventory_context_v318():return
            if (result['revision'],result['number'],result['original'])!=(revision,page,original):return
            self._inventory_view_v318=request['context']
            self._inventory_ready_v318=result['inventory_ready_v318']
            if result['inventory_ready_v318'].get('fonts'):self.fonts=result['fonts']
            if result['inventory_ready_v318'].get('images'):
                restore=getattr(self,'_inventory_image_restore_v318',None)
                selected=self.canvas.selected_image()
                if restore is None and selected:restore=selected['rect']
                self.canvas.set_images(result['images'],restore)
                self._inventory_image_restore_v318=None
                self._restore_image_rect=None
                self.refresh_elements()
            for action in request['callbacks']:action()
        if not self._submit('page_capabilities_v318',{'session_id':sid,'number':page,
                'revision':revision,'original':original,'needs':sorted(request['needs']),
                '_background_ui':True},loaded):
            self._inventory_request_v318=request;self._inventory_timer_v318.start()
        else:self._inventory_inflight_v318=request

    def _choose_content_at_v150(self,event):
        # Preserve the combined text/image tool without preparing every image
        # before the first page can be shown. A first click on non-text can
        # select its image after the requested inventory is ready; it never
        # replays a mouse press, drag or mutation.
        generation=getattr(self,'_inventory_pointer_generation_v318',0)+1
        self._inventory_pointer_generation_v318=generation
        result=super()._choose_content_at_v150(event)
        canvas=self.canvas
        if (not getattr(self,'_combined_edit_v150',False) or not canvas.model or canvas.read_only
                or getattr(canvas,'signature_rectangle_mode',False)
                or canvas.editor.isVisible() or canvas.zone_mode or canvas.placement_mode
                or event.button()!=Qt.LeftButton or getattr(self,'_rich_active',False)
                or not hasattr(self,'_inventory_view_v318')):
            return result
        context=self._inventory_context_v318()
        if (self._inventory_view_v318==context
                and self._inventory_ready_v318.get('images',False)):
            return result
        point=tuple(canvas.pdf_point(event.position().toPoint()))
        hit=canvas.model.hit(point)
        if hit is not None and hit.mode!=3 and hit.opacity>0:return result
        zoom=(self.zoom,canvas.zoom)
        def select_requested_image():
            if (generation!=self._inventory_pointer_generation_v318
                    or context!=self._inventory_context_v318() or zoom!=(self.zoom,canvas.zoom)
                    or getattr(self,'_navigation_pending_v310',lambda:False)()
                    or canvas.read_only or canvas.ids or canvas.selected_image()
                    or canvas.editor.isVisible() or canvas.placement_mode or canvas.zone_mode
                    or not self._combined_edit_v150):return
            image=next((item for item in reversed(canvas.images)
                        if item['rect'][0]<=point[0]<=item['rect'][2]
                        and item['rect'][1]<=point[1]<=item['rect'][3]),None)
            if image is not None:
                with QSignalBlocker(self.image_mode_action):self.image_mode_action.setChecked(True)
                self.toggle_image_mode(True)
                canvas.select_image(image)
        if self._ensure_page_inventory_v318(('images',),select_requested_image):
            self.statusBar().showMessage('Preparando imágenes de esta página…')
        return result

    def toggle_image_mode(self,checked):
        result=super().toggle_image_mode(checked)
        if checked:self._ensure_page_inventory_v318(('images',))
        return result

    def font_inspector(self):
        if self._ensure_page_inventory_v318(('fonts',),self.font_inspector):return
        return super().font_inspector()

    def all_elements(self):
        result=super().all_elements()
        self._ensure_page_inventory_v318(('images',))
        return result

    def zone_chosen(self,rect):
        result=super().zone_chosen(rect)
        self._ensure_page_inventory_v318(('images',))
        return result

    def next_element(self):
        if self._ensure_page_inventory_v318(('images',),self.next_element):return
        return super().next_element()
