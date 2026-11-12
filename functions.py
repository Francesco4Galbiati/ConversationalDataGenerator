import json
import re
import conf
from conf import ops, hallucinations, redis

def least_used_precondition_ids(intents, *, mode="one_to_one"):
    """Return the least-used eligible IDs separately for each intent and slot."""
    suffix = ":idx0" if mode == "many_to_many" else ""
    eligible = {}
    offered = {}
    for intent in intents:
        offered[intent] = {}
        for slot in ops[intent]["preconditions"]["slots"]:
            if slot not in eligible:
                eligible[slot] = sorted(redis.smembers(f"entities:{slot}{suffix}"))
            ids = eligible[slot]
            if not ids:
                offered[intent][slot] = []
                continue
            key = f"precondition_usage:{mode}:{intent}:{slot}"
            counts = [int(count or 0) for count in redis.hmget(key, ids)]
            minimum = min(counts)
            offered[intent][slot] = [entity for entity, count in zip(ids, counts) if count == minimum]
    return offered

def _next_id(v):
    """ACT009 -> ACT010, PFS099 -> PFS100: increment the trailing number, keep its width."""
    m = re.match(r'^(.*?)(\d+)$', v)
    return m.group(1) + str(int(m.group(2)) + 1).zfill(len(m.group(2)))

def replace_ids(slots, intent, abox):
    """Make every NEW id (postcondition id slot) unique within this world (abox).
    Ids of precondition slots refer to existing entities and are left unchanged.
    All ids seen are recorded in the Redis set abox:<abox>:ids."""
    key = f"abox:{abox}:ids"
    pre = ops[intent]['preconditions']['slots']
    for k in list(slots):
        if '_id' not in k:
            continue
        v = slots[k]
        if v is None:
            v = ''.join([x.capitalize() for x in k.split("_")[:-1]]) + '001'
            hallucinations['missing_slot'] += 1
        v = str(v)
        if re.search(r'\d+$', v) is None:
            continue
        if k not in pre and redis.sismember(key, v):
            while redis.sismember(key, v):
                v = _next_id(v)
            slots[k] = v
        redis.sadd(key, v)

    return slots

def write_answer(intent, answer, answerer_id=None):
    """Append one turn to the output file, after ids have been corrected.
    answerer_id is None for single-witness modes (triples.json), else the witness index (triples_<i>.json)."""
    path = conf.triples_file if answerer_id is None else conf.triples_files[int(answerer_id)]
    with open(path, 'a') as f:
        f.write(f'{intent}: ' + json.dumps(answer) + '\n')

def camel_to_snake(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def dict_keys_to_snake(d):
    return {camel_to_snake(k): v for k, v in d.items()}

def update_world_state(answer, intent, answerer_id=''):
    intent_def = ops[intent]

    # 1. Save entities (unchanged)
    for slot in intent_def['postconditions']['slots']:
        val = answer.get(slot)
        if val not in [None, 'None']:
            redis.sadd(f"entities:{slot}{answerer_id}", val)

    # 2. Save ONLY teacherOf triples
    for triple in intent_def['postconditions'].get('triples', []):
        s, p, o = triple

        if p != "likes" and p != "dislikes":
            continue

        # resolve subject (must be an ID slot)
        s_val = answer.get(s) if s.endswith('_id') else s

        # resolve object
        o_val = answer.get(o) if isinstance(o, str) and o.endswith('_id') else o

        if s_val in [None, 'None'] or o_val in [None, 'None']:
            continue

        redis.sadd(f"{p}{answerer_id}", f"{s_val}|{o_val}")

def parse_rdf_triples(rdf_text):
    """
    Parses N-Triples like:
    <s> <p> <o> .
    Returns list of (s, p, o)
    """
    triples = []
    
    lines = rdf_text.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or not line.endswith('.'):
            continue
        
        # basic N-triples parsing
        match = re.match(r'<([^>]*)>\s+<([^>]*)>\s+(.*)\s+\.', line)
        if not match:
            continue
        
        s = match.group(1)
        p = match.group(2)
        o_raw = match.group(3).strip()

        # object can be URI or literal
        if o_raw.startswith('<'):
            o = o_raw.strip('<>')
        else:
            # literal
            o = o_raw.strip('"')

        triples.append((s, p, o))
    
    return triples

def update_world_state_rdf(rdf_text, intent, answerer_id=''):
    triples = parse_rdf_triples(rdf_text)
    intent_triples = ops[intent]['postconditions']['triples']

    # slot → collected values
    slot_values = {}

    for (s, p, o) in triples:
        for (s_slot, pred, o_slot) in intent_triples:
            
            # match predicate
            if p != pred:
                continue

            # resolve subject slot
            if s_slot.endswith('_id'):
                slot_values.setdefault(s_slot, set()).add(s)

            # resolve object slot
            if isinstance(o_slot, str) and o_slot.endswith('_id'):
                slot_values.setdefault(o_slot, set()).add(o)

            elif isinstance(o_slot, str) and not o_slot.endswith('_id'):
                # literal slot (e.g. name)
                slot_values.setdefault(o_slot, set()).add(o)

    # store in redis (same logic as before)
    for slot, values in slot_values.items():
        if any(x in slot for x in conf.repeatable_terms):
            continue

        for val in values:
            if val not in [None, 'None']:
                redis.sadd(f"entities:{slot}{answerer_id}", val)
