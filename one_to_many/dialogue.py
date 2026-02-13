import ast
import conf
from json_repair import repair_json
from conf import ops, dialogue_client, default_n, newl, types_def, async_dialogue_client
from time import time

def gen_dialogue(n = default_n):

    start = time()

    dialogue = dialogue_client.generate(

        prompt=f"""
            ### ROLE ###
            You are simulating a one-to-many parallel conversation between four cooperative agents:
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
            - cardinality: the average number of repetitions of the intent in a 10-turns conversation
            
            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'], 
                    'slots': ops[i]['postconditions']['slots'] | ops[i]['preconditions']['slots'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops]}
            
            Each Answerer uses the same intent set but generates its own different A-Box.
            
            ### DIALOGUE RULES ###
            - Set up a sequence of intents from the list such that the preconditions of one intent can be satisfied by the 
            previous ones, intents in the sequence can be repeated multiple times in a row.
            - Intents must be picked more or less frequently according to their cardinality value (from 1 (lower) to 5
            (higher)): intents with higher cardinality must be picked more frequently than intents with lower cardinality.
            - Generated entities with lower cardinality must be used in multiple future turns of the conversation
            - Agent Q (Questioner) must:
                - Asks one high-level question per turn by selecting an intent whose preconditions can be satisfied.
                - Must not reference any specific entities (those belong to the Answerers’ A-Boxes).
                - Must never mention “intents”, “preconditions”, “postconditions”.
            - Agent A1, A2, A3 (Parallel Answerers), each Answerer must:
                - Interpret the question using the intent provided by the questioner.
                - Identify the slots of the preconditions among the entities already generated and choose one for each slot,
                trying to chose an id different from the one chosen by the other answerers 
                - Generate all the required entities present the slots section of the intent that have not been generated
                previously.
                - Use unique, sequential entity IDs appropriate for classes, formed by one or two capital letters and a
                number of 3 digits, starting from 001 (e.g. U001, D001, RG001)
                - Follow these type definitions when generating data:
                    {newl.join([types_def[t]['text'] for t in types_def if t != 'id']) 
                        if len([t for t in types_def if t != 'id']) != 0 else ""}
                - Never reuse ids from other turns of the conversation.
                - You can use entities belonging to a subclass when asked about an instance of the relative superclass.
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
            - Rich, realistic, non-trivial data.
            - Clear and diverse entity naming.
            - No meta-commentary, no explanations.
            - Output only JSON.
            
            Now generate a dialogue of exactly {n} turns
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

async def gen_dialogue_async(n=default_n):

    start = time()

    dialogue = await async_dialogue_client.generate(
        prompt=f"""
            ### ROLE ###
            You are simulating a one-to-many parallel conversation between four cooperative agents:
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
            - postconditions (created classes/relations)
            - slots (values to be expressed naturally)

            Intents available:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'slots': ops[i]['postconditions']['slots'] | ops[i]['preconditions']['slots'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops]}

            Each Answerer uses the same intent set but generates its own different A-Box.

            ### DIALOGUE RULES ###
            - Set up a sequence of intents from the list such that the preconditions of one intent can be satisfied by the 
            previous ones, intents in the sequence can be repeated multiple times in a row.
            - Intents must be picked more or less frequently according to their cardinality value (from 1 (lower) to 5
            (higher)): intents with higher cardinality must be picked more frequently than intents with lower cardinality.
            - Generated entities with lower cardinality must be used in multiple future turns of the conversation
            - Agent Q (Questioner) must:
                - Asks one high-level question per turn by selecting an intent whose preconditions can be satisfied.
                - Must not reference any specific entities (those belong to the Answerers’ A-Boxes).
                - Must never mention “intents”, “preconditions”, “postconditions”.
            - Agent A1, A2, A3 (Parallel Answerers), each Answerer must:
                - Interpret the question using the intent provided by the questioner.
                - Identify the slots of the preconditions among the entities already generated and choose one for each slot,
                trying to chose an id different from the one chosen by the other answerers 
                - Generate all the required entities present the slots section of the intent that have not been generated
                previously.
                - Use unique, sequential entity IDs appropriate for classes, formed by one or two capital letters and a
                number of 3 digits, starting from 001 (e.g. U001, D001, RG001)
                - Follow these type definitions when generating data:
                    {newl.join([types_def[t]['text'] for t in types_def if t != 'id'])
                        if len([t for t in types_def if t != 'id']) != 0 else ""}
                - Never reuse ids from other turns of the conversation.
                - You can use entities belonging to a subclass when asked about an instance of the relative superclass.
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
            - Rich, realistic, non-trivial data.
            - Clear and diverse entity naming.
            - No meta-commentary, no explanations.
            - Output only JSON.

            Now generate a dialogue of exactly {n} turns
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