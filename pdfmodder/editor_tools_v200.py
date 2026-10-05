"""Selection preflight, explicitly bounded cells and paged printing.

Only the dedicated PDF process uses MuPDF here. Qt receives paths/pixels and
serializable models, never a live Document. Print preparation uses disk rather
than retaining all full-size pages in memory.
"""
from pathlib import Path
import hashlib
import tempfile
import math

import pymupdf as fitz
from .model import EditError, union


def install_editor_tools_v200(Session):
    def selection_capabilities_v200(self, page, ids, revision=None, new_text=None):
        data=self.history.current
        if revision and revision != hashlib.sha256(data).hexdigest():
            raise EditError('La selección cambió. Selecciona el texto de nuevo.')
        from .compatibility_v200 import preflight_text
        return preflight_text(data,page,ids,new_text,self.resolver)

    def cell_selection_v200(self, page, rect, padding=2., alignment='left', revision=None):
        self._writable()
        data=self.history.current
        if revision and revision != hashlib.sha256(data).hexdigest():
            raise EditError('La selección pertenece a una revisión anterior.')
        from .engine import extract_page
        values=tuple(float(v) for v in rect)
        margin=float(padding)
        if len(values)!=4 or not all(math.isfinite(v) for v in values) or not math.isfinite(margin) or margin<0:
            raise EditError('El área o los márgenes de la celda no son válidos.')
        x0,y0,x1,y1=values
        inner=(x0+margin,y0+margin,x1-margin,y1-margin)
        if inner[2]<=inner[0] or inner[3]<=inner[1]:
            raise EditError('Los márgenes dejan la celda sin espacio disponible.')
        if alignment not in ('left','center','right','justify'):
            raise EditError('Elige una alineación compatible para la celda.')
        with self._open(data) as doc:
            p=doc[page]
            if not fitz.Rect(0,0,p.cropbox.width,p.cropbox.height).contains(fitz.Rect(values)):
                raise EditError('La celda debe estar dentro de la página.')
            model=extract_page(doc,page,data)
        selected=[]
        for glyph in model.glyphs:
            if glyph.mode==3 or glyph.opacity<=0:
                continue
            b=glyph.bbox
            if x0<=((b[0]+b[2])/2)<=x1 and y0<=((b[1]+b[3])/2)<=y1:
                if not fitz.Rect(values).contains(fitz.Rect(b)):
                    raise EditError('El borde corta caracteres. Amplía el área para incluirlos completos.')
                selected.append(glyph)
        if not selected:
            raise EditError('No hay texto visible dentro del área elegida.')
        payload=self.rich_selection(page,[g.id for g in selected])
        payload.update(rect=list(inner),width=inner[2]-inner[0],height=inner[3]-inner[1],
                       auto_width=False,auto_height=False,allow_overlap=False)
        paragraphs=payload.get('paragraphs') or [{'index':0}]
        payload['paragraphs']=[dict(p,alignment=alignment) for p in paragraphs]
        return {'payload':payload,'cell_rect':list(values),'padding':margin,
                'text':model.text([g.id for g in selected]),'ids':[g.id for g in selected],
                'state':self.state()}

    def print_pages_v200(self, pages=None, dpi=300):
        if self.pending is not None:
            raise EditError('Acepta o cancela la vista previa antes de imprimir.')
        dpi=int(dpi)
        if not 72<=dpi<=600:
            raise EditError('La resolución de impresión debe estar entre 72 y 600 ppp.')
        data=self.history.current
        old=getattr(self,'_print_folder_v200',None)
        if old:old.cleanup()
        folder=tempfile.TemporaryDirectory(prefix='pdfmodder-print-')
        self._print_folder_v200=folder
        result=[]
        with self._open(data) as doc:
            if not (doc.permissions & fitz.PDF_PERM_PRINT):
                raise EditError('El documento no permite imprimir con las credenciales aportadas.')
            if not (doc.permissions & fitz.PDF_PERM_PRINT_HQ):
                dpi=min(dpi,150)
            numbers=list(range(doc.page_count)) if pages is None else [int(p) for p in pages]
            if not numbers or len(numbers)>1000 or any(p<0 or p>=doc.page_count for p in numbers):
                raise EditError('Selecciona entre 1 y 1000 páginas existentes para imprimir.')
            total=0
            for index,number in enumerate(numbers):
                page=doc[number]
                scale=dpi/72.
                # The reported actual DPI makes the safety cap visible.
                scale=min(scale,(24_000_000/(page.rect.width*page.rect.height))**.5)
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False,colorspace=fitz.csRGB)
                target=Path(folder.name)/f'{index:05}.png'
                pix.save(target)
                total+=target.stat().st_size
                if total>1024*1024*1024:
                    raise EditError('La preparación de impresión supera 1 GB. Imprime por intervalos.')
                result.append({'page':number,'path':str(target),'width':page.rect.width,
                               'height':page.rect.height,'dpi':round(scale*72,1)})
                del pix
        return {'pages':result,'requested_dpi':dpi,'revision':hashlib.sha256(data).hexdigest(),
                'state':self.state()}

    def snapshot_v200(self, original=False):
        return {'data':self.original if original else self.history.current,'state':self.state()}

    for function in (selection_capabilities_v200,cell_selection_v200,print_pages_v200,snapshot_v200):
        setattr(Session,function.__name__,function)
