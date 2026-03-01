import ast
import conf
import asyncio
import requests
from time import time
from conf import bcolors, ops, hallucinations, ont_uri, g, fuseki, fuseki_headers, instructions, instructions_loop, \
    parallelization
from rdflib import URIRef, Literal, RDF
from agents import parser_agent, abox_agent
from functions import get_slots_model, get_intent_model, replace_ids, refactor_dialogue, dict_replace, \
    dict_keys_to_snake, check_preconditions
from json_repair import repair_json
from pydantic_ai import UnexpectedModelBehavior
from many_to_one.dialogue import gen_dialogue, gen_dialogue_async


async def __launch__(triples):

    n_t = 0
    gen = 0
    k = 0
    next_dialogue = None

    while n_t < triples:

        inst = next(instructions_loop)
        k += 1
        clear = False
        if inst == list(instructions)[0]:
            conf.ids = []
            gen += 1
            k = 1

        if parallelization:

            if inst == list(instructions)[len(instructions)-1]:
                clear = True
            if n_t == 0:
                parser_agent.run(user_prompt='')
                dialogue_list = gen_dialogue(instructions[inst], clear)
                inst = next(instructions_loop)
                next_dialogue = asyncio.create_task(gen_dialogue_async(instructions[inst], clear))
            else:
                dialogue_list = await next_dialogue
                inst = next(instructions_loop)
                next_dialogue = asyncio.create_task(gen_dialogue_async(instructions[inst], clear))
        else:

            if inst == list(instructions)[0]:
                clear = True
            dialogue_list = gen_dialogue(instructions[inst], clear)

        dialogue_list = refactor_dialogue(dialogue_list)

        i = 1
        while i <= len(list(dialogue_list)):

            t = dialogue_list[str(i)]
            if "Intent" not in t or 'Q' not in t or 'A' not in t:
                hallucinations['dictionary_hallucination'] += 1
                continue
            intent = t['Intent']
            question = t['Q']
            answer = t['A']

            if intent not in list(ops):
                hallucinations['dictionary_hallucination'] += 1
                i += 1
                continue

            slots_model = get_slots_model(intent, ops[intent])
            output_model = get_intent_model(intent, ops[intent])

            print(f"{bcolors.FAIL}====================================GEN {gen}.{k} - TURN {i}===================================={bcolors.ENDC}")
            print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
            print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")
            print(f"{bcolors.WARNING}Answer: {answer}{bcolors.ENDC}")

            start = time()
            if len(list(ops[intent]['preconditions']['slots'])) != 0:
                try:
                    slots_answer = parser_agent.run_sync(user_prompt=f"""
                        ### ROLE ###
                        You are a specialized information extraction agent.
                        Your task is to extract the slot values required to fulfill a specific intent from a given text.
    
                        ### INTENT CONTEXT ###
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
                    """, output_type=slots_model)
                    end = time()
                    slots = dict_replace('null', 'None', slots_answer.output.model_dump())

                except UnexpectedModelBehavior as e:
                    hallucinations['parser_failures'] += 1
                    print(e)

                    slots_answer = abox_agent.run_sync(user_prompt=f"""
                        ### ROLE ###
                        You are a specialized information extraction agent.
                        Your task is to extract the slot values required to fulfill a specific intent from a given text.
    
                        ### INTENT CONTEXT ###
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
            else:
                slots = {}
                end = time()

            conf.parsing_timestamps.append({'start': start, 'end': end})
            slots = dict_keys_to_snake(slots)

            check_preconditions(ops[intent]['preconditions']['classes'], slots, f'G{gen}_')

            print(f"{bcolors.WARNING}Slots: {slots}{bcolors.ENDC}")

            start = time()
            if len(list(ops[intent]['postconditions']['slots'])) != 0:
                try:
                    start = time()
                    answer_text = parser_agent.run_sync(user_prompt=f"""
                        ### ROLE ###
                        You are a specialized information extraction agent.
                        Your task is to extract the slot values required to fulfill a specific intent from a given text.
        
                        ### INTENT CONTEXT ###
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
                    """, output_type=output_model)
                    end = time()
                    answer = dict_replace('null', 'None', answer_text.output.model_dump())

                except UnexpectedModelBehavior as e:
                    hallucinations['parser_failures'] += 1
                    print(e)

                    answer_text = parser_agent.run_sync(user_prompt=f"""
                        ### ROLE ###
                        You are a specialized information extraction agent.
                        Your task is to extract the slot values required to fulfill a specific intent from a given text.
        
                        ### INTENT CONTEXT ###
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
                    end = time()
                    answer = ast.literal_eval(repair_json(answer_text.output).replace('null', 'None'))
            else:
                answer = {}
                end = time()

            conf.parsing_timestamps.append({'start': start, 'end': end})
            answer = dict_keys_to_snake(answer)
            answer, conf.ids = replace_ids(answer, conf.ids)

            for a in answer:
                if answer[a] != 'None' and answer[a] is not None:
                    answer[a] = str(answer[a]).replace("'", "")

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

                g.add((sub, pred, obj))

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