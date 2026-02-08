import re
import random
from collections import defaultdict
from conf import ont_prefix, g, ops, hallucinations, prefixes, sq, ont_uri, types_def
from pydantic import create_model
from pydantic_ai import UnexpectedModelBehavior

def get_intent_slots(intent):

    if len(intent["preconditions"]["classes"]) == 0:
        return None
    else:
        slots = " ".join([f"?{s}" for s in list(intent["preconditions"]["slots"])])
        classes = " .\n\t\t\t\t".join([f"?{c}_id rdf:type {ont_prefix}:{intent['preconditions']['classes'][c]}" for c in intent["preconditions"]["classes"]])
        triples = " .\n\t\t\t\t".join([f"?{t[0]}_id {ont_prefix}:{t[1]} ?{t[2]}_id" for t in intent["preconditions"]["triples"]])

        sparql = f"""
            {prefixes}
            
            SELECT {slots}
            WHERE {{
                {classes} .
                {triples}
            }}
        """

        res = g.query(sparql)
        data = [
            {str(var): (str(row[var].split('#')[-1]) if row[var] is not None else None)
                for var in res.vars}
            for row in res
        ]

        if len(data) != 0:
            return random.choice(data)
        else:
            return {}

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

def get_id_from_slots(slots):

    ids = {}
    for s in slots:
        sparql = f"""
            {prefixes}
            
            SELECT *
            WHERE {{
                ?s ?p ?o .
                ?s a {ont_prefix}:{''.join([x.capitalize() for x in s.split('_')[:-1]])} .
                FILTER(STR(?s) = "{ont_uri}{slots[s].replace(" ", "").replace("'", "")}")
            }}
        """
        res = g.query(sparql)

        if len(list(res)) > 0:
            ids[s] = slots[s].replace(" ", "").replace("'", "")
        else:
            sparql = f"""
                {prefixes}
                
                SELECT ?id
                WHERE {{
                    ?id ?p "{slots[s]}" . 
                    ?id a {ont_prefix}:{s.split('_')[0].capitalize()}
                }}
            """
            res = g.query(sparql)

            if len(res) > 0:
                ids[s] = [x.id for x in res][0].split('#')[-1]
            else:
                ids[s] = None

    for i in ids:
        if ids[i] is None:
            sparql = f"""
                {prefixes}
                
                SELECT ?id
                WHERE {{
                    {{
                        {' UNION '.join([f"{{{{?id ?p {ont_prefix}:{ids[x].replace(sq, '')}}} UNION "
                            f"{{{ont_prefix}:{ids[x].replace(sq, '')} ?p ?id}}}}" for x in ids if ids[x] is not None])}
                    }}
                    {{?id a {ont_prefix}:{i.split('_')[0].capitalize()}}}
                }}
            """
            res = g.query(sparql)

            if len(res) > 0:
                ids[i] = [x.id for x in res][0].split('#')[-1]
            else:
                sparql = f"""
                    {prefixes}
                    
                    SELECT ?id
                    WHERE {{
                        ?id a {ont_prefix}:{s.split('_')[0].capitalize()}
                    }}
                """
                res = g.query(sparql)

                if len(res) > 0:
                    ids[i] = [x.id for x in res][-1].split('#')[-1]
                    hallucinations['unspecified_slot'] += 1
                else:
                    raise UnexpectedModelBehavior('False precondition')

    return ids

def cap(str):
    return str[0].upper() + str[1:]

def repair_dialogue(dialogue):
    report = []

    for t in dialogue:
        turn = t
        intent = dialogue[t]['Intent']
        question = dialogue[t]['A']

        if intent not in list(ops):
            report.append({'turn': turn, 'error': 'Unknown or missing intent'})

        for slot in ops[intent]['preconditions']['slots']:

            pattern_nq = ' '.join([x for x in slot.replace("_id", r" ([A-Z]+\d+)").split('_')])
            sub_pattern_nq = ' '.join([x for x in slot.replace("_id", r" '\1'").split('_')])
            c_pattern_nq = ' '.join([cap(x) for x in slot.replace("_id", r" ([A-Z]+\d+)").split('_')])
            sub_c_pattern_nq = ' '.join([cap(x) for x in slot.replace("_id", r" '\1'").split('_')])
            question = re.sub(pattern_nq, sub_pattern_nq, question)
            question = re.sub(c_pattern_nq, sub_c_pattern_nq, question)

            pattern = ' '.join([x for x in slot.replace("_id", r" '[A-Z]+\d+'").split('_')])
            c_pattern = ' '.join([cap(x) for x in slot.replace("_id", r" '[A-Z]+\d+'").split('_')])
            if not re.search(pattern, question) and not re.search(c_pattern, question):
                report.append(f"Add {slot} to the question in turn {turn}")

    return report

def replace_ids(slots, ids):
    tmp = slots

    for k, v in slots.items():
        if '_id' in k and v != 'null' and v != 'None' and v is not None:
            while v in ids:
                if int(v[-1]) != 9:
                    new = v[:-1] + str(int(v[-1]) + 1)
                else:
                    if int(v[-2]) != 9:
                        new = v[:-2] + str(int(v[-2]) + 1) + '0'
                    else:
                        new = v[:-3] + str(int(v[-3]) + 1) + '00'
                v = new
            tmp[k] = v
            ids.append(v)

    return tmp, ids

def replace_ids_tM(slots, ids, intent):

    tmp = slots

    for k, v in slots.items():
        if '_id' in k:
            if v is None:
                v = ''.join([x.capitalize() for x in k.split("_")[:-1]]) + '001'
                hallucinations['unspecified_slot'] += 1
            if re.search(r'\d+$', v) is None:
                continue
            if v in ids and k not in ops[intent]['preconditions']['slots']:
                while v in ids:
                    if int(v[-1]) != 9:
                        new = v[:-1] + str(int(v[-1]) + 1)
                    else:
                        if int(v[-2]) != 9:
                            new = v[:-2] + str(int(v[-2]) + 1) + '0'
                        else:
                            new = v[:-3] + str(int(v[-3]) + 1) + '00'
                    v = new
                tmp[k] = v
            ids.append(v)

    return tmp, ids


def extract_entities(dialogue):
    entities = set()
    for d in dialogue:
        entities.update(re.findall(r"[A-Z]+\d+", dialogue[d]['A']))
        entities.update(re.findall(r"[A-Z]+\d+", dialogue[d]['B']))

    return entities

def relevant_classes(instructions):
    r = set()
    for i in instructions:
        for c in set(ops[i]['preconditions']['classes']):
            r.add(c)
    return r

def validate_plan(instructions):
    classes = set()
    for intents in instructions:
        for i in instructions[intents]:
            if i not in list(ops):
                hallucinations['unknown_intent'] += 1
            for _, c in ops[i]['postconditions']['classes'].items():
                classes.add(c)
        for i in instructions[intents]:
            for _, c in ops[i]['preconditions']['classes'].items():
                if c not in classes:
                    hallucinations['false_precondition'] += 1

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