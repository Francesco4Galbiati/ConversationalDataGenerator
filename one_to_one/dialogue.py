import ast
import conf
from time import time
from agents import tbox_agent
from conf import ops
from json_repair import repair_json

start = time()
dialogue = tbox_agent.run_sync(user_prompt=f"""
    ### ROLE ###
    You are simulating a one-to-one conversation between two cooperative agents:
    - Agent Q (Questioner) – asks high-level questions to explore a domain.
    - Agent A (Answerer) – answers the questions, building the world step by step
    
    ### OBJECTIVE ###
    Generate a structured multi-agent dialogue where:
    1. Agent Q asks one question per turn, choosing an available intent from the list.
    2. A interprets the question according to the specified intent and:
        - generate new facts/entities
        - expand its A-Box
    3. All answers must faithfully follow intent preconditions, postconditions, and slots.
    
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
            'slots': ops[i]['postconditions']['slots']
        }
    } for i in ops]}
    
    Each Answerer uses the same intent set but generates its own different A-Box.
    
    ### DIALOGUE RULES ###
    - Set up a sequence of intents from the list such that the preconditions of one intent can be satisfied by the 
    previous ones, intents in the sequence can be repeated multiple times in a row.
    - Agent Q (Questioner) must:
        - Asks one question per turn by selecting an intent whose preconditions can be satisfied.
        - For each specific slot required by the preconditions, specify the id and the class (e.g. Class C001) of the
        entities you intend to reference.
        - Never mention “intents”, “preconditions”, “postconditions”.
    - Agent A (Answerer) must:
        - Interpret the question using the intent provided by the questioner.
        - Generate all the required entities present the slots section of the intent that have not been generated
        previously.
        - Use unique, sequential entity IDs appropriate for classes, formed by one or two capital letters and a
        number of 3 digits, starting from 001 (e.g. U001, D001, RG001)
        - Never reuse ids from other turns of the conversation.
        - Never refer to “intents” explicitly.
    
    Each answerer produces one answer per turn.
    
    ### OUTPUT FORMAT ###
    For each turn, produce a JSON block like:
    {{
        "1": {{
            "Intent": "<intent>",
            "Q": "<question>",
            "A": "<answer>"
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
    
    Now generate a dialogue of 25 turns
""")
ex_time = time() - start
conf.model_time += ex_time
input_tokens = dialogue._state.usage.input_tokens
output_tokens = dialogue._state.usage.output_tokens
print(f"Dialogue generation: {{Execution time: {round(ex_time, 2)}, Input tokens:  {input_tokens}, Output tokens: {output_tokens}}}")

dialogue_list = ast.literal_eval(repair_json(dialogue.output))