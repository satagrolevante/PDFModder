"""Bounded automatic text-area adaptation; typography and origin stay exact."""
from dataclasses import replace
import math

from .model import EditError


def automatic_area_enabled_v316(window):
    """Optional UI modules keep strict behavior until the policy is installed."""
    control=getattr(window,'auto_adapt_box',None)
    return bool(control is not None and control.isChecked())


def adapt_rich_layout_v316(request,tokens,rect,limits):
    """Return request, area and evidence for the ordinary rich compositor.

    Call after natural-width measurement and before line layout. ``limits``
    must be the intersection of the actual page and its known source clip.
    This helper grants no clipping, permission, resource or validation waiver.
    Explicit fixed-width boxes retain their width unless a single glyph cannot
    fit; long natural-width text wraps at the existing visible right boundary.
    The compositor still verifies every final glyph against these same limits.
    """
    if not request.auto_adapt:
        return request,rect,{}
    if (len(rect)!=4 or len(limits)!=4 or
            any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (*rect,*limits))):
        raise EditError('El área y sus límites deben contener coordenadas finitas.')
    x0,y0,x1,y1=map(float,rect)
    left,top,right,bottom=map(float,limits)
    if right<=left or bottom<=top or x0<left-.035 or y0<top-.035 or x0>=right or y0>=bottom:
        raise EditError('No hay espacio visible para adaptar el área sin mover su posición.')
    available=right-x0
    width=x1-x0
    if width<=0 or y1<=y0:
        raise EditError('El área de texto debe tener dimensiones positivas.')
    original_width=width
    width=min(width,available)

    # Compute a minimum for only the text being edited. Unselected neighbours
    # never participate in an automatic reflow or change of position.
    paragraphs=request.paragraphs or [{}]
    paragraph=0
    minimum=.1
    for token in tokens:
        char=token.get('char','')
        if char=='\n':
            paragraph+=1
            continue
        if char=='\u2028':
            continue
        settings={}
        for entry in paragraphs:
            if entry.get('index',paragraph)==paragraph:
                settings.update(entry)
        indentation=float(settings.get('left_indent',0))+float(settings.get('right_indent',0))
        indentation+=max(0.,float(settings.get('first_indent',0)))
        advance=float(token.get('width',0))
        if char=='\t':
            stops=[float(v) for v in settings.get('tab_stops',[]) if float(v)>0]
            advance=min(stops) if stops else float(settings.get('tab_interval',36.))
        minimum=max(minimum,indentation+advance)
    if not math.isfinite(minimum) or minimum>available+.035:
        raise EditError('Una letra, tabulación o sangría supera el espacio visible; no se reducirá la letra automáticamente.')
    width=max(width,min(minimum,available))
    adapted=(x0,y0,x0+width,min(y1,bottom))
    adjustments=[]
    if original_width>available+.035:adjustments.append('wrap_to_visible_width')
    if width>original_width+.035:adjustments.append('expand_minimum_width')
    if not request.auto_height:adjustments.append('automatic_height')
    report={'auto_adapt':True,'automatic_area_adjustments':adjustments}
    return replace(request,auto_height=True),adapted,report
