import ast
import asyncio
from json_repair import repair_json
import conf
import requests
from time import time
from pydantic_ai import UnexpectedModelBehavior
from rdflib import URIRef, RDF, Literal
from functions import get_intent_model, get_slots_model, replace_ids, refactor_dialogue, dict_replace
from agents import parser_agent, abox_agent
from conf import bcolors, ops, ont_uri, hallucinations, fuseki, fuseki_headers
from one_to_one.dialogue import gen_dialogue, gen_dialogue_async


async def __launch__(triples):

    n_t = 0
    gen = 0
    next_dialogue = None

    while n_t < triples:

        gen += 1
        conf.ids = []

        if n_t == 0:
            abox_agent.run(user_prompt="")
            dialogue_list = gen_dialogue()
            next_dialogue = asyncio.create_task(gen_dialogue_async())
        else:
            dialogue_list = await next_dialogue
            next_dialogue = asyncio.create_task(gen_dialogue_async())

        dialogue_list = refactor_dialogue(dialogue_list)

        i = 1
        while i <= len(list(dialogue_list)):

            t = dialogue_list[str(i)]
            intent = t['Intent']
            question = t['Q']
            answer = t['A']

            if intent not in list(ops):
                hallucinations['dictionary_hallucination'] += 1
                i += 1
                continue

            slots_model = get_slots_model(intent, ops[intent])
            output_model = get_intent_model(intent, ops[intent])

            print(f"{bcolors.FAIL}====================================GEN {gen} - TURN {i}===================================={bcolors.ENDC}")
            print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
            print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")
            print(f"{bcolors.WARNING}Answer: {answer}{bcolors.ENDC}")

            start = time()

            try:
                slots_answer = await abox_agent.run(user_prompt=f"""
                    ### ROLE ###
                    You are a specialized information extraction agent.
                    Your task is to extract the slot values required to fulfill a specific intent from a given text.

                    ### INTENT CONTEXT ###
                    Intent name: {intent}
                    Intent description: {ops[intent]['preconditions']['description']}
                    Required data slots: {list(ops[intent]['preconditions']['slots'])}

                    ### INSTRUCTIONS ###
                    - Read the text carefully.
                    - Identify and extract the values that correspond to each data slot.
                    - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
                    - Do not invent or paraphrase data — use only what appears in the text.
                    - After having identified the data slots, return them in a JSON object that uses the names of the slots

                    ### INPUT TEXT ###
                    {question}
                """, output_type=slots_model)
                end = time() - start
                slots = dict_replace('null', 'None', slots_answer.output.model_dump())

            except UnexpectedModelBehavior as e:
                hallucinations['parser_failures'] += 1
                print(e)

                slots_answer = await abox_agent.run(user_prompt=f"""
                    ### ROLE ###
                    You are a specialized information extraction agent.
                    Your task is to extract the slot values required to fulfill a specific intent from a given text.
    
                    ### INTENT CONTEXT ###
                    Intent name: {intent}
                    Intent description: {ops[intent]['preconditions']['description']}
                    Required data slots: {list(ops[intent]['preconditions']['slots'])}
    
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
                    {question}
                """)
                end = time()
                slots = ast.literal_eval(repair_json(slots_answer.output).replace('null', 'None'))

            conf.parsing_timestamps.append({'start': start, 'end': end})

            print(f"{bcolors.WARNING}Slots: {slots}{bcolors.ENDC}")

            start = time()
            try:
                answer_text = await parser_agent.run(user_prompt=f"""
                    ### ROLE ###
                    You are a specialized information extraction agent.
                    Your task is to extract the slot values required to fulfill a specific intent from a given text.

                    ### INTENT CONTEXT ###
                    Intent name: {intent}
                    Intent description: {ops[intent]['preconditions']['description']}
                    Required data slots: {list(ops[intent]['postconditions']['slots'])}

                    ### INSTRUCTIONS ###
                    - Read the text carefully.
                    - Identify and extract the values that correspond to each data slot.
                    - If a slot value that is not an id is missing or cannot be inferred by the text alone, set it as 'null'.
                    - Do not invent or paraphrase data — use only what appears in the text.
                    - After having identified the data slots, return them in a JSON object that uses the names of the slots.

                    ### INPUT TEXT ###
                    {answer}
                """, output_type=output_model)
                end = time()
                answer = dict_replace('null', 'None', answer_text.output.model_dump())

            except UnexpectedModelBehavior as e:
                hallucinations['parser_failures'] += 1
                print(e)

                answer_text = await parser_agent.run(user_prompt=f"""
                    ### ROLE ###
                    You are a specialized information extraction agent.
                    Your task is to extract the slot values required to fulfill a specific intent from a given text.

                    ### INTENT CONTEXT ###
                    Intent name: {intent}
                    Intent description: {ops[intent]['preconditions']['description']}
                    Required data slots: {list(ops[intent]['postconditions']['slots'])}

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
                    {answer}
                """)
                end = time() - start
                answer = ast.literal_eval(repair_json(answer_text.output).replace('null', 'None'))

            conf.parsing_timestamps.append({'start': start, 'end': end})
            answer, conf.ids = replace_ids(answer, conf.ids)

            for a in answer:
                if answer[a] != 'None' and answer[a] is not None:
                    answer[a] = answer[a].replace("'", "")

            print(f"{bcolors.OKCYAN}Data:{bcolors.ENDC}")
            print(f'{bcolors.OKCYAN}{answer}{bcolors.ENDC}')

            for v in answer.values():
                if v == 'None' or v is None:
                    hallucinations['unspecified_slot'] += 1

            for v in slots.values():
                if v == 'None' or v is None:
                    hallucinations['unspecified_slot'] += 1

            for t in ops[intent]["postconditions"]["triples"]:

                if t[0] in ops[intent]['postconditions']['slots']:
                    if t[0] not in answer or answer[t[0]] == 'None' or answer[t[0]] is None:
                        continue
                    sub = URIRef(f"{ont_uri}{f'G{gen}_' + answer[t[0]]}")
                elif t[0] in ops[intent]['preconditions']['slots']:
                    if t[0] not in slots or slots[t[0]] == 'None' or slots[t[0]] is None:
                        continue
                    sub = URIRef(f"{ont_uri}{f'G{gen}_' + slots[t[0]]}")
                else:
                    print(f"{bcolors.FAIL}No slots named {t[0]} in the {intent} intent!")
                    hallucinations['dictionary_hallucination'] += 1
                    continue

                pred = URIRef(f"{ont_uri}{t[1]}") if t[1] != "type" else RDF.type

                if t[2] in ops[intent]['postconditions']['slots']:
                    if t[2] not in answer or answer[t[2]] == 'None' or answer[t[2]] is None:
                        continue
                    if ops[intent]['postconditions']['slots'][t[2]] == "id":
                        obj = URIRef(f"{ont_uri}{f'G{gen}_' + answer[t[2]]}")
                    else:
                        obj = Literal(f"{answer[t[2]]}")
                elif t[2] in ops[intent]['preconditions']['slots']:
                    if t[2] not in slots or slots[t[2]] == 'None' or slots[t[2]] is None:
                        continue
                    obj = URIRef(f"{ont_uri}{f'G{gen}_' + slots[t[2]]}")
                else:
                    obj = URIRef(f"{ont_uri}{t[2]}")

                if 'http' in obj:
                    f_obj = '<' + str(obj) + '>'
                else:
                    f_obj = '"' + str(obj) + '"'

                fuseki_triple = f"<{sub}> <{pred}> {f_obj}"
                requests.post(fuseki, data=fuseki_triple.encode('utf-8'), headers=fuseki_headers)

                n_t += 1
                if n_t >= triples:
                    return

            i += 1
    return