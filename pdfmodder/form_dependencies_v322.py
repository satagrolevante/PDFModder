"""Static AcroForm dependency evidence; JavaScript is never executed here.

Only literal field references and known Acrobat formatting/calculation helpers
are understood. Dynamic access or calls outside this vocabulary leave the
dependency set unknown rather than guessing that an unrelated field is safe.
"""
from __future__ import annotations

import re


_TOKEN = re.compile(r'''\s+|//[^\r\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|.''')
_CALL = re.compile(r'(?<![\w$])(?:[A-Za-z_$][\w$]*\s*\.\s*)*([A-Za-z_$][\w$]*)\s*\(')
_SAFE_CALLS = {
    'getField', 'AFSimple_Calculate', 'AFNumber_Format', 'AFNumber_Keystroke',
    'AFPercent_Format', 'AFPercent_Keystroke', 'AFDate_FormatEx', 'AFDate_KeystrokeEx',
    'AFTime_FormatEx', 'AFTime_KeystrokeEx', 'AFSpecial_Format', 'AFSpecial_Keystroke',
    'AFRange_Validate', 'AFMergeChange', 'AFMakeNumber', 'Number', 'String',
    'parseFloat', 'parseInt', 'isNaN', 'isFinite', 'abs', 'min', 'max', 'round',
    'floor', 'ceil', 'pow', 'sqrt', 'alert', 'println', 'if', 'while', 'for', 'switch',
}


def _obj(value):
    return value.get_object() if hasattr(value, 'get_object') else value


def _literal(token):
    if len(token) < 2 or token[0] not in ('"', "'") or token[-1] != token[0]:
        raise ValueError('not a string literal')
    body = token[1:-1]
    out, index = [], 0
    escapes = {'n':'\n', 'r':'\r', 't':'\t', 'b':'\b', 'f':'\f', 'v':'\v', '0':'\0'}
    while index < len(body):
        char = body[index]; index += 1
        if char != '\\':
            out.append(char); continue
        if index >= len(body):
            raise ValueError('incomplete escape')
        char = body[index]; index += 1
        if char in ('u', 'x'):
            length = 4 if char == 'u' else 2
            value = body[index:index+length]
            if len(value) != length or not re.fullmatch('[0-9a-fA-F]+',value):
                raise ValueError('unsupported string escape')
            out.append(chr(int(value,16))); index += length
        elif char in ('\r', '\n'):
            raise ValueError('continued string literal')
        else:
            out.append(escapes.get(char,char))
    return ''.join(out)


def _references(code, owner):
    tokens = [t for t in _TOKEN.findall(code) if not t.isspace() and not t.startswith(('//','/*'))]
    # Replace literals with placeholders before scanning calls. A quote in an
    # alert or comment cannot invent a getField call or hide a dynamic call.
    bare = ' '.join('STRING' if t[:1] in ('"', "'") else t for t in tokens)
    unknown = bool(re.search(r'\b(?:eval|Function|with|numFields|getNthFieldName|submitForm|resetForm|importAnFDF|importAnXFDF|calculateNow)\b',bare))
    unknown = unknown or bool(re.search(r'\b(?:this|event)\s*\[|[\]\)]\s*\(',bare)) or '\\' in bare
    for call in _CALL.finditer(bare):
        name=call.group(1);full=re.sub(r'\s+','',call.group(0))[:-1]
        if name not in _SAFE_CALLS:
            unknown=True
        elif '.' in full:
            allowed=(full=='this.getField' or full=='app.alert' or full=='console.println'
                     or full.startswith('Math.') and name in {'abs','min','max','round','floor','ceil','pow','sqrt'})
            unknown=unknown or not allowed
    if owner is None and re.search(r'\bevent\s*\.\s*(?:value|target|source)',bare):
        unknown = True
    if re.search(r'\bevent\s*\.\s*source',bare):
        unknown = True
    references = set()
    for index, token in enumerate(tokens):
        if token == 'getField':
            try:
                if tokens[index+1] != '(' or tokens[index+3] != ')':
                    raise ValueError('dynamic field name')
                references.add(_literal(tokens[index+2]))
            except (IndexError, ValueError):
                unknown = True
        elif token == 'AFSimple_Calculate':
            try:
                if tokens[index+1] != '(' or _literal(tokens[index+2]).upper() not in ('SUM','PRD','AVG','MIN','MAX') or tokens[index+3] != ',':
                    raise ValueError('unsupported calculation')
                cursor = index+4
                if tokens[cursor] == '[':
                    cursor += 1
                    while tokens[cursor] != ']':
                        references.add(_literal(tokens[cursor])); cursor += 1
                        if tokens[cursor] == ',': cursor += 1
                        elif tokens[cursor] != ']': raise ValueError('dynamic field list')
                    cursor += 1
                else:
                    references.update(name.strip() for name in _literal(tokens[cursor]).split(',') if name.strip())
                    cursor += 1
                if tokens[cursor] != ')': raise ValueError('unsupported calculation arguments')
            except (IndexError, ValueError):
                unknown = True
    return references, unknown


