from time import time
import requests
import conf
from ABox import num_abox, ABox
from conf import bcolors, ops, ont_uri, hallucinations, prefixes, ont_prefix, fuseki, fuseki_headers
from owlrl import DeductiveClosure, OWLRL_Semantics
from agents import abox_agent
from rdflib import URIRef, RDF, Literal
from dialogue import dialogue_list, input_tokens, output_tokens
from functions import get_intent_model_tM, replace_ids_tM
from pydantic_ai import UnexpectedModelBehavior

i = 1
abox_list = []
ids = []
for n in range(num_abox):
    abox_list.append(ABox(n))
    ids.append(list())

hallucinations['total_intents'] = len(list(ops))

while i <= len(list(dialogue_list)):

    t = dialogue_list[str(i)]
    intent = t['Intent']
    question = t['Q']
    answer = []
    for n in range(num_abox):
        answer.append(t[f'A{n+1}'])

    if intent not in list(ops):
        hallucinations['unknown_intent'] += 1
        i += 1
        continue

    output_model = get_intent_model_tM(intent, ops[intent])

    print(f"{bcolors.FAIL}====================================TURN {i}===================================={bcolors.ENDC}")
    print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
    print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")

    for n in range(num_abox):

        abox = abox_list[n]
        print(f"{bcolors.WARNING}[A{n+1}] Answer: {answer[n]}{bcolors.ENDC}")

        start = time()
        try:
            answer_text = abox_agent.run_sync(user_prompt=f"""
                    ### ROLE ###
                    You are a specialized information extraction agent.
                    Your task is to extract the slot values required to fulfill a specific intent from a given text.
    
                    ### INTENT CONTEXT ###
                    Intent name: {intent}
                    Required slots: {list(ops[intent]['postconditions']['slots'])
                                              .extend(list(ops[intent]['preconditions']['slots']))}
    
                    ### INSTRUCTIONS ###
                    - Read the text carefully.
                    - Identify and extract the values that correspond to each slot.
                    - If a slot value corresponding to an id is missing from the text, generate a new one on the spot
                    - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
                    - Do not invent or paraphrase data — use only what appears in the text.
    
                    ### INPUT TEXT ###
                    {answer[n]}
                """, output_type=output_model)
            answer_slots, new_ids = replace_ids_tM(answer_text.output.model_dump(), ids[n], intent)
            ids[n] = new_ids

        except UnexpectedModelBehavior as e:
            hallucinations['tbox_model_failures'] += 1
            print(e)
            continue
        conf.parsing_time += time() - start

        print(f"{bcolors.OKCYAN}[A{n+1}] Data: {answer_slots}{bcolors.ENDC}")

        for t in ops[intent]["postconditions"]["triples"]:
            if t[0] in ops[intent]['postconditions']['slots']:
                sub = URIRef(f"{ont_uri}{answer_slots[t[0]]}")
            elif t[0] in ops[intent]['preconditions']['slots']:
                sub = URIRef(f"{ont_uri}{answer_slots[t[0]]}")
            pred = URIRef(f"{ont_uri}{t[1]}") if t[1] != "type" else RDF.type
            if t[2] in ops[intent]['postconditions']['slots']:
                if ops[intent]['postconditions']['slots'][t[2]] == "id":
                    obj = URIRef(f"{ont_uri}{answer_slots[t[2]]}")
                else:
                    obj = Literal(f"{answer_slots[t[2]]}")
            elif t[2] in ops[intent]['preconditions']['slots']:
                obj = URIRef(f"{ont_uri}{answer_slots[t[2]]}")
            else:
                obj = URIRef(f"{ont_uri}{t[2]}")

            if 'http' in obj:
                f_obj = '<' + str(obj) + '>'
            else:
                f_obj = '"' + str(obj) + '"'

            fuseki_triple = f"<{sub}> <{pred}> {f_obj}"
            response = requests.post(fuseki, data=fuseki_triple.encode('utf-8'), headers=fuseki_headers)
            print(response.status_code, response.text)

            abox.graph.add((sub, pred, obj))
            DeductiveClosure(OWLRL_Semantics).expand(abox.graph)

    i += 1

print(f'\n{bcolors.OKGREEN}Generated data:{bcolors.ENDC}\n')

sparql = f"""
    {prefixes}

    SELECT ?s ?p ?o
    WHERE {{
        ?s ?p ?o .
        FILTER(STRSTARTS(STR(?s), STR({ont_prefix}:))) .
        FILTER(
            STRSTARTS(STR(?p), STR({ont_prefix}:)) ||
            STRENDS(STR(?p), "type")
        ) .
        FILTER(
            isLiteral(?o) ||
            STRSTARTS(STR(?o), STR({ont_prefix}:))
        )
    }}
"""
res = []
for n in range(num_abox):
    res.append(abox_list[n].graph.query(sparql))

for n in range(num_abox):
    print(f"Result of A-Box {n}:")
    for t in res[n]:
        print(t.s, t.p, t.o)

print(f"\nNumber of plan hallucinations: {hallucinations}")
print(f"Total model time: {conf.model_time}\nTotal parsing time: {conf.parsing_time}")