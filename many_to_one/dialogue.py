import ast
import json
from collections import defaultdict

import conf
from time import time
from conf import ops, dialogue_client, async_dialogue_client
from json_repair import repair_json

def gen_dialogue(instructions):

    conf.chat_history.append({
        'role': 'system',
        'content': f"""
            --- 🧭 ROLE ---
            You are simulating a conversation between two cooperative agents exploring a section of a knowledge domain.
            - Agent Q (Questioner): asks progressively deeper questions to uncover new entities and relations.
            - Agent A (Answerer): replies with facts, descriptions, and relations according to defined intents.
            
            --- 🎯 OBJECTIVE ---
            Generate a coherent and natural dialogue that:
            - Gradually explores the domain described by the intents.
            - Uses intents only when all their preconditions are satisfied.
            - Includes at least {len(instructions) * 3} full A–B exchanges (≈{len(instructions) * 6} total turns) based
            on the intents provided below.
            - Balances frequency: large entities (e.g. Organizations) appear 1–2 times; smaller ones (e.g. People) 
            appear 3–4 times; 
            - Introduces all slot information with realistic, natural names (no placeholders).
            
            --- ⚙️ INTENTS ---
            Each intent defines an operation in the domain:
            IntentName:
                description: <summary>
                preconditions: <required classes or relations>
                slots: <values to express naturally in text>
                
            Use only these intents:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'slots': ops[i]['postconditions']['slots']
                }
            } for i in ops if i in instructions]}
            
            --- 🗣️ DIALOGUE RULES ---
            - Each A–B turn = exactly one complete intent taken from this prompt, and not from the other messages.
            - Agent Q (Questioner) must:
              - Reference all the entities in the preconditions using the IDs defined in the previous messages.
              - Explicitly mention the class of each referenced entity.
              - Ask about all knowledge provided required by the intents' slots.
            - Agent A (Answerer) must:
              - Introduce all data from the intent’s slot fields in natural text.
              - Maintain internal consistency with prior dialogue.
              - Specify a new, unique ID for any new entity (matching its class, e.g. 'S001' for Student).
              - Never mention “intent”, “precondition”, or “postcondition” explicitly.
              - Follow these type definitions when generating data:
                    {conf.newl.join([conf.types_def[t]['text'] for t in conf.types_def if t != 'id']) 
                        if len([t for t in conf.types_def if t != 'id']) != 0 else ""}
            - Include the executed intent name for every turn.
            - Do not execute partial intents (i.e. asking for only part of the information)
            
            --- 🧾 OUTPUT FORMAT ---
            JSON only — no extra commentary.
            
            Example:
            {{
              "1": {{"Intent": "<intent_name>", "Q": "...", "A": "..."}},
              "2": {{"Intent": "<intent_name>", "Q": "...", "A": "..."}}
            }}
            
            --- ✨ STYLE ---
            - Natural, concise, and contextually consistent.
            - Use realistic entity names and relationships.
            - Avoid redundancy — each turn should expand the world logically.
            - Output only the JSON, without explanations or prefixes.
        """
    })
    conf.chat_history.append({
        'role': 'user',
        'content': 'Continue the dialogue according to the system instructions, ONLY generate new dialogue exchanges,'
                   'do not rewrite old ones. Start enumerating the dialogue turns from 1.'
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model='mistral-small3.2:24b-instruct-2506-q4_K_M',
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    conf.chat_history.pop()
    conf.chat_history.pop()
    dialogue_list = ast.literal_eval(repair_json(dialogue['message']['content']))

    history_dict = defaultdict(dict)
    for k, v in dialogue_list.items():
        history_dict[k]['Q'] = v['Q']
        history_dict[k]['A'] = v['A']

    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing
            entities in a coherent way, do not modify it. {json.dumps(history_dict)}"""
    })

    return dialogue_list


async def gen_dialogue_async(instructions):
    conf.chat_history.append({
        'role': 'system',
        'content': f"""
            --- 🧭 ROLE ---
            You are simulating a conversation between two cooperative agents exploring a section of a knowledge domain.
            - Agent Q (Questioner): asks progressively deeper questions to uncover new entities and relations.
            - Agent A (Answerer): replies with facts, descriptions, and relations according to defined intents.

            --- 🎯 OBJECTIVE ---
            Generate a coherent and natural dialogue that:
            - Gradually explores the domain described by the intents.
            - Uses intents only when all their preconditions are satisfied.
            - Includes at least {len(instructions) * 3} full A–B exchanges (≈{len(instructions) * 6} total turns) based
            on the intents provided below.
            - Balances frequency: large entities (e.g. Organizations) appear 1–2 times; smaller ones (e.g. People) 
            appear 3–4 times; 
            - Introduces all slot information with realistic, natural names (no placeholders).

            --- ⚙️ INTENTS ---
            Each intent defines an operation in the domain:
            IntentName:
                description: <summary>
                preconditions: <required classes or relations>
                slots: <values to express naturally in text>

            Use only these intents:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'slots': ops[i]['postconditions']['slots']
                }
            } for i in ops if i in instructions]}

            --- 🗣️ DIALOGUE RULES ---
            - Each A–B turn = exactly one complete intent taken from this prompt, and not from the other messages.
            - Agent Q (Questioner) must:
              - Reference all the entities in the preconditions using the IDs defined in the previous messages.
              - Explicitly mention the class of each referenced entity.
              - Ask about all knowledge provided required by the intents' slots.
            - Agent A (Answerer) must:
              - Introduce all data from the intent’s slot fields in natural text.
              - Maintain internal consistency with prior dialogue.
              - Specify a new, unique ID for any new entity (matching its class, e.g. 'S001' for Student).
              - Never mention “intent”, “precondition”, or “postcondition” explicitly.
              - Follow these type definitions when generating data:
                    {conf.newl.join([conf.types_def[t]['text'] for t in conf.types_def if t != 'id'])
                        if len([t for t in conf.types_def if t != 'id']) != 0 else ""}
            - Include the executed intent name for every turn.
            - Do not execute partial intents (i.e. asking for only part of the information)

            --- 🧾 OUTPUT FORMAT ---
            JSON only — no extra commentary.

            Example:
            {{
              "1": {{"Intent": "<intent_name>", "Q": "...", "A": "..."}},
              "2": {{"Intent": "<intent_name>", "Q": "...", "A": "..."}}
            }}

            --- ✨ STYLE ---
            - Natural, concise, and contextually consistent.
            - Use realistic entity names and relationships.
            - Avoid redundancy — each turn should expand the world logically.
            - Output only the JSON, without explanations or prefixes.
        """
    })
    conf.chat_history.append({
        'role': 'user',
        'content': 'Continue the dialogue according to the system instructions, ONLY generate new dialogue exchanges,'
                   'do not rewrite old ones. Start enumerating the dialogue turns from 1.'
    })

    start = time()
    dialogue = await async_dialogue_client.chat(
        messages=conf.chat_history,
        model='mistral-small3.2:24b-instruct-2506-q4_K_M',
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    conf.chat_history.pop()
    conf.chat_history.pop()
    dialogue_list = ast.literal_eval(repair_json(dialogue['message']['content']))

    history_dict = defaultdict(dict)
    for k, v in dialogue_list.items():
        history_dict[k]['Q'] = v['Q']
        history_dict[k]['A'] = v['A']

    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing
            entities in a coherent way, do not modify it. {json.dumps(history_dict)}"""
    })

    return dialogue_list