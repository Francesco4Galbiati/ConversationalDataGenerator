"""Evaluate a CDG run: convert it to RDF and measure what the paper's counters do not see.

usage (repo root, .venv active):
    python tools/evaluate_run.py resources/output/run_XXXX  [--contract OntoPFAS_contract.yaml]
                                 [--reference resources/reference/ontopfas]  [--no-ttl]
Writes <run>/output_<k>.ttl (one RDF graph per triples*.json) and <run>/evaluation.json, and prints a report.

Sections
  1. run summary       turns, intents used, template triples, the paper's counters (from output.txt)
  2. RDF conversion    built from the contract's triple templates + prefixes (works for any contract that
                       has a `prefixes` section); triples with a missing slot are skipped and counted
  3. quality checks    duplicate ids for new entities, duplicate entities (same class + same name/title),
                       missing slots, values outside a type's options/pattern, ids leaking into literal values,
                       lat/long outside Europe, numbers that are not numbers
  4. distribution      class and property frequencies, Jensen-Shannon distance (base 2, as js-distance.py) to
                       the reference graph, on the union of names and on the names both graphs contain,
                       after mapping the reference's names onto the ontology's (NAME_MAP)
"""
import argparse, collections, glob, json, math, os, re, sys
import yaml
from rdflib import Graph, Literal, Namespace, RDF, URIRef

# reference (PFAS Data Hub instances) local name -> ontology local name
NAME_MAP = {'Country': 'Place', 'containedInPlace': 'isContainedInPlace', 'location': 'SpatialThing',
            'source_type': 'sourceType', 'source_text': 'sourceText', 'source_url': 'sourceUrl',
            'maps_link': 'mapsLink', 'Pfoa': 'Pfas', 'Pfos': 'Pfas', 'Presumptive': 'Observation'}
INST = Namespace('http://example.org/cdg/')
ID_RE = re.compile(r'\b[A-Z]{1,6}\d{3,}\b')


def local(u):
    s = str(u)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]


def load_turns(path):
    turns = []
    for line in open(path, encoding='utf-8'):
        if ':' not in line:
            continue
        intent, js = line.split(':', 1)
        try:
            turns.append((intent.strip(), json.loads(js)))
        except json.JSONDecodeError:
            turns.append((intent.strip(), None))
    return turns


def expand(curie, prefixes):
    if ':' in str(curie):
        p, l = str(curie).split(':', 1)
        if p in prefixes:
            return URIRef(prefixes[p] + l)
    return None


def to_graph(turns, ops, prefixes):
    g = Graph()
    for p, ns in prefixes.items():
        g.bind(p, ns)
    g.bind('inst', INST)
    skipped = collections.Counter()
    for intent, a in turns:
        if a is None or intent not in ops:
            skipped['unparsable turn'] += 1
            continue
        id_slots = {s for s in {**ops[intent]['preconditions']['slots'], **ops[intent]['postconditions']['slots']} if s.endswith('_id')}
        node = lambda s: URIRef(INST[str(a[s]).replace(' ', '_')])
        for s_slot, pred, o_slot in ops[intent]['postconditions']['triples']:
            if a.get(s_slot) in (None, '', 'None'):
                skipped['missing subject'] += 1; continue
            subj = node(s_slot)
            if pred == 'type':
                cls = expand(a[o_slot], prefixes) if o_slot in a else expand(o_slot, prefixes)
                if cls is None:
                    skipped['unknown class'] += 1; continue
                g.add((subj, RDF.type, cls)); continue
            p = expand(pred, prefixes)
            if p is None:
                skipped['unknown predicate'] += 1; continue
            if a.get(o_slot) in (None, '', 'None'):
                skipped['missing object'] += 1; continue
            obj = node(o_slot) if o_slot in id_slots else Literal(a[o_slot])
            g.add((subj, p, obj))
    return g, skipped


