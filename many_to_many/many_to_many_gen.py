import conf
import requests
import ast
from agents import parser_agent
from conf import hallucinations, bcolors, ops, ont_uri, fuseki, fuseki_headers, instructions_loop, num_abox, instructions, g
from time import time
from rdflib import URIRef, Literal, RDF
from functions import get_intent_model_tM, replace_ids_tM, refactor_dialogue, dict_replace
from json_repair import repair_json
from pydantic_ai import UnexpectedModelBehavior
from many_to_many.dialogue import gen_dialogue

def __launch__(triples):

    inst = next(instructions_loop)
    n_t = 0
    gen = 0
    k = 0
    for n in range(num_abox):
        conf.ids.append(list())

    while n_t < triples:

        k += 1
        if inst == list(instructions)[0]:
            gen += 1
            k = 1
            conf.chat_history = []
            conf.ids.clear()
            for n in range(num_abox):
                conf.ids.append(list())

        dialogue_list = refactor_dialogue(gen_dialogue(instructions[inst]))

        i = 1
        while i <= len(list(dialogue_list)):

            t = dialogue_list[str(i)]
            intent = t['Intent']
            question = t['Q']
            answer = []
            for n in range(num_abox):
                answer.append(t[f'A{n + 1}'])

            if intent not in list(ops):
                hallucinations['dictionary_hallucination'] += 1
                i += 1
                continue

            output_model = get_intent_model_tM(intent, ops[intent])

            print(f"{bcolors.FAIL}====================================GEN {gen}.{k} - TURN {i}===================================={bcolors.ENDC}")
            print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
            print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")

            for n in range(num_abox):
                print(f"{bcolors.WARNING}[A{n + 1}] Answer: {answer[n]}{bcolors.ENDC}")

                start = time()

                try:
                    answer_text = parser_agent.run_sync(user_prompt=f"""
                        ### ROLE ###
                        You are a specialized information extraction agent.
                        Your task is to extract the slot values required to fulfill a specific intent from a given text.

                        ### INTENT CONTEXT ###
                        Intent name: {intent}
                        Intent description: {ops[intent]['preconditions']['description']}
                        Required data slots: {list(ops[intent]['postconditions']['slots'])
                                              .extend(list(ops[intent]['preconditions']['slots']))}

                        ### INSTRUCTIONS ###
                        - Read the text carefully.
                        - Identify and extract the values that correspond to each data slot.
                        - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
                        - Do not invent or paraphrase data — use only what appears in the text.
                        - After having identified the data slots, return them in a JSON object that uses the names of the slots

                        ### INPUT TEXT ###
                        {answer[n]}
                    """, output_type=output_model)
                    parse_time = time() - start
                    slots = dict_replace('null', 'None', answer_text.output.model_dump())

                except UnexpectedModelBehavior as e:
                    hallucinations['parser_failures'] += 1
                    print(e)

                    slots_answer = parser_agent.run_sync(user_prompt=f"""
                        ### ROLE ###
                        You are a specialized information extraction agent.
                        Your task is to extract the slot values required to fulfill a specific intent from a given text.

                        ### INTENT CONTEXT ###
                        Intent name: {intent}
                        Intent description: {ops[intent]['preconditions']['description']}
                        Required data slots: {list(ops[intent]['postconditions']['slots'])
                                              .extend(list(ops[intent]['preconditions']['slots']))}

                        ### INSTRUCTIONS ###
                        - Read the text carefully.
                        - Identify and extract the values that correspond to each data slot.
                        - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
                        - Do not invent or paraphrase data — use only what appears in the text.
                        - After having identified the data slots, return them in a JSON object that uses the names of the slots

                        ### OUTPUT FORMAT ###
                        Return a JSON dictionary like:
                        {{
                          "<slot1>": "<value-or-null>",
                          "<slot2>": "<value-or-null>",
                          ...
                        }}

                        ### INPUT TEXT ###
                        {answer[n]}
                    """)
                    parse_time = time() - start
                    slots = ast.literal_eval(repair_json(slots_answer.output).replace('null', 'None'))

                conf.timestamps.append({'role': 'parsing', 'time': parse_time})
                slots, conf.ids[n] = replace_ids_tM(slots, conf.ids[n], intent)

                for s in slots:
                    slots[s] = slots[s].replace("'", "")

                print(f"{bcolors.OKCYAN}[A{n + 1}] Data: {slots}{bcolors.ENDC}")

                for v in slots.values():
                    if v == 'None' or v is None:
                        hallucinations['unspecified_slot'] += 1

                for t in ops[intent]["postconditions"]["triples"]:

                    if t[0] not in slots or slots[t[0]] == 'None' or slots[t[0]] is None:
                        continue

                    if t[2] not in slots or slots[t[2]] == 'None' or slots[t[2]] is None:
                        continue

                    if t[0] in ops[intent]['postconditions']['slots'] or t[0] in ops[intent]['preconditions']['slots']:
                        sub = URIRef(f"{ont_uri}{f'A{n}G{gen}_' + slots[t[0]]}")
                    else:
                        print(f"{bcolors.FAIL}No slots named {t[0]} in the {intent} intent!")
                        hallucinations['dictionary_hallucination'] += 1
                        continue

                    pred = URIRef(f"{ont_uri}{t[1]}") if t[1] != "type" else RDF.type

                    if t[2] in ops[intent]['postconditions']['slots']:
                        if ops[intent]['postconditions']['slots'][t[2]] == "id":
                            obj = URIRef(f"{ont_uri}{f'A{n}G{gen}_' + slots[t[2]]}")
                        else:
                            obj = Literal(f"{slots[t[2]]}")
                    elif t[2] in ops[intent]['preconditions']['slots']:
                        obj = URIRef(f"{ont_uri}{f'A{n}G{gen}_' + slots[t[2]]}")
                    else:
                        obj = URIRef(f"{ont_uri}{t[2]}")

                    g.add((sub, pred, obj))
                    n_t += 1

                    if 'http' in obj:
                        f_obj = '<' + str(obj) + '>'
                    else:
                        f_obj = '"' + str(obj) + '"'

                    fuseki_triple = f"<{sub}> <{pred}> {f_obj}"
                    requests.post(fuseki, data=fuseki_triple.encode('utf-8'), headers=fuseki_headers)

            i += 1
        inst = next(instructions_loop)

    print(f"\nNumber of plan hallucinations: {hallucinations}")