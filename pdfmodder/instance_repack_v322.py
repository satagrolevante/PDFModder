"""Restore Form group/layer boundaries after editing a single flattened instance."""
from io import BytesIO
import copy

import pymupdf as fitz
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ContentStream,NameObject,DictionaryObject,ArrayObject,DecodedStreamObject,StreamObject
from .model import EditError


def restore_instance_properties(original,candidate,page,evidence,report=None):
    if not evidence.get('repack_ids'):return candidate
    from .form_instances_v200 import _Expansion
    from .clipping import _serialize
    src=PdfReader(BytesIO(original),strict=True)
    expansion=_Expansion(src,page,probing=True)
    expansion.walk(ContentStream(src.pages[page].get_contents(),src).operations,expansion.base)
    wanted={key:expansion.forms[tuple(map(int,key.split('.')))] for key in evidence['repack_ids']}
    reader=PdfReader(BytesIO(candidate),strict=True);writer=PdfWriter(clone_from=reader)
    writer.pdf_header=reader.pdf_header
    target=writer.pages[page]
    resources=target['/Resources'].get_object()
    objects=resources.get('/XObject')
    objects=objects.get_object() if objects is not None else DictionaryObject()
    resources[NameObject('/XObject')]=objects
    operations=ContentStream(target.get_contents(),writer).operations
    # Resolve original optional-content identities against the retained
    # catalog instead of introducing disconnected copies of an OCG.
    from .pageops import _semantic
    optional=writer.root_object.get('/OCProperties',{})
    optional=optional.get_object() if hasattr(optional,'get_object') else optional
    groups=optional.get('/OCGs',[]) if isinstance(optional,dict) else []
    def attribute(value):
        resolved=value.get_object() if hasattr(value,'get_object') else value
        if isinstance(resolved,StreamObject):return value.clone(writer)
        if isinstance(resolved,dict) and resolved.get('/Type')=='/OCG':
            matches=[ref for ref in groups if _semantic(ref)==_semantic(value)]
            if len(matches)!=1:raise EditError('No se puede vincular la capa original de la instancia de forma inequívoca.')
            return matches[0]
        if isinstance(resolved,dict):return DictionaryObject({key:attribute(item) for key,item in resolved.items()})
        if isinstance(resolved,list):return ArrayObject([attribute(item) for item in resolved])
        return value.clone(writer) if hasattr(value,'clone') else copy.deepcopy(value)
    stack=[];replaced=set();serial=0
    def emit(items):
        nonlocal serial
        output=[];index=0
        while index<len(items):
            args,op=items[index]
            marker=args[1].get('/PMInstanceID') if op==b'BDC' and len(args)==2 and isinstance(args[1],dict) else None
            if marker is None:index+=1;output.append((args,op));continue
            depth=1;end=index+1
            while end<len(items) and depth:
                if items[end][1] in (b'BMC',b'BDC'):depth+=1
                elif items[end][1]==b'EMC':depth-=1
                if depth:end+=1
            if depth or str(marker) not in wanted:raise EditError('La edición perdió el ámbito de propiedades de la instancia.')
            form=DecodedStreamObject();form.set_data(_serialize(emit(items[index+1:end])))
            form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                NameObject('/BBox'):ArrayObject(target.mediabox),NameObject('/Resources'):DictionaryObject({k:v for k,v in resources.items()})})
            for key in ('/Group','/OC'):
                source=wanted[str(marker)]
                if key in source:form[NameObject(key)]=attribute(source.raw_get(key))
            serial+=1;name=NameObject('/PMInstanceEdited'+str(serial))
            while name in objects:serial+=1;name=NameObject('/PMInstanceEdited'+str(serial))
            # Exclude the new Form from its own resource graph; each nested
            # child has already received an immutable resource dictionary.
            local=DictionaryObject({k:v for k,v in resources.items()})
            local[NameObject('/XObject')]=DictionaryObject(dict(objects))
            form[NameObject('/Resources')]=local
            objects[name]=writer._add_object(form);output.append(([name],b'Do'))
            replaced.add(str(marker));index=end+1
        return output
    stream=DecodedStreamObject();stream.set_data(_serialize(emit(operations)))
    target[NameObject('/Contents')]=writer._add_object(stream)
    if replaced!=set(wanted):raise EditError('No se restauraron todas las propiedades de las instancias editadas.')
    out=BytesIO();writer.write(out)
    with fitz.open(stream=out.getvalue(),filetype='pdf') as doc:result=doc.tobytes(garbage=2,no_new_id=True)
    from .engine import extract_page
    from .richtext import _validate
    from .tagged import analyze_readonly
    with fitz.open(stream=candidate,filetype='pdf') as doc:model=extract_page(doc,page,candidate)
    structure=analyze_readonly(candidate)
    if report is None:
        _validate(candidate,result,page,model.glyphs,[],[],[],structure.semantic() if structure else None)
    else:
        from types import SimpleNamespace
        changed=[SimpleNamespace(bbox=tuple(r)) for r in
                 report.get('source_regions',[])+report.get('destination_regions',[])]
        # Layers are deliberately restored from the user's original, so compare
        # their properties against that original rather than the disposable
        # unlayered preparation. Only the actual edited ink is excluded.
        checked=_validate(original,result,page,model.glyphs,changed,[],[],
                           structure.semantic() if structure else None)
        report.update(checked)
    return result
