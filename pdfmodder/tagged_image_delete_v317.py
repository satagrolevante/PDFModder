"""Remove one isolated Figure or decorative image without leaving stale Alt text."""
from pypdf.generic import ArrayObject, ContentStream, NameObject, NullObject

from .tagged import analyze, analyze_readonly, fail, obj, ref, _number_tree
from .tagged_image_v160 import TaggedImageTransform
from .tagged_insert import _children, _dump, _parent_tree_copy, _set_parent_array
from .tagged_pages import _assert_reachable


def _remove_parent_key(tree, key):
    """Remove a page association, updating existing number-tree boundaries."""
    numbers = tree.get('/Nums', [])
    keys = []
    if '/Nums' in tree:
        tree[NameObject('/Nums')] = ArrayObject(
            value for index in range(0, len(numbers), 2) if numbers[index] != key
            for value in numbers[index:index+2])
        keys.extend(tree['/Nums'][::2])
    if '/Kids' in tree:
        children = []
        for child in tree['/Kids']:
            child_keys = _remove_parent_key(child, key)
            if child_keys:
                children.append(child)
                keys.extend(child_keys)
        if children:
            tree[NameObject('/Kids')] = ArrayObject(children)
        else:
            del tree['/Kids']
    if not keys and '/Nums' not in tree:
        tree[NameObject('/Nums')] = ArrayObject()
    if '/Limits' in tree:
        if keys:
            tree[NameObject('/Limits')] = ArrayObject([min(keys), max(keys)])
        else:
            del tree['/Limits']
    return keys


class TaggedImageDeletionV317:
    """Plan a narrow semantic deletion; shared/attributed figures stay protected.

    New PDFModder Figures are scalar-MCID leaves with plain /MCID marks. We
    remove that leaf and its mark, leave other MCIDs stable, and reserve its
    historical ParentTree slot as null. Decorative images retain their scopes.
    """
    def __init__(self, data, page, item):
        self.data = data
        self.page = page
        self.structure = analyze(data)
        self.mark_operations = {}
        self.writes = []
        self.remove_struct_parents = False
        self.mcid = None
        if self.structure is None:
            self.expected = None
            return
        s = self.structure
        guard = TaggedImageTransform(data, page, item, structure=s)
        self.mcid = guard.mcid
        if self.mcid is None:
            self.expected = s.semantic()
            return
        mcid = self.mcid
        mark = s.marks[page][mcid]
        owner = s.owners[(page, mcid)]
        node = s.nodes.get(owner)
        if (node is None or node.get('/S') != '/Figure' or
                set(node) - {'/Type', '/S', '/P', '/Pg', '/K', '/Alt', '/Lang'} or
                not isinstance(obj(node.get('/K')), int) or obj(node['/K']) != mcid or
                set(mark.resolved) != {'/MCID'} or mark.nested_actual or
                mark.tag != '/Figure' or isinstance(mark.properties, NameObject)):
            fail('la figura no es una hoja independiente con un único MCID; no se elimina su semántica automáticamente.')
        if sum(path == owner for path in s.owners.values()) != 1:
            fail('la figura reúne varios contenidos; no se elimina su descripción compartida.')
        if any(path != owner and owner[:len(path)] == path and
               any(key in ancestor for key in ('/Alt', '/ActualText', '/E'))
               for path, ancestor in s.nodes.items()):
            fail('la figura pertenece a un grupo con significado compartido; no se elimina automáticamente.')
        contents = obj(s.reader.pages[page].get('/Contents', []))
        contents = contents if isinstance(contents, (list, tuple)) else [contents]
        offset = 0
        from .analysis_reuse_v315 import grouped_stream_operations_v318
        for positions, operations in grouped_stream_operations_v318(
                (obj(content).get_data() for content in contents),s.reader):
            count = len(operations)
            removed = {index-offset for index in (mark.start, mark.end)
                       if offset <= index < offset+count}
            if removed:
                if len(positions)!=1:
                    fail('la apertura o cierre de la figura está repartida entre bloques.')
                self.mark_operations[positions[0]] = removed
            offset += count
        if sum(map(len, self.mark_operations.values())) != 2:
            fail('no se pueden aislar la apertura y el cierre de la figura.')

        parent = obj(node['/P'])
        leaf_ref = ref(node)
        children = _children(parent.get('/K', ArrayObject()))
        if sum(ref(child) == leaf_ref for child in children) != 1:
            fail('la figura no tiene un padre único verificable.')
        remaining = ArrayObject(child for child in children if ref(child) != leaf_ref)
        parent[NameObject('/K')] = remaining
        self.writes.append((ref(parent)[0], 'K', _dump(remaining)))

        parent_tree = _parent_tree_copy(s.tree['/ParentTree'])
        key = s.reader.pages[page].get('/StructParents')
        owners = ArrayObject(s.parents[key])
        owners[mcid] = NullObject()
        del s.marks[page][mcid]
        if s.marks[page]:
            if not _set_parent_array(parent_tree, key, owners):
                fail('no se encuentra la asociación ParentTree de la figura.')
        else:
            _remove_parent_key(parent_tree, key)
            del s.reader.pages[page]['/StructParents']
            s.page_parent_keys.pop(key, None)
            self.remove_struct_parents = True
        s.tree[NameObject('/ParentTree')] = parent_tree
        self.writes.append((ref(s.tree)[0], 'ParentTree', _dump(parent_tree)))
        # Removing a leaf referred to from an IDTree, /Ref or another retained
        # property would make a dangling accessible relationship.
        _assert_reachable(s.root, {leaf_ref})
        s.parents = _number_tree(parent_tree)
        s.nodes, s.owners, s.object_owners = {}, {}, []
        s.node_refs = {ref(s.tree): ('tree',)}
        s._walk(s.tree.get('/K', []), (), ref(s.tree), None, 0)
        s._validate_links()
        self.expected = s.semantic()

    def apply(self, doc, contents, *, changed_position):
        """Remove only the two proven semantic operators in private streams."""
        for position, removed in self.mark_operations.items():
            if position == changed_position:
                continue
            stream = ContentStream(None, None)
            from .media import _ops
            stream.operations = [operation for index, operation in enumerate(
                _ops(doc.xref_stream(contents[position])).operations) if index not in removed]
            clone = doc.get_new_xref()
            doc.update_object(clone, '<<>>')
            doc.update_stream(clone, stream.get_data())
            contents[position] = clone
        for xref, key, value in self.writes:
            doc.xref_set_key(xref, key, value)
        if self.remove_struct_parents:
            # MuPDF retains an explicit PDF null for xref_set_key(..., 'null').
            # Write the verified page dictionary with this key absent; the
            # caller immediately installs the new private Contents references.
            doc.update_object(doc[self.page].xref, _dump(self.structure.reader.pages[self.page]))
        return contents

    def validate(self, output):
        # The private mutable planner already checked its source and produced
        # expected. Reopening the source would evict the checked candidate.
        current = analyze_readonly(output)
        if ((self.structure is None) != (current is None)
                or current is not None and self.expected != current.semantic()):
            fail('la eliminación alteró etiquetas o relaciones ajenas a la figura.')
        if self.structure is None:
            return None
        return {'verified': True, 'reading_order_preserved': True,
                'removed_mcid': self.mcid, 'removed_figure': self.mcid is not None,
                'scope': 'Sólo se retira la figura seleccionada; otros MCID y relaciones se conservan.'}
