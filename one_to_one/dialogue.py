import ast
import conf
from time import time
from conf import ops, default_n, dialogue_client, newl, types_def, async_dialogue_client, dialogue_llm
from json_repair import repair_json

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
            - cardinality: the average number of repetitions of the intent in a 10-turns conversation
            
            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'], 
                    'slots': ops[i]['postconditions']['slots'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops]}
            You may ONLY use operations listed above.
            
            ### DIALOGUE RULES ###
            - Select an intent whose required entities already exist.
            - Intents must be picked more or less frequently according to their cardinality value (from 1 (lower) to 5
            (higher)): intents with higher cardinality must be picked more frequently than intents with lower cardinality.
            - Use ALL the intents given to you in the dialogue you generate
            - Generated entities with lower cardinality must be used in multiple future turns of the conversation
            - Ask exactly one specific question per turn, mentioning all the ids in the preconditions.
            - In the question, explicitly reference ALL required entities using their entity ID
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
            - Display all data in a dialogical answer (not a list of fields)
            - Assign NEW, UNIQUE IDs for new entities only.
            - ID format:
              - One to three capital letters + three digits. Use letters that are coherent with the class of the entity.
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
        model=dialogue_llm,
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
                } for i in ops]}
                You may ONLY use operations listed above.
                
                ### DIALOGUE RULES ###
                - Select an intent whose required entities already exist.
                - Intents must be picked more or less frequently according to their cardinality value (from 1 (lower) to 5
                (higher)): intents with higher cardinality must be picked more frequently than intents with lower cardinality.
                - Use ALL the intents given to you in the dialogue you generate
                - Generated entities with lower cardinality must be used in multiple future turns of the conversation
                - Ask exactly one specific question per turn, mentioning all the ids in the preconditions.
                - In the question, explicitly reference ALL required entities using their entity ID
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
                - Display all data in a dialogical answer (not a list of fields)
                - Assign NEW, UNIQUE IDs for new entities only.
                - ID format:
                  - One to three capital letters + three digits. Use letters that are coherent with the class of the entity.
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
        model=dialogue_llm,
        format='json',
        options={
            "temperature": 0.8
        }
    )

    end = time()
    print(f"Dialogue generation: {{Execution time: {round(end - start, 2)}}}")
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    return ast.literal_eval(repair_json(dialogue['response']))