def analyze_form_dependencies(reader, names):
    """Return per-field decisions, with unknown dependencies failing closed."""
    names = set(names)
    scripts, unknown_structure = [], False
    seen_actions = set()
    def action(raw, owner, context):
        nonlocal unknown_structure
        node = _obj(raw)
        if isinstance(node,list):
            for index, value in enumerate(node): action(value,owner,f'{context}/{index}')
            return
        if not isinstance(node,dict):
            unknown_structure = True; return
        marker = (id(node),owner)
        if marker in seen_actions:
            unknown_structure = True; return
        seen_actions.add(marker)
        if node.get('/S') == '/JavaScript':
            value = _obj(node.get('/JS'))
            if hasattr(value,'get_data'):
                raw = value.get_data()
                try: code = raw.decode('utf-8-sig')
                except UnicodeError:
                    if raw.startswith((b'\xfe\xff',b'\xff\xfe')):
                        try: code = raw.decode('utf-16')
                        except UnicodeError: unknown_structure = True; code = ''
                    else: unknown_structure = True; code = ''
            elif isinstance(value,str): code = value
            else: unknown_structure = True; code = ''
            scripts.append((owner,context,code))
        if '/Next' in node: action(node['/Next'],owner,context+'/Next')
        seen_actions.remove(marker)
    def additional(raw, owner, context):
        nonlocal unknown_structure
        values = _obj(raw)
        if not isinstance(values,dict): unknown_structure = True; return
        for key, value in values.items(): action(value,owner,context+'/'+str(key))
    root = reader.trailer['/Root']
    if '/AA' in root: additional(root['/AA'],None,'catalog/AA')
    if '/OpenAction' in root and isinstance(_obj(root['/OpenAction']),dict): action(root['/OpenAction'],None,'catalog/OpenAction')
    visited_trees = set()
    def script_names(raw):
        nonlocal unknown_structure
        node = _obj(raw)
        if not isinstance(node,dict) or id(node) in visited_trees:
            unknown_structure = True; return
        visited_trees.add(id(node))
        pairs = _obj(node.get('/Names',[]))
        if not isinstance(pairs,list) or len(pairs)%2:
            unknown_structure = True; return
        for index in range(0,len(pairs),2): action(pairs[index+1],None,'catalog/JavaScript/'+str(pairs[index]))
        for child in _obj(node.get('/Kids',[])): script_names(child)
    named = _obj(root.get('/Names',{}))
    if isinstance(named,dict) and '/JavaScript' in named: script_names(named['/JavaScript'])
    for number, page in enumerate(reader.pages):
        if '/AA' in page: additional(page['/AA'],None,f'page/{number}/AA')
    visited_fields = set()
    def field(raw, parent=''):
        nonlocal unknown_structure
        node = _obj(raw)
        if not isinstance(node,dict) or id(node) in visited_fields:
            unknown_structure = True; return
        visited_fields.add(id(node))
        part = str(node.get('/T',''))
        name = '.'.join(x for x in (parent,part) if x)
        owner = name or None
        if '/AA' in node: additional(node['/AA'],owner,'field/'+name+'/AA')
        if '/A' in node: action(node['/A'],owner,'field/'+name+'/A')
        for child in _obj(node.get('/Kids',[])): field(child,name)
    form = _obj(root.get('/AcroForm',{}))
    for raw in _obj(form.get('/Fields',[])): field(raw)
    touched, decisions = set(), []
    for raw in _obj(form.get('/CO',[])):
        node=_obj(raw);parts=[];seen=set()
        while isinstance(node,dict) and id(node) not in seen:
            seen.add(id(node))
            if node.get('/T'):parts.append(str(node['/T']))
            node=_obj(node.get('/Parent'))
        calculated='.'.join(reversed(parts))
        matches={known for known in names if known==calculated or known.startswith(calculated+'.')} if calculated else set()
        if not matches:unknown_structure=True
        touched.update(matches)
        decisions.append({'context':'AcroForm/CO','fields':sorted(matches),'unknown':not bool(matches)})
    for owner, context, code in scripts:
        refs, unknown = _references(code,owner)
        related = set()
        for name in refs | ({owner} if owner else set()):
            matches = {known for known in names if known==name or known.startswith(name+'.') or name.startswith(known+'.')}
            if not matches: unknown = True
            related.update(matches)
        touched.update(related)
        unknown_structure = unknown_structure or unknown
        decisions.append({'context':context,'fields':sorted(related),'unknown':unknown})
    blocked = names if unknown_structure else touched
    return {'scripts':decisions,'unknown_dependencies':unknown_structure,'blocked_fields':sorted(blocked),
            'fields':{name:{'value_editable':name not in blocked,
                'value_reason':('Hay JavaScript con dependencias dinámicas o no verificables; se conservan sus valores.' if unknown_structure else
                    'Este campo participa en cálculos o validaciones JavaScript; cambiarlo requiere actualizar sus dependencias.' if name in touched else ''),
                'dependencies':sorted({other for d in decisions if name in d['fields'] for other in d['fields'] if other!=name})}
                for name in names}}
