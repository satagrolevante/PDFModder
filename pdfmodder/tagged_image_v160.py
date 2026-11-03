"""Preserve semantics when transforming one independently tagged image instance."""
from .tagged import PAINT, SHOW, analyze_readonly, fail, obj, _has_string


class TaggedImageTransform:
    def __init__(self, data, page, item, *, structure=None):
        self.data = bytes(data)
        if structure is not None and getattr(structure, 'data', None) != self.data:
            fail('la estructura de la imagen pertenece a una versión anterior.')
        self.structure = structure if structure is not None else analyze_readonly(self.data)
        self.page = page
        self.mcid = None
        if self.structure is None:
            return
        s = self.structure
        contents = obj(s.reader.pages[page].get('/Contents', []))
        contents = contents if isinstance(contents, (list, tuple)) else [contents]
        from .analysis_reuse_v315 import grouped_stream_operations_v318
        offset=0
        for positions,operations in grouped_stream_operations_v318(
                (obj(content).get_data() for content in contents),s.reader):
            if item['stream_position'] in positions:
                if len(positions)!=1:
                    fail('la imagen comparte un operador repartido entre bloques.')
                offset+=item['do_index']
                break
            offset+=len(operations)
        else:
            fail('no se encuentra el bloque de la imagen seleccionada.')
        ops = s.operations[page]
        if offset >= len(ops) or ops[offset][1] != b'Do':
            fail('no se puede asociar la imagen seleccionada con su etiqueta.')
        stack = []
        resources = obj(s.reader.pages[page].get('/Resources', {}))
        properties = obj(resources.get('/Properties', {}))
        for args, operator in ops[:offset+1]:
            if operator in (b'BMC', b'BDC'):
                prop = args[1] if operator == b'BDC' else {}
                prop = obj(properties.get(prop)) if isinstance(prop, str) else obj(prop)
                stack.append((str(args[0]), prop or {}))
            elif operator == b'EMC':
                stack.pop()
        if any('/BBox' in prop for _, prop in stack):
            fail('la imagen tiene una caja semántica que requiere actualizar su geometría.')
        self.mcid = s.contexts[page][offset]
        if self.mcid is None:
            if not any(tag == '/Artifact' for tag, _ in stack):
                fail('la imagen no tiene una etiqueta de figura ni una marca decorativa.')
            return
        mark = s.marks[page][self.mcid]
        selected_ops = ops[mark.start:mark.end+1]
        if (sum(operator in PAINT for _, operator in selected_ops) != 1
                or any(operator in SHOW and _has_string(args) for args, operator in selected_ops)):
            fail('la etiqueta reúne la imagen con otros contenidos; no se modifica su distribución.')
        owner = s.owners[(page, self.mcid)]
        ancestors = [node for path, node in s.nodes.items() if owner[:len(path)] == path]
        if any(node.get('/A') or node.get('/C') for node in ancestors):
            fail('la imagen tiene atributos de disposición o clases que necesitan actualizar su geometría.')
        rolemap = obj(s.tree.get('/RoleMap', {}))
        figure = False
        for node in ancestors:
            role, seen = node.get('/S'), set()
            while role in rolemap and role not in seen:
                seen.add(role); role = rolemap[role]
            if role == '/Figure' and str(node.get('/Alt', '')).strip():
                figure = True
        if not figure:
            fail('la imagen necesita una etiqueta Figure con descripción alternativa verificable.')

    def validate(self, output):
        # This guard never mutates its checked source. Capture its private
        # expectation before independently checking only the exact candidate.
        expected = self.structure.semantic() if self.structure is not None else None
        current = analyze_readonly(output)
        if ((self.structure is None) != (current is None)
                or current is not None and expected != current.semantic()):
            fail('se alteraron etiquetas, relaciones u otras propiedades accesibles de la imagen.')
        if self.structure is None:
            return None
        from .page_fingerprint import PageProof
        from .draft_control_v305 import checkpoint
        unchanged = PageProof(self.data, output)
        def associations(structure, number):
            return [(context, str(args[0])) for (args, operator), context in zip(
                    structure.operations[number], structure.contexts[number]) if operator == b'Do']
        for number in range(len(self.structure.operations)):
            checkpoint()
            # A complete input graph proves every invocation and MCID context
            # identical; the global tree and ParentTree were checked above.
            if unchanged.unchanged(number):
                continue
            if associations(self.structure, number) != associations(current, number):
                fail('se alteró la asociación de una imagen con su etiqueta u orden de lectura.')
        return {'verified': True, 'structure_preserved': True, 'reading_order_preserved': True,
                'mcid': self.mcid, 'artifact_preserved': self.mcid is None,
                'scope': 'Figure/Alt o Artifact, MCID y ParentTree conservados; no certificación PDF/UA.'}
