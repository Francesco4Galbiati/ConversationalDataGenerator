import ast
from json_repair import repair_json

import conf
from agents import tbox_agent
from conf import ops
from time import time

start = time()
dialogue = tbox_agent.run_sync(f"""
    ### ROLE ###
    You are simulating a one-to-many parallel conversation between four cooperative agents:
    - Agent Q (Questioner) – asks high-level questions to explore a domain.
    - Agent A1, Agent A2, Agent A3 (Answerers) – each answers independently, building a separate A-Box model of the
    same ontology.
    
    Each Answerer’s A-Box is co mpletely isolated, with its own entities, IDs, and facts.
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
            'postconditions': ops[i]['postconditions']['classes'],
            'slots': ops[i]['postconditions']['slots'] | ops[i]['preconditions']['slots']
        }
    } for i in ops]}
    
    Each Answerer uses the same intent set but generates its own different A-Box.
    
    ### DIALOGUE RULES ###
    - Set up a sequence of intents from the list such that the preconditions of one intent can be satisfied by the 
    previous ones, intents in the sequence can be repeated multiple times in a row.
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
    - Rich, realistic data.
    - Clear, consistent entity naming.
    - No meta-commentary, no explanations.
    - Output only JSON.
    
    Now generate a dialogue of 20 turns
""")

ex_time = time() - start
conf.model_time += ex_time
input_tokens = dialogue._state.usage.input_tokens
output_tokens = dialogue._state.usage.output_tokens
print(f"Dialogue generation: {{Execution time: {round(ex_time, 2)}, Input tokens:  {input_tokens}, Output tokens: {output_tokens}}}")

dialogue_list = ast.literal_eval(repair_json(dialogue.output))

print()