"""A capability describes one operation on one current selection."""
from copy import deepcopy
from hashlib import sha256

from .model import EditError,union


def _entry(status,label,reasons=(),actions=(),resolutions=()):
    return dict(status=status,label=label,reasons=list(reasons),actions=list(actions),
                resolution_ids=list(resolutions),requires_final_validation=True)


def selection_capabilities_v300(session,page,ids,revision=None,new_text=None):
    data=session.history.current;digest=sha256(data).hexdigest()
    if revision and revision!=digest:raise EditError('La selección pertenece a una revisión anterior.')
    from .compatibility_v200 import preflight_text
    from .engine import extract_page
    from .objects_v300 import object_graph
    from .validation import document_issues,content_widget_issues
    text=preflight_text(data,page,ids,new_text,session.resolver)
    text['resolution_ids']=[]
    with session._open(data) as doc:
        model=extract_page(doc,page,data);selected=model.selected(ids)
        document_problems=document_issues(data,doc,operation='content')
        widget_problems=content_widget_issues(doc[page],[g.bbox for g in selected])
    if not selected or len(selected)!=len(set(ids)):
        raise EditError('Selecciona texto de la revisión actual.')
    if widget_problems:
        text.update(status='blocked',label='Este texto coincide con un campo de formulario',
                    reasons=widget_problems,actions=['Usa el editor de campos para cambiar su valor o apariencia.'],
                    resolution_ids=['forms'])
    if any(g.mode==3 for g in selected):text['resolution_ids'].append('ocr')
    if any(f.get('availability')=='font_required' for f in text.get('fonts',[])):
        text['resolution_ids'].append('fonts')
    # The shaping route has its own evidence; a successful check does not
    # remove safeguards for unrelated transforms, tagged content or fields.
    if (text['status']!='available' and not document_problems and not widget_problems and not model.issues
            and all(g.direction==(1.,0.) for g in selected)
            and not any(g.mode==3 for g in selected)):
        from .typography_v300 import preflight_shaping
        shaped=preflight_shaping(data,page,ids)
        if shaped.get('status') in ('available','conditional'):
            text=deepcopy(shaped);text.setdefault('actions',[])
            text.setdefault('reasons',[]);text.setdefault('resolution_ids',[])
            if text['status']=='conditional':text['resolution_ids'].append('fonts')
    # Object inventory has stricter structural requirements than some verified
    # text paths. Its limitation belongs to those operations, not to the whole
    # selection or to a pending text draft.
    try:
        graph=object_graph(data,page)
    except EditError as error:
        graph={'items':[], 'document_reason':str(error)}
    boxes=[g.trace_bbox for g in selected];area=union(boxes)
    def contains(rect,box):
        return bool(rect and rect[0]-.1<=box[0] and rect[1]-.1<=box[1]
                    and rect[2]+.1>=box[2] and rect[3]+.1>=box[3])
    candidates=[o for o in graph['items'] if o['kind']=='text' and contains(o['rect'],area)]
    if not candidates:
        candidates=[o for o in graph['items'] if o['kind'] in ('form','group') and contains(o['rect'],area)]
    candidates.sort(key=lambda o:(o['rect'][2]-o['rect'][0])*(o['rect'][3]-o['rect'][1]))
    object_entry=candidates[0] if candidates else None
    operations={'text':text}
    for key,label in [('move','Mover'),('scale','Cambiar escala'),('rotate','Girar'),('duplicate','Duplicar')]:
        caps=object_entry['capabilities'] if object_entry else {}
        if caps.get(key):
            operations[key]=_entry('available',label+': compatible como objeto PDF',
                actions=['Abrir Editar objetos y elegir la aparición completa que quieres modificar.'],resolutions=['objects'])
        else:
            reason=graph.get('document_reason') or caps.get('reason') or caps.get('transform_reason') or caps.get('duplicate_reason') or 'No se identificó un objeto completo verificable para esta selección.'
            operations[key]=_entry('blocked',label+': necesita otra selección',[reason],
                ['El inspector muestra la compatibilidad de cada objeto y grupo.'],['objects'])
    if text['status']=='blocked' and any(operations[key]['status']=='available' for key in ('move','scale','rotate')):
        text['resolution_ids'].append('objects')
        text['actions'].append('Puedes transformar la aparición completa mediante Editar objetos PDF.')
    if text['status']!='blocked':text['resolution_ids'].append('area')
    result=deepcopy(text);result.update(operations=operations,revision=digest,
        object_id=object_entry['id'] if object_entry else None,scope='operación y selección actuales')
    return result
