"""Associate a new signature widget with an existing tagged structure.

All changes precede CMS signing. Independent pypdf validation afterwards checks
both the new OBJR/ParentTree relation and every pre-existing accessible semantic
value. This is preservation, not a declaration of PDF/UA conformance.
"""
from .model import EditError


def tag_signature_widget_v318(writer, field_name, page_index):
    from pyhanko.pdf_utils import generic as g
    from pyhanko.sign.fields import enumerate_sig_fields
    root = writer.root
    if '/StructTreeRoot' not in root:
        return None
    tree_ref = root.raw_get('/StructTreeRoot')
    tree = tree_ref.get_object()
    matches = list(enumerate_sig_fields(writer, with_name=field_name))
    if len(matches) != 1:
        raise EditError('No se encuentra el campo de firma que debe etiquetarse.')
    field_ref = matches[0][2]
    widget = field_ref.get_object()
    if widget.get('/Subtype') != '/Widget':
        # Our fields use a combined field/widget. Never guess another widget.
        raise EditError('El campo de firma no tiene una anotación verificable.')
    page_ref = writer.find_page_for_modification(page_index)[0]
    entries = {}
    seen = set()

    def number_tree(raw):
        node = raw.get_object()
        identity = id(node)
        if identity in seen:
            raise EditError('ParentTree contiene un ciclo.')
        seen.add(identity)
        nums = list(node.get('/Nums', g.ArrayObject()))
        if len(nums) % 2:
            raise EditError('ParentTree contiene pares incompletos.')
        for key, value in zip(nums[::2], nums[1::2]):
            number = int(key)
            if number < 0 or number in entries:
                raise EditError('ParentTree contiene claves inválidas o repetidas.')
            entries[number] = value
        for child in node.get('/Kids', g.ArrayObject()):
            number_tree(child)
    if '/ParentTree' in tree:
        number_tree(tree.raw_get('/ParentTree'))
    key = max(max(entries, default=-1) + 1, int(tree.get('/ParentTreeNextKey', 0)))
    new_node = g.DictionaryObject({
        g.pdf_name('/Type'): g.pdf_name('/StructElem'),
        g.pdf_name('/S'): g.pdf_name('/Form'),
        g.pdf_name('/P'): tree_ref,
        g.pdf_name('/Pg'): page_ref,
        g.pdf_name('/Alt'): g.pdf_string('Firma digital del documento'),
        g.pdf_name('/K'): g.DictionaryObject({
            g.pdf_name('/Type'): g.pdf_name('/OBJR'),
            g.pdf_name('/Obj'): field_ref,
            g.pdf_name('/Pg'): page_ref,
        }),
    })
    node_ref = writer.add_object(new_node)
    old_children = tree.get('/K', g.ArrayObject())
    if isinstance(old_children, g.ArrayObject):
        # Copy the array: it may itself be indirect and shared.
        children = g.ArrayObject(list(old_children))
    else:
        children = g.ArrayObject([tree.raw_get('/K')])
    children.append(node_ref)
    tree[g.pdf_name('/K')] = children
    entries[key] = node_ref
    nums = g.ArrayObject()
    for number, value in sorted(entries.items()):
        nums.extend((g.NumberObject(number), value))
    tree[g.pdf_name('/ParentTree')] = writer.add_object(g.DictionaryObject({g.pdf_name('/Nums'): nums}))
    tree[g.pdf_name('/ParentTreeNextKey')] = g.NumberObject(key + 1)
    widget[g.pdf_name('/StructParent')] = g.NumberObject(key)
    writer.mark_update(tree_ref)
    writer.mark_update(field_ref)
    return {'parent_key': key, 'page': page_index, 'field_name': field_name}


def _normalised_semantic(structure):
    """Normalise equivalent number-tree encodings and root scalar /K."""
    from .tagged import obj, ref
    result = structure.semantic()
    raw_k = obj(structure.tree.get('/K', []))
    scalar = not isinstance(raw_k, (tuple, list))
    remap = {path: ((0,) + path if scalar else path) for path in structure.nodes}

    def canonical(value):
        if (isinstance(value, tuple) and len(value) == 2 and value[0] == 'structure'
                and isinstance(value[1], tuple)):
            return ('structure', remap.get(value[1], value[1]))
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(canonical(item) for item in value)
        return value
    result = canonical(result)
    result['nodes'] = {remap[path]: node for path, node in result['nodes'].items()}
    if scalar:
        result['tree']['/K'] = (result['tree']['/K'],)

    def owner(value):
        value_obj = obj(value)
        if isinstance(value_obj, (list, tuple)):
            return tuple(owner(item) for item in value_obj)
        identity = ref(value)
        if identity in structure.node_refs:
            path = structure.node_refs[identity]
            return ('structure', remap.get(path, path))
        if type(value_obj).__name__ == 'NullObject':
            return None
        raise EditError('ParentTree de firma contiene un propietario no verificable.')
    result['tree']['/ParentTree'] = {key: owner(value) for key, value in structure.parents.items()}
    result['tree'].pop('/ParentTreeNextKey', None)
    return result


def assert_tagged_signature_v318(before, after, association):
    from .tagged import analyze_readonly, obj, ref
    source = analyze_readonly(before)
    result = analyze_readonly(after)
    if source is None:
        if result is not None:
            raise EditError('La firma ha añadido etiquetas ajenas al documento.')
        return
    if result is None or association is None:
        raise EditError('La firma no ha conservado su estructura de accesibilidad.')
    page = association['page']
    key = association['parent_key']
    annotations = obj(result.reader.pages[page].get('/Annots', []))
    targets = [(index, obj(value)) for index, value in enumerate(annotations)
               if obj(value).get('/T') == association['field_name']]
    if len(targets) != 1:
        raise EditError('La firma no tiene una anotación única en la página solicitada.')
    index, widget = targets[0]
    owner_ref = ref(result.parents.get(key))
    path = result.node_refs.get(owner_ref)
    node = result.nodes.get(path)
    kid = obj(node.get('/K')) if node is not None else {}
    if (widget.get('/StructParent') != key or node is None
            or set(node) != {'/Type','/S','/P','/Pg','/Alt','/K'}
            or node.get('/Type') != '/StructElem' or node.get('/S') != '/Form'
            or node.get('/Alt') != 'Firma digital del documento'
            or ref(node.get('/Pg')) != ref(result.reader.pages[page])
            or not isinstance(kid, dict) or set(kid) != {'/Type','/Obj','/Pg'}
            or kid.get('/Type') != '/OBJR'
            or ref(kid.get('/Pg')) != ref(result.reader.pages[page])
            or int(result.tree.get('/ParentTreeNextKey', -1)) != key + 1
            or result.annotations.get(ref(kid.get('/Obj'))) != (page, index)):
        raise EditError('La asociación accesible de la firma no coincide con su campo.')
    old = _normalised_semantic(source)
    new = _normalised_semantic(result)
    # Our Form must be the single new root child, after existing reading order.
    children = new['tree'].get('/K', ())
    if not children or children[-1] != ('structure', path):
        raise EditError('La firma ha alterado el orden de lectura del documento.')
    new['tree']['/K'] = children[:-1]
    new['tree']['/ParentTree'].pop(key, None)
    new['nodes'].pop(path, None)
    if new != old:
        raise EditError('La firma ha modificado etiquetas, relaciones u otras propiedades accesibles.')
