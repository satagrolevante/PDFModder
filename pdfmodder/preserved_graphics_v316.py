"""Exact graph proof for native text layers above preserved page artwork.

This proves only images/vectors/resource identity. Text, geometry, interactive
objects, independent syntax and excluded-area pixels still need their usual
validators. Unknown structure returns False; caller assertions remain in force.
"""
from pypdf.generic import ArrayObject,DictionaryObject,StreamObject,NameObject

from .draft_control_v305 import checkpoint,DraftCancelled
from .page_fingerprint import _Graph,_NoProof
from .analysis_reuse_v315 import stream_operations_v316,stream_scope_events_v316


def _resolve(value):
    return value.get_object() if hasattr(value,'get_object') else value


def _contents(page):
    value=_resolve(page.get('/Contents'))
    values=list(value) if isinstance(value,ArrayObject) else [value] if value is not None else []
    result=[_resolve(item) for item in values]
    if any(not isinstance(item,StreamObject) for item in result):raise _NoProof('Unknown contents')
    return result


def _text_only(raw):
    """Only self-contained filled native text can disappear from this proof."""
    if len(raw)>64*1024:return False
    operations=stream_operations_v316(raw)
    if not operations or operations[0]!=([],b'q') or operations[-1]!=([],b'Q'):return False
    allowed={b'q',b'Q',b'cm',b'BT',b'ET',b'Tf',b'Tm',b'Td',b'TD',b'T*',
             b'Tj',b'TJ',b"'",b'"',b'Tc',b'Tw',b'Tz',b'TL',b'Ts',b'Tr',
             b'rg',b'RG',b'g',b'G',b'k',b'K'}
    graphics=0;inside=False;paint=False
    for index,(args,operator) in enumerate(operations):
        if index%256==0:checkpoint()
        if operator not in allowed:return False
        if operator==b'q':graphics+=1
        elif operator==b'Q':
            graphics-=1
            if graphics<0 or (graphics==0 and index!=len(operations)-1):return False
        elif graphics<=0:return False
        if operator==b'BT':
            if inside:return False
            inside=True
        elif operator==b'ET':
            if not inside:return False
            inside=False
        elif operator==b'Tr' and (len(args)!=1 or args[0]!=0):return False
        elif operator in (b'Tj',b'TJ',b"'",b'"'):
            if not inside:return False
            paint=True
    return graphics==0 and not inside and paint


def _protected(graph,page):
    result=[]
    for stream in _contents(page):
        checkpoint()
        raw=stream.get_data()
        if raw.strip()==b'q':result.append(('open',None))
        elif raw.strip() in (b'n\nQ',b'n Q',b'n\r\nQ'):
            result.append(('close',None))
        elif not _text_only(raw):result.append(('opaque',graph.value(stream)))
    # Only wrappers around the entire remaining artwork are neutral. Never
    # drop a local transform/clip or a q/Q surrounding only part of the page.
    while len(result)>=2 and result[0][0]=='open' and result[-1][0]=='close':
        result=result[1:-1]
    return tuple(result)


def _used_fonts(page,reader):
    used=set();active=set();checked=set()
    def visit(streams,resources,depth=0):
        if depth>32:raise _NoProof('Nested Form budget')
        names=[]
        for stream in streams:
            events=stream_scope_events_v316(stream.get_data(),reader)
            if events is None:raise _NoProof('Split syntax')
            for operator,name in events:
                if operator==b'Tf':used.add(name)
                elif operator==b'Do':names.append(name)
        objects=_resolve(resources.get('/XObject',{}))
        for name in names:
            reference=objects.get(name)
            if reference is None:continue
            form=_resolve(reference)
            if form.get('/Subtype')!='/Form':continue
            identity=id(form)
            if identity in active:raise _NoProof('Recursive Form')
            child_resources=_resolve(form.get('/Resources',resources))
            key=identity,id(child_resources)
            if key in checked:continue
            active.add(identity)
            visit([form],child_resources,depth+1)
            active.remove(identity);checked.add(key)
    resources=_resolve(page.get('/Resources',{}))
    if not isinstance(resources,dict):raise _NoProof('Unknown resources')
    visit(_contents(page),resources)
    return used


def preserved_text_graphics_v316(before_data,after_data,page_number):
    """Prove preserved artwork while allowing independent native text layers.

    Both complete revisions are strictly opened. Existing resource bindings and
    all non-text streams must have identical independent object graphs; only
    unused new font names may be added. No UI metadata or requested flag grants
    permission to skip any part of this proof.
    """
    try:
        limits=dict(max_nodes=1_000_000,max_depth=64,max_stream_bytes=64*1024*1024,
                    max_total_stream_bytes=256*1024*1024)
        before=_Graph(before_data,**limits);after=_Graph(after_data,**limits)
        if before.page_count!=after.page_count or before.global_hash!=after.global_hash:return False
        a,b=before.pages[page_number],after.pages[page_number]
        ra,rb=_resolve(a.get('/Resources',{})),_resolve(b.get('/Resources',{}))
        if not isinstance(ra,dict) or not isinstance(rb,dict):return False
        if before.dictionary(ra,0,omitted={'/Font'})!=after.dictionary(rb,0,omitted={'/Font'}):return False
        fa,fb=_resolve(ra.get('/Font',{})),_resolve(rb.get('/Font',{}))
        if not isinstance(fa,dict) or not isinstance(fb,dict) or not set(fa)<=set(fb):return False
        for name,value in fa.items():
            if before.value(value)!=after.value(fb[name]):return False
        added=set(fb)-set(fa)
        if any(not isinstance(name,NameObject) for name in added):return False
        if added and added & _used_fonts(a,before.reader):return False
        if _protected(before,a)!=_protected(after,b):return False
        checkpoint()
        return True
    except DraftCancelled:raise
    except Exception:return False
