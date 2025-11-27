import conf
import requests
from time import time
from conf import entities, bcolors, ops, hallucinations, ont_uri, g, prefixes, ids, fuseki, fuseki_headers
from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import URIRef, Literal, RDF
from agents import parser_agent, abox_agent
from functions import get_slots_model, get_intent_model, replace_ids, validate_plan
from collections import defaultdict
from pydantic_ai import UnexpectedModelBehavior
from dialogue import instructions, get_dialogue

validate_plan(instructions)

for i in instructions:

    dialogue = get_dialogue(instructions[i])
    dialogue = replace_ids(dialogue, ids)
    hallucinations['total_intents'] += len(list(dialogue))
    print(f"{bcolors.FAIL}============================== {i} =============================={bcolors.ENDC}")

    d = 1
    while d <= len(list(dialogue)):

        t = dialogue[str(d)]
        intent = t['Intent']
        question = t['A']
        answer = t['B']
        slots_model = get_slots_model(intent, ops[intent])
        output_model = get_intent_model(intent, ops[intent])

        print(f"{bcolors.WARNING}Question: {intent}{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Answer: {question}{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Intent: {answer}{bcolors.ENDC}")

        try:
            start = time()
            slots_answer = parser_agent.run_sync(user_prompt=f"""
                ### ROLE ###
                You are a specialized information extraction agent.
                Your task is to extract the slot values required to fulfill a specific intent from a given input question.

                ### REQUIRED SLOTS ###
                {list(ops[intent]['preconditions']['slots'])}

                ### INSTRUCTIONS ###
                - Read the input question carefully.
                - Identify and extract the values that correspond to each slot.
                - Do not invent or paraphrase data — use only what appears in the text.
                - If a slot is not present in the text, write 'none' in the output
                - After having identified the slots, return them in a JSON format

                ### INPUT QUESTION ###
                {question}
            """, output_type=slots_model)
            conf.parsing_time += time() - start

        except UnexpectedModelBehavior as e:
            hallucinations['tbox_model_failures'] += 1
            print(e)
            continue

        slots = slots_answer.output.model_dump()
        for _, s in slots.items():
            if s == 'none':
                hallucinations['unspecified_slot'] += 1

        print(f"{bcolors.WARNING}Slots: {slots}{bcolors.ENDC}")

        try:
            start = time()
            answer_text = abox_agent.run_sync(user_prompt=f"""
                    ### ROLE ###
                    You are a specialized information extraction agent.
                    Your task is to extract the slot values required to fulfill a specific intent from a given text.

                    ### INTENT CONTEXT ###
                    Intent name: {intent}
                    Required slots: {list(ops[intent]['postconditions']['slots'])}

                    ### INSTRUCTIONS ###
                    - Read the text carefully.
                    - Identify and extract the values that correspond to each slot.
                    - If a slot value corresponding to an id is missing from the text, generate a new one on the spot
                    - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
                    - Do not invent or paraphrase data — use only what appears in the text.
                    - After having identified the slots, return them in a JSON object that uses the names of the slots

                    ### INPUT TEXT ###
                    {answer}
                """, output_type=output_model)
            conf.parsing_time += time() - start
            answer = answer_text.output.model_dump()

        except UnexpectedModelBehavior as e:
            hallucinations['abox_model_failures'] += 1
            print(e)
            continue

        for a in answer:
            answer[a] = answer[a].replace("'", "")

        print(f"{bcolors.OKCYAN}Data:{bcolors.ENDC}")
        print(f'{bcolors.OKCYAN}{answer}{bcolors.ENDC}')

        if answer != {}:
            tmp = defaultdict(dict)
            prefix = ''
            for k, v in answer.items():
                if '_' in k:
                    prefix, subkey = '_'.join(k.split('_')[:-1]), k.split('_')[-1]
                    tmp[prefix][subkey] = v
                    if subkey == 'id':
                        ids.append(v)
            if len(prefix) != 0:
                entities[prefix].append(tmp[prefix])


        for t in ops[intent]["postconditions"]["triples"]:

            if t[0] in ops[intent]['postconditions']['slots']:
                sub = URIRef(f"{ont_uri}{answer[t[0]]}")
            elif t[0] in ops[intent]['preconditions']['slots']:
                sub = URIRef(f"{ont_uri}{slots[t[0]]}")

            if t[2] in ops[intent]['postconditions']['slots']:
                if ops[intent]['postconditions']['slots'][t[2]] == "id":
                    obj = URIRef(f"{ont_uri}{answer[t[2]]}")
                else:
                    obj = Literal(f"{answer[t[2]]}")
            elif t[2] in ops[intent]['preconditions']['slots']:
                obj = URIRef(f"{ont_uri}{slots[t[2]]}")
            else:
                obj = URIRef(f"{ont_uri}{t[2]}")
            if t[1] != "type":
                pred = URIRef(f"{ont_uri}{t[1]}")
            else:
                pred = RDF.type

            if 'http' in obj:
                f_obj = '<' + str(obj) + '>'
            else:
                f_obj = '"' + str(obj) + '"'

            fuseki_triple = f"<{sub}> <{pred}> {f_obj}"
            response = requests.post(fuseki, data=fuseki_triple.encode('utf-8'), headers=fuseki_headers)
            print(response.status_code, response.text)

            g.add((sub, pred, obj))
            DeductiveClosure(OWLRL_Semantics).expand(g)

        d += 1

print(f'\n{bcolors.OKGREEN}Generated data:{bcolors.ENDC}\n')

sparql = f"""
    {prefixes}

    SELECT ?s ?p ?o
    WHERE {{
        ?s ?p ?o .
        FILTER(STRSTARTS(STR(?s), STR(lubm:))) .
        FILTER(
            STRSTARTS(STR(?p), STR(lubm:)) ||
            STRENDS(STR(?p), "type")
        ) .
        FILTER(
            isLiteral(?o) ||
            STRSTARTS(STR(?o), STR(lubm:))
        )
    }}
"""
res = g.query(sparql)

for t in res:
    print(t.s, t.p, t.o)

print(f"\nNumber of plan hallucinations: {hallucinations}")
print(f"Total model time: {conf.model_time}\nTotal parsing time: {conf.parsing_time}")