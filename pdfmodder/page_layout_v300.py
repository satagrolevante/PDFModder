"""Page positions with logarithmic corrections when estimated sizes arrive."""
from collections import Counter
from heapq import heapify, heappop, heappush

from PySide6.QtCore import QRectF


class PageLayoutV300:
    """Keep heights, not a resident QRectF and scene item for every page.

    A prefix-sum tree lets a newly measured mixed-size page move the following
    pages without rebuilding their rectangles. Only visible rectangles and
    the few cached images are materialised by the reader.
    """
    def __init__(self,geometries,zoom,margin,gutter):
        self.geometries=geometries
        self.zoom=float(zoom);self.margin=float(margin);self.gutter=float(gutter)
        self._tree=[0.]+[height*self.zoom+self.gutter for _,height in geometries]
        for index in range(1,len(self._tree)):
            parent=index+(index & -index)
            if parent<len(self._tree):self._tree[parent]+=self._tree[index]
        self._widths=Counter(width for width,_ in geometries)
        self._width_heap=[-width for width in self._widths]
        heapify(self._width_heap)

    def __len__(self):return len(self.geometries)

    def _prefix(self,count):
        value=0.
        while count:
            value+=self._tree[count];count-=count & -count
        return value

    def top(self,number):return self.margin+self._prefix(number)

    @property
    def largest_width(self):
        while self._width_heap and not self._widths[-self._width_heap[0]]:heappop(self._width_heap)
        return -self._width_heap[0]*self.zoom if self._width_heap else 0.

    @property
    def bounds(self):
        return QRectF(0.,0.,self.largest_width+2*self.margin,
                      max(0.,self._prefix(len(self))+2*self.margin-self.gutter))

    def __getitem__(self,number):
        if isinstance(number,slice):return [self[index] for index in range(*number.indices(len(self)))]
        if number<0:number+=len(self)
        if not 0<=number<len(self):raise IndexError(number)
        width,height=self.geometries[number]
        return QRectF(self.margin+(self.largest_width-width*self.zoom)/2.,self.top(number),
                      width*self.zoom,height*self.zoom)

    def page_at_y(self,y):
        """Index of the last page top at or before y, including page gaps."""
        distance=float(y)-self.margin
        if distance<0:return -1
        count=0;prefix=0.
        bit=1<<(len(self).bit_length()-1) if self else 0
        while bit:
            candidate=count+bit
            if candidate<=len(self) and prefix+self._tree[candidate]<=distance:
                count=candidate;prefix+=self._tree[candidate]
            bit>>=1
        return min(count,len(self)-1)

    def update(self,number,geometry):
        old_width,old_height=self.geometries[number]
        width,height=geometry
        self.geometries[number]=geometry
        delta=(height-old_height)*self.zoom
        index=number+1
        while index<len(self._tree):
            self._tree[index]+=delta;index+=index & -index
        if width!=old_width:
            self._widths[old_width]-=1
            self._widths[width]+=1
            heappush(self._width_heap,-width)


class PageTopsV300:
    """Sequence compatibility for extensions inspecting reader page tops."""
    def __init__(self,layout):self.layout=layout
    def __len__(self):return len(self.layout)
    def __getitem__(self,index):
        if isinstance(index,slice):return [self.layout.top(i) for i in range(*index.indices(len(self)))]
        if index<0:index+=len(self)
        if not 0<=index<len(self):raise IndexError(index)
        return self.layout.top(index)
