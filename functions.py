import re
import conf
import random
import requests
from conf import ont_prefix, ops, hallucinations, prefixes, sq, ont_uri, types_def, redis
from pydantic import create_model
from collections import defaultdict
from pydantic_ai import UnexpectedModelBehavior

def get_intent_model(i, intent):
    fields = {}
    for name, type_ in intent["postconditions"].get("slots", {}).items():
        py_type = str
        if type_ in types_def:
            py_type = types_def[type_]['def']
        fields[name] = (py_type, ...)
    model = create_model(f"{i}Model", **fields)
    return model

def get_intent_model_tM(i, intent):
    fields = {}
    for name, type_ in intent["postconditions"].get("slots", {}).items():
        py_type = str
        if type_ in types_def:
            py_type = types_def[type_]['def']
        fields[name] = (py_type, ...)
    for name, type_ in intent["preconditions"].get("slots", {}).items():
        py_type = str
        if type_ in types_def:
            py_type = types_def[type_]['def']
        fields[name] = (py_type, ...)
    model = create_model(f"{i}Model", **fields)
    return model

def get_slots_model(i, intent):
    fields = {}
    for name, type_ in intent["preconditions"].get("slots", {}).items():
        py_type = str
        if type_ in types_def:
            py_type = types_def[type_]['def']
        fields[name] = (py_type, ...)
    model = create_model(f"{i}SlotsModel", **fields)
    return model

def cap(str):
    return str[0].upper() + str[1:]

def replace_ids(slots, intent, abox):

    tmp = slots
    for k, v in slots.items():
        if '_id' in k:
            if v is None:
                v = ''.join([x.capitalize() for x in k.split("_")[:-1]]) + '001'
                hallucinations['missing_slot'] += 1
            if re.search(r'\d+$', str(v)) is None:
                continue
            if redis.sismember(f"abox{abox}:ids", v) and k not in ops[intent]['preconditions']['slots']:
                while redis.sismember(f"abox{abox}:ids", v):
                    if int(v[-1]) != 9:
                        new = v[:-1] + str(int(v[-1]) + 1)
                    else:
                        if int(v[-2]) != 9:
                            new = v[:-2] + str(int(v[-2]) + 1) + '0'
                        else:
                            new = v[:-3] + str(int(v[-3]) + 1) + '00'
                    v = new
                tmp[k] = v
            redis.sadd(f"abox:{abox}:ids", v)

    return tmp

def refactor_dialogue(dialogue):

    ref_dialogue = defaultdict(dict)
    i = 1
    for t in dialogue:
        ref_dialogue.update({str(i): dialogue[t]})
        i += 1

    return ref_dialogue

def dict_replace(_old, _new, dict):
    for k, v in dict.items():
        if v == _old:
            dict[k] = _new
    return dict

def camel_to_snake(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def dict_keys_to_snake(d):
    return {camel_to_snake(k): v for k, v in d.items()}


def check_preconditions(classes, slots, prefix):
    """
    For each class in `classes`, checks if the instance with the ID in `slots`
    exists as rdf:type of that class in Fuseki.

    Returns:
        missing_count (int): number of missing rdf:type triples
    """

    fuseki_query_endpoint = conf.fuseki_query
    base_ontology_uri = conf.ont_uri
    base_resource_uri = conf.ont_uri
    missing_count = 0

    for key, class_name in classes.items():

        slot_key = f"{key}_id"
        if slot_key not in slots:
            continue
        if slot_key not in slots or slots[slot_key] is None or slots[slot_key] == 'None':
            continue

        instance_id = slots[slot_key]

        subject_uri = f"<{base_resource_uri}{prefix}{instance_id}>"

        # Build full list of valid types
        if isinstance(conf.subclasses, dict):
            subclass_list = conf.subclasses.get(class_name, [])
        else:
            subclass_list = []

        valid_types = [class_name] + subclass_list

        # Convert to full URIs
        class_uris = " ".join(
            f"<{base_ontology_uri}{c}>" for c in valid_types
        )

        query = f"""
            ASK {{
                VALUES ?type {{ {class_uris} }}
                {subject_uri} a ?type .
            }}
            """

        response = requests.get(
            fuseki_query_endpoint,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"}
        )

        if response.status_code != 200:
            continue

        result = response.json()

        if not result.get("boolean", False):
            missing_count += 1
            print(f'{subject_uri} not found')

    conf.hallucinations['false_precondition'] += missing_count

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

import re

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