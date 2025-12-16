import ast
from collections import defaultdict

import conf
from time import time
from conf import ops, chat_history, dialogue_client, num_abox
from agents import dialogue_agent, cluster_agent
from json_repair import repair_json


def gen_dialogue(instructions):

    conf.chat_history.append({
        'role': 'system',
        'content': f"""
            ### ROLE ###
            You are simulating a parallel conversation between four cooperative agents:
            - Agent Q (Questioner) – asks high-level questions to explore a domain.
            - Agent A1, Agent A2, Agent A3 (Answerers) – each answers independently, building a separate A-Box model of the
            same ontology.
            
            Each Answerer’s A-Box is completely isolated, with its own entities, IDs, and facts.
            No Answerer ever sees or references the others.
            
            ### OBJECTIVE ###
            Generate a structured multi-agent dialogue where:
            1. Agent Q asks one question per turn, choosing an available intent from the list.
            2. A1, A2, and A3 each interpret the question independently according to the specified intent and:
                - generate new facts/entities
                - expand their own parallel A-Box
                - mention required entities from the previously generated ones.
            3. The three answers must yield:
                - different data
                - different ids
                - different narrative branches
            4. All answers must faithfully follow intent preconditions, postconditions, and slots.
            
            This is used to simulate parallel knowledge graph branches.
            
            ### INTENTS ###
            The domain is defined by intents, each having:
            - description
            - preconditions (required classes/relations)
            - slots (values to be expressed naturally)
            
            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'slots': ops[i]['postconditions']['slots']
                }
            } for i in ops if i in instructions]}
            
            Each Answerer uses the same intent set but generates its own different A-Box.
            
            ### DIALOGUE RULES ###
            - Set up a sequence of intents from the list such that the preconditions of one intent can be satisfied by the 
            previous ones, intents in the sequence can be repeated multiple times in a row.
            - Agent Q (Questioner) must:
                - Asks one high-level question per turn by selecting an intent whose preconditions can be satisfied.
                - Must not reference any specific entities (those belong to the Answerers’ A-Boxes).
                - Must never mention “intents”, “preconditions”, “postconditions”.
                - Must balance intent frequency: large entities (e.g. Organizations) appear 1–2 times; smaller ones
                    (e.g. People) appear 3–4 times; 
            - Agent A1, A2, A3 (Parallel Answerers), each Answerer must:
                - Interpret the question using the intent provided by the questioner.
                - Identify the slots of the preconditions among the entities already generated in the previous
                interactions
                - Generate all the required entities present the slots section of the intent that have not been generated
                previously.
                - Every precondition mentioned in the selected intent MUST be included in the answer by using its id.
                - Use unique, sequential entity IDs appropriate for classes, formed by one or two capital letters and a
                number of 3 digits, starting from 001 (e.g. U001, D001, RG001)
                - Follow these type definitions when generating data:
                    {conf.newl.join([conf.types_def[t]['text'] for t in conf.types_def if t != 'id']) 
                        if len([t for t in conf.types_def if t != 'id']) != 0 else ""}
                - Never mention, reference, or imply the existence of A2 or A3 (or vice versa).
                - Never refer to “intents” explicitly.
            - When multiple previously-generated entities satisfy a precondition, the answerer must not always pick the same
            one. They should rotate or diversify across different suitable entities to explore alternative knowledge branches.
            
            Each answerer produces one answer per turn.
            
            ### OUTPUT FORMAT ###
            For each turn, produce a JSON block like:
            {{
                "1": {{
                    "Q": "<question>",
                    "Intent": "<intent>",
                    "A1": "<answer>",
                    "A2": "<answer>",
                    "A3": "<answer>"
                }},
                "2": {{
                    ...
                }},
                ...
            }}
            
            ### STYLE ###
            - Natural, friendly dialogue tone.
            - Rich, realistic data.
            - Clear, consistent entity naming.
            - No meta-commentary, no explanations.
            - Output only JSON.
            
            Now generate a dialogue with {len(instructions) * 3} new question turns, without counting the ones present
            in the message history, restarting the enumeration of the turns from 1
        """
    })
    conf.chat_history.append({
        'role': 'user',
        'content': 'Continue the dialogue according to the system instructions, ONLY generate new dialogue exchanges,'
                   'do not rewrite old ones present in other messages.'
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
    ex_time = time() - start
    print(f"Dialogue generation: {{Execution time: {round(ex_time, 2)}}}")

    conf.chat_history.pop()
    conf.chat_history.pop()
    dialogue_list = ast.literal_eval(repair_json(dialogue['message']['content']))

    history_dict = defaultdict(dict)
    for k, v in dialogue_list.items():
        history_dict[k]['Q'] = v['Q']
        for n in range(num_abox):
            history_dict[k][f'A{str(n+1)}'] = v[f'A{str(n+1)}']

    import json
    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing
                entities in a coherent way, do not modify it. {json.dumps(history_dict)}"""
    })

    return dialogue_list