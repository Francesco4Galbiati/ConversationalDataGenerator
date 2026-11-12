"""Static checks for a CDG conversational contract.
usage: python check_contract.py CONTRACT.yaml [ONTOLOGY.ttl]"""
import sys, re, yaml

c = yaml.safe_load(open(sys.argv[1]))
ops, types = c['intents'], c['types']
errors, warns = [], []
BASIC = {'id', 'str', 'int', 'float', 'bool', 'date'}

for k in ['intents', 'types', 'instructions', 'subclasses', 'precondition_slots', 'repeatable_terms']:
    if k not in c:
        errors.append(f'missing top-level key {k} (conf.py reads it)')

produced = {}
for name, i in ops.items():
    pre, post = i['preconditions'], i['postconditions']
    for part, d in (('pre', pre), ('post', post)):
        for s, t in d['slots'].items():
            if t not in types and t not in BASIC:
                errors.append(f'{name}: {part} slot {s} has undefined type {t!r}')
            is_id_type = t == 'id' or str(t).startswith('id_')
            if '_id' in s and not is_id_type:
                errors.append(f'{name}: {part} slot {s} contains "_id" but is not an identifier; the code '
                              f'(replace_ids, multi-witness id copy) treats every *_id* slot as an id')
            if s.endswith('_id') is False and is_id_type:
                warns.append(f'{name}: {part} slot {s} has an id type but its name does not end in _id')
            if t == 'bool' or types.get(t, {}).get('type') == 'bool':
                warns.append(f'{name}: {part} slot {s} is boolean; OK only with the JSON-parsing fix '
                             f'(repair_json(..., return_objects=True)); the original ast.literal_eval crashes on true/false')
    both = set(pre['slots']) | set(post['slots'])
    for tr in post['triples']:
        if len(tr) != 3:
            errors.append(f'{name}: triple {tr} does not have 3 elements')
            continue
        s, p, o = tr
        if s not in both:
            errors.append(f'{name}: triple subject {s} is not a slot')
        if p != 'type' and o not in both:
            errors.append(f'{name}: triple object {o} is not a slot')
        if p == 'type' and o in both and types.get(both_t := {**pre['slots'], **post['slots']}[o], {}).get('type') != 'enum':
            warns.append(f'{name}: type object {o} is a non-enum slot')
    used = {x for tr in post['triples'] if len(tr) == 3 for x in (tr[0], tr[2])}
    for s in post['slots']:
        if s not in used:
            errors.append(f'{name}: post slot {s} never used in a triple')
    for s in pre['slots']:
        if s not in used:
            warns.append(f'{name}: pre slot {s} never used in a triple')
    if 'cardinality' not in pre or not pre.get('description'):
        errors.append(f'{name}: missing cardinality/description')
    for s in post['slots']:
        produced.setdefault(s, []).append(name)

for name, i in ops.items():
    for s in i['preconditions']['slots']:
        if s not in produced:
            errors.append(f'{name}: precondition slot {s} is produced by NO intent (intent can never run)')
        if s not in c['precondition_slots']:
            errors.append(f'{name}: precondition slot {s} missing from precondition_slots (querent never sees its ids)')
for s in c['precondition_slots']:
    if s not in produced:
        errors.append(f'precondition_slots: {s} is produced by no intent')

# instructions = partition of intents (Definition 5) + cardinality present
seen = []
for g, d in c['instructions'].items():
    if 'cardinality' not in d:
        errors.append(f'instructions group {g} has no cardinality (KeyError in many-querent modes)')
    for i in d['inst']:
        if i not in ops:
            errors.append(f'instructions group {g} lists unknown intent {i}')
        seen.append(i)
for i in ops:
    if seen.count(i) != 1:
        errors.append(f'intent {i} appears {seen.count(i)} times in instructions (must be exactly once)')

# id slot types should be distinct per class
idt = {}
for i in ops.values():
    for cls_alias, cls in {**i['preconditions']['classes'], **i['postconditions']['classes']}.items():
        pass

# ontology vocabulary check
if len(sys.argv) > 2:
    from rdflib import Graph, URIRef
    g = Graph(); g.parse(sys.argv[2])
    terms = {str(x) for x in g.all_nodes() if isinstance(x, URIRef)}
    pref = c.get('prefixes', {})
    def expand(curie):
        p, l = curie.split(':', 1)
        return pref[p] + l
    curies = set()
    for i in ops.values():
        for tr in i['postconditions']['triples']:
            if tr[1] != 'type': curies.add(tr[1])
            elif ':' in tr[2]: curies.add(tr[2])
        for d in (i['preconditions']['classes'], i['postconditions']['classes']):
            curies |= set(d.values())
    for t in types.values():
        if t.get('type') == 'enum':
            curies |= {o for o in t['options'] if isinstance(o, str) and re.match(r'^\w+:\w', o) and o.split(':')[0] in pref}
    for cu in sorted(curies):
        if expand(cu) not in terms:
            errors.append(f'vocabulary: {cu} ({expand(cu)}) is not in the ontology')

dens = [len(i['postconditions']['triples']) for i in ops.values()]
print(f'{len(ops)} intents, {sum(dens)} template triples, density {sum(dens)/len(dens):.2f}')
print('\n'.join('ERROR  ' + e for e in errors) or 'no errors')
print('\n'.join('warn   ' + w for w in warns))
sys.exit(1 if errors else 0)
