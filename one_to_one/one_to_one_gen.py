import requests
from pydantic_ai import UnexpectedModelBehavior
from rdflib import URIRef, RDF, Literal
from functions import get_intent_model, get_slots_model, get_id_from_slots
from agents import abox_agent, parser_agent
from conf import bcolors, ops, ont_uri, g, hallucinations, prefixes, fuseki, fuseki_headers
from owlrl import DeductiveClosure, OWLRL_Semantics
from dialogue import dialogue_list

i = 1

hallucinations['total_intents'] = len(list(ops))

while i < len(list(dialogue_list)):

    t = dialogue_list[str(i)]
    intent = t['Intent']
    question = t['A']
    answer = t['B']

    if intent not in list(ops):
        hallucinations['unknown_intent'] += 1
        continue

    slots_model = get_slots_model(intent, ops[intent])
    output_model = get_intent_model(intent, ops[intent])

    print(f"{bcolors.FAIL}====================================TURN {i}===================================={bcolors.ENDC}")
    print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
    print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")
    print(f"{bcolors.WARNING}Answer: {answer}{bcolors.ENDC}")

    try:
        slots_answer = abox_agent.run_sync(user_prompt=f"""
            ### ROLE ###
            You are a specialized information extraction agent.
            Your task is to extract the slot values required to fulfill a specific intent from a given text.

            ### INTENT CONTEXT ###
            Intent name: {intent}
            Required slots: {list(ops[intent]['preconditions']['slots'])}

            ### INSTRUCTIONS ###
            - Read the text carefully.
            - Identify and extract the values that correspond to each slot.
            - If a slot value corresponding to an id is missing from the text, generate a new one on the spot
            - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
            - Do not invent or paraphrase data — use only what appears in the text.
            - After having identified the slots, return them in a JSON object that uses the names of the slots
            
            ### INPUT TEXT ###
            {question}
        """, output_type=slots_model)

    except UnexpectedModelBehavior as e:
        hallucinations['tbox_model_failures'] += 1
        print(e)
        continue

    try:
        slots = get_id_from_slots(slots_answer.output.model_dump())
    except UnexpectedModelBehavior as e:
        hallucinations['false_precondition'] += 1
        i += 1
        continue

    print(f"{bcolors.WARNING}Slots: {slots}{bcolors.ENDC}")

    try:
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
        answer = answer_text.output.model_dump()

    except UnexpectedModelBehavior as e:
        hallucinations['abox_model_failures'] += 1
        print(e)
        continue

    for a in answer:
        answer[a] = answer[a].replace("'", "")

    print(f"{bcolors.OKCYAN}Data:{bcolors.ENDC}")
    print(f'{bcolors.OKCYAN}{answer}{bcolors.ENDC}')

    for t in ops[intent]["postconditions"]["triples"]:
        if t[0] in ops[intent]['postconditions']['slots']:
            sub = URIRef(f"{ont_uri}{answer[t[0]]}")
        elif t[0] in ops[intent]['preconditions']['slots']:
            sub = URIRef(f"{ont_uri}{slots[t[0]]}")
        pred = URIRef(f"{ont_uri}{t[1]}") if t[1] != "type" else RDF.type
        if t[2] in ops[intent]['postconditions']['slots']:
            if ops[intent]['postconditions']['slots'][t[2]] == "id":
                obj = URIRef(f"{ont_uri}{answer[t[2]]}")
            else:
                obj = Literal(f"{answer[t[2]]}")
        elif t[2] in ops[intent]['preconditions']['slots']:
            obj = URIRef(f"{ont_uri}{slots[t[2]]}")
        else:
            obj = URIRef(f"{ont_uri}{t[2]}")
        g.add((sub, pred, obj))

        if 'http' in obj:
            f_obj = '<' + obj + '>'
        else:
            f_obj = '"' + obj + '"'

        fuseki_triple = f"<{sub}> <{pred}> {f_obj}"
        response = requests.post(fuseki, data=fuseki_triple.encode('utf-8'), headers=fuseki_headers)
        print(response.status_code, response.text)

        DeductiveClosure(OWLRL_Semantics).expand(g)

    i += 1

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