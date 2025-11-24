import conf
from time import time
from conf import entities, bcolors, ops, hallucinations, ont_uri, g, prefixes, ids, dot_graph, img, model_time
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
                #sub_label = answer[t[0]]
            elif t[0] in ops[intent]['preconditions']['slots']:
                sub = URIRef(f"{ont_uri}{slots[t[0]]}")
                #sub_label = slots[t[0]]
            #if not dot_graph.get_node(f'\t{sub_label}'):
                #dot_graph.add_node(pydot.Node(sub_label, label=sub_label))

            if t[2] in ops[intent]['postconditions']['slots']:
                if ops[intent]['postconditions']['slots'][t[2]] == "id":
                    obj = URIRef(f"{ont_uri}{answer[t[2]]}")
                    #obj_label = answer[t[2]]
                    #if not dot_graph.get_node(f'\t{obj_label}'):
                        #dot_graph.add_node(pydot.Node(obj_label, label=obj_label))
                else:
                    obj = Literal(f"{answer[t[2]]}")
                    #obj_label = f'{sub_label}_{t[1]}'
                    #dot_graph.add_node(pydot.Node(obj_label, label=answer[t[2]]))
            elif t[2] in ops[intent]['preconditions']['slots']:
                obj = URIRef(f"{ont_uri}{slots[t[2]]}")
                #obj_label = slots[t[2]]
                #if not dot_graph.get_node(f'\t{slots[t[2]]}'):
                    #dot_graph.add_node(pydot.Node(obj_label, label=obj_label))
            else:
                obj = URIRef(f"{ont_uri}{t[2]}")
                #obj_label = f'{sub_label}_{t[1]}'
                #dot_graph.add_node(pydot.Node(obj_label, label=t[2]))

            if t[1] != "type":
                pred = URIRef(f"{ont_uri}{t[1]}")
            else:
                pred = RDF.type
            #dot_graph.add_edge(pydot.Edge(sub_label, obj_label, label=t[1]))

            g.add((sub, pred, obj))
            DeductiveClosure(OWLRL_Semantics).expand(g)
            # dot_graph.write_png(f'../resources/img/graph_{img}.png')
            img += 1

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