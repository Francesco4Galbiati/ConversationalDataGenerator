import ast
from time import time
from json_repair import repair_json

import conf
from conf import ops, default_n, dialogue_client, newl, types_def, async_dialogue_client

def gen_dialogue(n = default_n):

    start = time()

    dialogue = dialogue_client.generate(

        prompt=f"""
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
            
            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'], 
                    'slots': ops[i]['postconditions']['slots']
                }
            } for i in ops]}
            You may ONLY use operations listed above.
            
            ### DIALOGUE RULES ###
            - Select an operation whose required entities already exist.
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
            - Keys must be sequential numbers starting from "1".
            - No trailing text.
            - No explanations.
            - No markdown.
            - JSON ONLY.
            
            ### TASK ###
            Generate exactly {n} turns.
        """,
        model='mistral-small3.2:24b-instruct-2506-q4_K_M',
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    return ast.literal_eval(repair_json(dialogue['response']))

async def gen_dialogue_async(n = default_n):

    start = time()

    dialogue = await async_dialogue_client.generate(

        prompt=f"""
                ### ROLE ###
                You are simulating a one-to-one conversation between two cooperative agents:
                    - Agent Q (Questioner) – selects one intent per turn and asks a natural-language question.
                    - Agent A (Answerer) – answers the question, expanding its own A-Box by creating new entities and facts.
                The simulation must be strictly controlled, deterministic, and fully consistent with the ontology.

                ### OBJECTIVE ###
                - Produce a structured dialogue where each turn follows this pipeline:
                - Q selects exactly one valid intent from the list.
                - Q asks one question based on that intent.
                - A interprets the question using the chosen intent, and:
                    - creates all required entities,
                    - adds new facts consistent with the intent’s postconditions

                ### INTENTS ###
                Each intent has:
                    - description
                    - preconditions (required classes/entities)
                    - slots (data the answer must express naturally)

                Intents available:
                {[{
                    i: {
                        'description': ops[i]['preconditions']['description'],
                        'preconditions': ops[i]['preconditions']['classes'],
                        'slots': ops[i]['postconditions']['slots']
                    }
                } for i in ops]}

                ### DIALOGUE RULES ###
                Agent Q (Questioner) must:
                - Select an intent whose preconditions are currently satisfied.
                - Ask one question based on that intent.
                - Referencing every entity in the intent's precondition, always specifying their entity ID
                - Never mention:
                    - “intent”
                    - “preconditions”
                    - “postconditions”
                    - ontology mechanics

                Agent A (Answerer) must:
                - Interpret the question according to the intent decided by Q.
                - Create all entities required by the intent’s postconditions.
                - Use unique sequential IDs for each class:
                    - Format: A, AA, or AAA + 3 digits (e.g., U001, RG002).
                - Follow these type definitions when generating data:
                    {newl.join([types_def[t]['text'] for t in types_def if t != 'id'])
                        if len([t for t in types_def if t != 'id']) != 0 else ""}
                - Never reuse an ID for any entity.
                - Never mention:
                    - “intent”, “preconditions”, “postconditions”
                    - internal rules
                    - the A-Box explicitly

                ### OUTPUT FORMAT ###
                Output only one single JSON object containing all turns:
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
                - Natural, conversational tone.
                - Rich, realistic details.
                - Consistent naming and entity references.
                - Absolutely no meta-commentary or explanation.

                ### TASK ###
                Now generate a dialogue of {n} turns following all rules above.
            """,
        model='mistral-small3.2:24b-instruct-2506-q4_K_M',
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    return ast.literal_eval(repair_json(dialogue['response']))