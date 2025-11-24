import ast
import conf
from time import time
from conf import ops, chat_history, ids
from agents import tbox_agent, repair_agent, cluster_agent
from functions import repair_dialogue, replace_ids
from json_repair import repair_json

start = time()
instructions = cluster_agent.run_sync(f"""
    ### ROLE ###
    You are an expert ontology analyst.  
    Your task is to organize a list of domain intents into coherent areas of expertise.  
    Each area of expertise groups intents that deal with related entities, actions, or relationships.
    
    ### OBJECTIVE ###
    Given the following intents, analyze their descriptions, preconditions, and postconditions, and produce a
    structured categorization:
    1. Identify logical areas or subdomains of expertise.
    2. Assign each of the intents to one area.
    3. Make sure that each area has a meaningful conceptual focus.
    4. Create new area names when necessary, but keep them concise and descriptive.
    5. Prefer 4–5 areas in total.
    6. Try to keep a balanced number of intents for each area of expertise.
    7. Order the areas according to the preconditions of their intent: an intent I1 that has the result of another
    intent I2 in the preconditions should be put after I2
    
    ### INPUT ###
    Each intent is described as:
    IntentName:
      description: <short summary>
      preconditions: <required entities or relations>
      postconditions: <new entities or relations>
      slots: <data attributes introduced by the intent>
    
    ### INTENTS ###:
    {[{
        i: {
            'description': ops[i]['preconditions']['description'],
            'preconditions': ops[i]['preconditions']['classes'], 
            'postconditions': ops[i]['postconditions']['classes'],
            'slots': ops[i]['postconditions']['slots']
        }
    } for i in ops]}
    
    ### OUTPUT FORMAT ###
    Return only valid JSON in the following format:
    
    {{
        "<area1_name>": ['<intent1_name>', '<intent2_name>', ...],
        "<area2_name>": ['<intent6_name>', '<intent7_name>', ...]
        ...
    }}
    
    ### STYLE ###
    - Use short, human-readable area names.
    - Every intent must appear exactly once.
    - Return the areas of expertise ordered according to the dependencies of their intent.
    - Do not include any explanations or commentary outside of the JSON.
""")
ex_time = time() - start
conf.model_time += ex_time
input_tokens = instructions._state.usage.input_tokens
output_tokens = instructions._state.usage.output_tokens
print(f"Instruction generation: {{Execution time: {round(ex_time, 2)}, Input tokens: {input_tokens}, Output tokens: {output_tokens}}}")

instructions = ast.literal_eval(repair_json(instructions.output))

def get_dialogue(instructions):

    start = time()
    dialogue = tbox_agent.run_sync(f"""
        --- 🧭 ROLE ---
        You are simulating a conversation between two cooperative agents exploring a section of a knowledge domain.
        - Agent A (Questioner): asks progressively deeper questions to uncover new entities and relations.
        - Agent B (Answerer): replies with facts, descriptions, and relations according to defined intents.
        
        --- 🎯 OBJECTIVE ---
        Generate a coherent and natural dialogue that:
        - Gradually explores the domain described by the intents.
        - Uses intents only when all their preconditions are satisfied.
        - Includes at least {len(instructions) * 3} full A–B exchanges (≈{len(instructions) * 6} total turns).
        - Balances frequency: large entities (e.g. Universities) appear 1–2 times; smaller ones (e.g. Students) appear 3–4 times.
        - Introduces all slot information with realistic, natural names (no placeholders).
        
        --- ⚙️ INTENTS ---
        Each intent defines an operation in the domain:
        IntentName:
            description: <summary>
            preconditions: <required classes or relations>
            postconditions: <introduced classes or relations>
            slots: <values to express naturally in text>
            
        Intents to use:
        {[{
            i: {
                'description': ops[i]['preconditions']['description'],
                'preconditions': ops[i]['preconditions']['classes'], 
                'postconditions': ops[i]['postconditions']['classes'],
                'slots': ops[i]['postconditions']['slots']
            }
        } for i in ops if i in instructions]}
        
        --- 🗣️ DIALOGUE RULES ---
        - Each A–B turn = exactly one intent.
        - Agent A (Questioner) must:
          - Ask about all knowledge provided by the intent.
          - Reference all the entities in the preconditions' slots using the IDs defined in the chat history.
          - Explicitly mention the class of each referenced entity.
        - Agent B (Answerer) must:
          - Introduce all data from the intent’s slot fields in natural text.
          - Maintain internal consistency with prior dialogue.
          - Specify a new, unique ID for any new entity (matching its class, e.g. 'S001' for Student).
          - Never mention “intent”, “precondition”, or “postcondition” explicitly.
        - Include the executed intent name for every turn.
        
        --- 🧾 OUTPUT FORMAT ---
        JSON only — no extra commentary.
        
        Example:
        {{
          "1": {{"Intent": "<intent_name>", "A": "...", "B": "..."}},
          "2": {{"Intent": "<intent_name>", "A": "...", "B": "..."}}
        }}
        
        --- ✨ STYLE ---
        - Natural, concise, and contextually consistent.
        - Use realistic entity names and relationships.
        - Avoid redundancy — each turn should expand the world logically.
        - Output only the JSON, without explanations or prefixes.
    """, message_history=chat_history)
    ex_time = time() - start
    conf.model_time += ex_time
    input_tokens = dialogue._state.usage.input_tokens
    output_tokens = dialogue._state.usage.output_tokens
    dialogue_list = ast.literal_eval(repair_json(dialogue.output))
    repair_record = repair_dialogue(dialogue_list)
    print(f"Dialogue generation: {{Execution time: {round(ex_time, 2)}, Input tokens:  {input_tokens}, Output tokens: {output_tokens}}}")

    chat_history.extend(dialogue.new_messages())

    if len(repair_record) != 0:
        start = time()
        repaired_dialogue = repair_agent.run_sync(f"""
            You are repairing a dialogue between Agent A and Agent B.
            Your goal is to fix inconsistencies and missing data while preserving meaning.
    
            ### INPUT ###
            Dialogue:
            {dialogue_list}
    
            Detected issues:
            {repair_record}
    
            ### RULES ###
            - Correct only the minimal necessary parts according to the turns and agents specified in the list of detected
              issues by explicitating the missing ids as stated in the list of detected issues.
            - Infer the missing ids from the previous turns of the dialogue.
            - Keep the IDs consistent across all turns.
            - Do not change the dialogue structure or intent order.
            - If an entity is referenced only by name, add its id to the question according to the context.
            - Check if there is any entity without an id in the answers and, if any, generate a new id for each of them
    
            ### OUTPUT ###
            Return the corrected dialogue, formatted exactly as:
            Use a JSON format for the output:
            {{
                "1": {{
                    "Intent": "<intent_name>",
                    'A': '...',
                    'B:': '...'
                }},
                "2": {{
                    "Intent": "<intent_name>",
                    "A": "...",
                    "B": "..."
                }},
                ...
            }}
        """)
        ex_time = time() - start
        conf.model_time += ex_time
        input_tokens = repaired_dialogue._state.usage.input_tokens
        output_tokens = repaired_dialogue._state.usage.output_tokens
        print(f"Dialogue reparation: {{Execution time: {round(ex_time, 2)}, Input tokens:  {input_tokens}, Output tokens: {output_tokens}}}")
        chat_history[-1] = repaired_dialogue.new_messages()[-1]
        dialogue_list = replace_ids(ast.literal_eval(repair_json(repaired_dialogue.output)), ids)

    return dialogue_list