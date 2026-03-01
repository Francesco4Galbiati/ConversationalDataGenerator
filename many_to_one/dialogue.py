import ast
import json
import conf
from time import time
from conf import ops, dialogue_client, async_dialogue_client, newl, types_def, dialogue_llm
from collections import defaultdict
from json_repair import repair_json

def gen_dialogue(instructions, clear):

    if clear:
        conf.chat_history.clear()

    conf.chat_history.append({
        'role': 'system',
        'content': f"""
            ### ROLE ###
            You are simulating a one-to-one conversation between two cooperative agents:
            - Agent Q (Questioner): selects exactly one valid operation per turn and asks a natural-language question.
            - Agent A (Answerer): answers the question by adding new entities and facts to its internal world state.
            
            The simulation must remain consistent, deterministic, and ontology-compliant at all times.
            
            ### OBJECTIVE ###
            Generate a structured dialogue where each turn follows this exact sequence:
            
            1. Agent Q selects one operation whose requirements are already satisfied.
            2. Agent Q asks one question corresponding to that operation.
            3. Agent A answers by:
               - generating all required data,
               - introducing all new entities implied by the operation,
               - adding all facts implied by the operation.
            
            No step may be skipped.
            
            ### INTENTS ###
            Each operation is defined by:
            - description
            - required classes/entities
            - slots (data that must appear in the answer)
            - cardinality: the average number of repetitions of the intent in a 10-turns conversation
            
            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'slots': ops[i]['postconditions']['slots'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops if i in instructions]}
            
            ### DIALOGUE RULES ###
            - Select an intent whose required entities already exist.
            - Intents must be picked more or less frequently according to their cardinality value (from 1 (lower) to 5
            (higher)): intents with higher cardinality must be picked more frequently than intents with lower cardinality.
            - Always specify the current intent's name.
            - Ask exactly one question per turn.
            - Explicitly reference ALL required entities using:
              - their entity ID
              - their class name
            - Ask for ALL information required to fulfill the operation.
            - NEVER mention:
              - ontology
              - operations / intents
              - preconditions or postconditions
              - rules or constraints
              
            Agent A (Answerer) must:
            - Interpret the question using the operation selected by Agent Q.
            - Generate all the ids required by the intent.
            - Generate ALL slot data required by that operation.
            - Introduce ALL new entities implied by the operation.
            - Assign NEW, UNIQUE IDs for new entities only.
            - ID format:
              - One to three capital letters + three digits (e.g., U001, RG002), use different letters for different classes
              - IDs must never be reused.
            - Generate data consistent with the following type descriptions:
                {newl.join([types_def[t]['text'] for t in types_def if t != 'id']) 
                    if len([t for t in types_def if t != 'id']) != 0 else ""}
            - NEVER mention:
                - operations / intents
                - ontology mechanics
                - rules
                - internal state (e.g. “A-Box”)
            
            ### OUTPUT FORMAT ###
            Output a SINGLE JSON object containing ALL turns.
            Each turn MUST follow this structure exactly:
            {{
                "1": {{
                    "Intent": "<intent_name>",
                    "Q": "<question>",
                    "A": "<answer>"
                }},
                "2": {{
                    ...
                }},
                ...
            }}
            
            ### STYLE ###
            - No trailing text.
            - No explanations.
            - No markdown.
            - JSON ONLY.
            
            ### TASK ###
            Generate exactly {len(instructions)*3} turns.
        """
    })
    conf.chat_history.append({
        'role': 'user',
        'content': f'Continue the dialogue according to the system instructions, ONLY generate {len(instructions)*3} '
                   f'new dialogue exchanges, do not rewrite old ones'
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model=dialogue_llm,
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    dialogue_list = ast.literal_eval(repair_json(dialogue['message']['content']))

    history_dict = defaultdict(dict)
    for k, v in dialogue_list.items():
        if 'Q' in v and 'A' in v:
            history_dict[k]['Q'] = v['Q']
            history_dict[k]['A'] = v['A']

    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing
            entities in a coherent way, do not modify it. {json.dumps(history_dict)}"""
    })

    return dialogue_list


async def gen_dialogue_async(instructions, clear):

    if clear:
        conf.chat_history.clear()

    conf.chat_history.append({
        'role': 'system',
        'content': f"""
            ### ROLE ###
            You are simulating a one-to-one conversation between two cooperative agents:
            - Agent Q (Questioner): selects exactly one valid operation per turn and asks a natural-language question.
            - Agent A (Answerer): answers the question by adding new entities and facts to its internal world state.
            
            The simulation must remain consistent, deterministic, and ontology-compliant at all times.
            
            ### OBJECTIVE ###
            Generate a structured dialogue where each turn follows this exact sequence:
            
            1. Agent Q selects one operation whose requirements are already satisfied.
            2. Agent Q asks one question corresponding to that operation.
            3. Agent A answers by:
               - generating all required data,
               - introducing all new entities implied by the operation,
               - adding all facts implied by the operation.
            
            No step may be skipped.
            
            ### INTENTS ###
            Each operation is defined by:
            - description
            - required classes/entities
            - slots (data that must appear in the answer)
            - cardinality: the average number of repetitions of the intent in a 10-turns conversation
            
            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'slots': ops[i]['postconditions']['slots'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops if i in instructions]}
            
            ### DIALOGUE RULES ###
            - Select an intent whose required entities already exist.
            - Intents must be picked more or less frequently according to their cardinality value (from 1 (lower) to 5
            (higher)): intents with higher cardinality must be picked more frequently than intents with lower cardinality.
            - Always specify the current intent's name.
            - Ask exactly one question per turn.
            - Explicitly reference ALL required entities using:
              - their entity ID
              - their class name
            - Ask for ALL information required to fulfill the operation.
            - NEVER mention:
              - ontology
              - operations / intents
              - preconditions or postconditions
              - rules or constraints
              
            Agent A (Answerer) must:
            - Interpret the question using the operation selected by Agent Q.
            - Generate all the ids required by the intent.
            - Generate ALL slot data required by that operation.
            - Introduce ALL new entities implied by the operation.
            - Assign NEW, UNIQUE IDs for new entities only.
            - ID format:
              - One to three capital letters + three digits (e.g., U001, RG002).
              - IDs must never be reused.
            - Generate data consistent with the following type descriptions:
                {newl.join([types_def[t]['text'] for t in types_def if t != 'id']) 
                    if len([t for t in types_def if t != 'id']) != 0 else ""}
            - NEVER mention:
                - operations / intents
                - ontology mechanics
                - rules
                - internal state (e.g. “A-Box”)
            
            ### OUTPUT FORMAT ###
            Output a SINGLE JSON object containing ALL turns.
            Each turn MUST follow this structure exactly:
            {{
                "1": {{
                    "Intent": "<intent_name>",
                    "Q": "<question>",
                    "A": "<answer>"
                }},
                "2": {{
                    ...
                }},
                ...
            }}
            
            ### STYLE ###
            - No trailing text.
            - No explanations.
            - No markdown.
            - JSON ONLY.
            
            ### TASK ###
            Generate exactly {len(instructions)*3} turns.
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
        model=dialogue_llm,
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
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