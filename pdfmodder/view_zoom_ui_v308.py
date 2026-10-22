"""Choose the opening zoom before rendering the first PDF page."""
from math import isfinite


class ViewZoomUiV308Mixin:
    def _submit(self, command, payload=None, callback=None):
        if command == 'open':
            completed = callback

            def callback(result):
                # Only a successful open changes the default. Failed opens,
                # tab activation and recovery keep the previous view intact.
                state = result.get('state', self.state)
                self._fit_width_session_v308 = (state.get('session_id'), state.get('path'))
                if completed:
                    completed(result)

        elif command == 'reading_info':
            pending = getattr(self, '_fit_width_session_v308', None)
            if pending is not None:
                completed = callback

                def callback(result):
                    state_key = (self.state.get('session_id'), self.state.get('path'))
                    if pending == getattr(self, '_fit_width_session_v308', None) == state_key:
                        self._opening_width_v308(result)
                        self._fit_width_session_v308 = None
                    if completed:
                        completed(result)

        return super()._submit(command, payload, callback)

    def _opening_width_v308(self, result):
        geometries = result.get('geometries', {})
        geometry = geometries.get(self.page_number, geometries.get(str(self.page_number)))
        geometry = geometry or result.get('default_geometry')
        if not geometry:
            return
        width, height = float(geometry['width']), float(geometry['height'])
        if not all(isfinite(value) and value > 0 for value in (width, height)):
            return
        reader = self.reader
        viewport = reader.maximumViewportSize()
        margin = 2 * reader.MARGIN
        available_width = viewport.width() - margin
        zoom = available_width / width
        count = int(result.get('page_count', 1))
        # Geometry for unvisited pages is intentionally estimated. This uses
        # the same estimate as the reader without inspecting every PDF page.
        total_height = count * height * zoom + max(0, count - 1) * reader.GUTTER + margin
        if total_height > viewport.height():
            available_width -= reader.verticalScrollBar().sizeHint().width()
        self.zoom = max(.1, min(available_width / width, 4.))
        self._sync_zoom_control()

    def set_zoom(self, value):
        # An explicit zoom choice made while metadata is pending wins over the
        # opening default. Merely switching tabs never arms this default.
        self._fit_width_session_v308 = None
        return super().set_zoom(value)