def distribution(g, mapped=False):
    cls = collections.Counter(); prop = collections.Counter()
    m = (lambda x: NAME_MAP.get(x, x)) if mapped else (lambda x: x)
    schema_nodes = {s for s, o in g.subject_objects(RDF.type) if local(o) in ('DatatypeProperty', 'ObjectProperty')}
    for s, p, o in g:
        if s in schema_nodes:
            continue
        if p == RDF.type:
            cls[m(local(o))] += 1
        else:
            prop[m(local(p))] += 1
    return cls, prop


def js_distance(a, b, keys):
    pa = [a.get(k, 0) for k in keys]; pb = [b.get(k, 0) for k in keys]
    sa, sb = sum(pa), sum(pb)
    if not sa or not sb:
        return None
    pa = [x / sa for x in pa]; pb = [x / sb for x in pb]
    mm = [(x + y) / 2 for x, y in zip(pa, pb)]
    kl = lambda p, q: sum(x * math.log2(x / y) for x, y in zip(p, q) if x > 0)
    return math.sqrt((kl(pa, mm) + kl(pb, mm)) / 2)


def quality(turns, ops, types):
    q = collections.defaultdict(list)
    created = {}
    names = collections.defaultdict(list)
    all_ids = set()
    for t, (intent, a) in enumerate(turns):
        if a is None or intent not in ops:
            continue
        pre, post = ops[intent]['preconditions'], ops[intent]['postconditions']
        slots = {**pre['slots'], **post['slots']}
        for s in slots:
            if s.endswith('_id') and a.get(s) not in (None, ''):
                all_ids.add(str(a[s]))
        for s, ty in post['slots'].items():
            v = a.get(s)
            if v in (None, '', 'None'):
                q['missing slot'].append(f'turn {t} {intent}.{s}'); continue
            if s.endswith('_id'):
                if v in created:
                    q['new entity with an existing id'].append(f'turn {t} {intent}.{s}={v} (first: {created[v]})')
                created.setdefault(v, f'turn {t} {intent}.{s}')
            d = types.get(ty, {})
            if d.get('options') and str(v) not in map(str, d['options']):
                q['value not in the allowed options'].append(f'{s}={v!r}')
            if d.get('pattern') and not re.fullmatch(d['pattern'], str(v)):
                q['value not matching the pattern'].append(f'{s}={v!r}')
            if ty in ('int', 'float', 'latitude', 'longitude', 'concentration', 'year', 'mobility_degree') or d.get('type') in ('int', 'float'):
                try: float(v)
                except (TypeError, ValueError): q['number that is not a number'].append(f'{s}={v!r}')
            if (s.endswith('_name') or s.endswith('_title')) and not s.endswith('_id'):
                cls = next((c for al, c in post['classes'].items() if s.startswith(al)), None)
                if cls:
                    names[(cls, str(v).strip().lower())].append(f'turn {t}')
        for s in slots:
            if s not in a and s.endswith('_id') and s in pre['slots']:
                q['missing slot'].append(f'turn {t} {intent}.{s}')
        lat = next((a[s] for s in a if s.endswith('latitude')), None)
        lon = next((a[s] for s in a if s.endswith('longitude')), None)
        if lat is not None and lon is not None:
            try:
                if not (34 <= float(lat) <= 72 and -25 <= float(lon) <= 45):
                    q['coordinates outside Europe'].append(f'turn {t} ({lat}, {lon})')
            except (TypeError, ValueError):
                pass
    for (cls, name), where in names.items():
        if len(where) > 1:
            q['duplicate entity (same class and name)'].append(f'{cls} "{name}" x{len(where)}')
    for t, (intent, a) in enumerate(turns):
        if a is None:
            continue
        for s, v in a.items():
            if not s.endswith('_id') and isinstance(v, str):
                leaked = [x for x in ID_RE.findall(v) if x in all_ids]
                if leaked:
                    q['identifier inside a literal value'].append(f'{s}={v!r}')
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run')
    ap.add_argument('--contract', default=None)
    ap.add_argument('--reference', default='resources/reference/ontopfas')
    ap.add_argument('--no-ttl', action='store_true')
    args = ap.parse_args()

    out_txt = os.path.join(args.run, 'output.txt')
    summary = open(out_txt).read() if os.path.exists(out_txt) else ''
    contract_path = args.contract
    if contract_path is None:
        sys.exit('please pass --contract (the run folder does not record which contract was used)')
    if not os.path.exists(contract_path):
        contract_path = os.path.join('resources/contracts', contract_path)
    c = yaml.safe_load(open(contract_path))
    ops, types, prefixes = c['intents'], c['types'], c.get('prefixes')
    if not prefixes:
        sys.exit('this contract has no `prefixes` section, so its predicates cannot be turned into IRIs')

    ref = None
    if args.reference and os.path.isdir(args.reference):
        ref = Graph()
        for f in sorted(glob.glob(os.path.join(args.reference, '*.ttl'))):
            ref.parse(f)
    report = {'run': args.run, 'contract': os.path.basename(contract_path), 'files': {}}
    print(f'=== {args.run}  ({os.path.basename(contract_path)})')
    m = re.search(r'Number of plan hallucinations: (\{.*\})', summary)
    print('  paper counters:', m.group(1) if m else 'output.txt has no summary (run interrupted before the fix?)')
    for line in summary.splitlines():
        if line.startswith(('Total time', 'Status', 'Server retries')):
            print('  ' + line)

    for f in sorted(glob.glob(os.path.join(args.run, 'triples*.json'))):
        name = os.path.basename(f)
        turns = load_turns(f)
        intents = collections.Counter(i for i, _ in turns)
        g, skipped = to_graph(turns, ops, prefixes)
        if not args.no_ttl:
            g.serialize(os.path.join(args.run, name.replace('triples', 'output').replace('.json', '.ttl')), format='turtle')
        q = quality(turns, ops, types)
        cls, prop = distribution(g)
        r = {'turns': len(turns), 'intents_used': f'{len(intents)}/{len(ops)}', 'intent_counts': dict(intents),
             'rdf_triples': len(g), 'triples_skipped': dict(skipped),
             'quality': {k: len(v) for k, v in q.items()}, 'quality_examples': {k: v[:5] for k, v in q.items()},
             'classes': dict(cls), 'properties': dict(prop)}
        print(f'\n  --- {name}: {len(turns)} turns, {r["intents_used"]} intents, {len(g)} RDF triples'
              + (f', skipped {dict(skipped)}' if skipped else ''))
        if q:
            for k, v in sorted(q.items(), key=lambda kv: -len(kv[1])):
                print(f'    {k:42} {len(v):4}   e.g. {"; ".join(v[:2])[:110]}')
        else:
            print('    no quality problems found')
        if ref is not None:
            rc, rp = distribution(ref, mapped=True)
            for what, a, b in (('classes', cls, rc), ('properties', prop, rp)):
                union = sorted(set(a) | set(b)); shared = sorted(set(a) & set(b))
                ju, js = js_distance(a, b, union), js_distance(a, b, shared)
                r[f'js_{what}_union'] = ju; r[f'js_{what}_shared'] = js
                only_gen = sorted(set(a) - set(b)); only_ref = sorted(set(b) - set(a))
                print(f'    JS {what:10} union {ju:.3f} | shared ({len(shared)}) {js:.3f}' if ju is not None and js is not None
                      else f'    JS {what}: n/a')
                print(f'       only generated: {", ".join(only_gen[:10])}{" ..." if len(only_gen) > 10 else ""}')
                print(f'       only reference: {", ".join(only_ref[:10])}{" ..." if len(only_ref) > 10 else ""}')
        report['files'][name] = r
    with open(os.path.join(args.run, 'evaluation.json'), 'w') as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False, default=str)
    print(f'\n  saved {os.path.join(args.run, "evaluation.json")}')


if __name__ == '__main__':
    main()
