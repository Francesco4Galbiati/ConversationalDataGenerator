import ast
import conf
from time import time
from conf import ops, chat_history
from agents import tbox_agent, cluster_agent
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
        You are simulating a many-to-many parallel conversation with:
        - A T-Box, representing a specialized conceptual viewpoint (subsets of intents).
        - 3 A-Boxes (Answerers), A1, A2, A3, who independently populate separate knowledge graphs.
        Each A-Box maintains:
        - its own entities
        - its own IDs
        - its own narrative world
        - its own interpretation of the questions
        No A-Box ever sees the others.
        
        The simulation models parallel world exploration with a conceptual planner (T-Box) and multiple generators 
        (A-Boxes).
        
        --- 🎯 OBJECTIVE ---
        1. Generate a structured multi-agent dialogue where:
          - T-Box selects an available intent.
          - It asks one high-level question consistent with that intent.
        2. A1, A2, A3 independently:
          - interpret the question
          - satisfy preconditions using their own previously created entities
          - introduce new entities where required
          - create new facts according to the intent’s postconditions
        3. All A-Box branches diverge in:
          - entity IDs
          - attribute values
          - which previously created entities they connect to
          - world structure
        
        This produces parallel knowledge graph expansions across different conceptual planners.
        
        ⚙️ INTENTS
        Each intent is defined by:
        
        IntentName:
            description: <summary>
            preconditions: <required classes/relations>
            postconditions: <introduced classes/relations>
            slots: <required slot values>
            
        Available intents:
        {[{
            i: {
                'description': ops[i]['preconditions']['description'],
                'preconditions': ops[i]['preconditions']['classes'],
                'postconditions': ops[i]['postconditions']['classes'],
                'slots': ops[i]['postconditions']['slots'] | ops[i]['preconditions']['slots']
            }
        } for i in instructions]}
        
        --- 🗂️ DIALOGUE RULES FOR T-BOX---
        At each turn:
        1. The T-Box selects an intent:
          - It must belong to the T-Box’s area of expertise (derived from its subset of intents).
          - All preconditions must be logically satisfiable by prior A-Box turns.
          - Frequently reuse small-entity intents (Student, Course, Group).
          - Sparingly reuse large-entity intents (University, Department).
        2. The T-Box generates one high-level question:
          - No mention of:
            - “intent”
            - “preconditions”
            - “slots”
          - Must never reference entity IDs (A-Boxes own the IDs).
          - The question should implicitly request the content the intent introduces.
        
        --- 🧠 DIALOGUE RULES FOR A-BOXES ---
        For each turn, A1, A2, A3 independently:
        1. Precondition satisfaction
          - Identify entities matching the required slots.
          - If multiple entities match:
            - do not always select the most recent;
            - do not always select the same one across the three A-Boxes;
            - prioritize structural diversity:
              - A1 may pick an entity from turn 2
              - A2 from turn 5
              - A3 from turn 7
          - If no matching entity exists, create it.
        2. Postcondition generation
          - Create all required classes and relations.
          - Fill all slot values with naturalistic names.
          - Assign IDs:
            - format: [A–Z]{{1,2}}[0-9]{{3}}
            - unique, sequential within each A-Box
            - never reused
        3. Structural diversity requirement
          - To avoid homogeneous graphs, A-Boxes must:
            - avoid using the same previously created entity as the other A-Boxes
            - vary which earlier entities they link to
            - occasionally reuse older entities rather than the newest
            - distribute relationships among different branches of the existing graph
            
        --- 🧾 OUTPUT FORMAT ---
        JSON only:
        {{
            "1": {{
                "Intent": "<intent_name>",
                "Q": "<question>",
                "A1": "<answer>",
                "A2": "<answer>",
                "A3": "<answer>"
            }},
            "2": {{ ... }},
             ...
        }}
        
        --- ✨ STYLE ---
        - Natural, human-like conversational tone.
        - Rich but concise.
        - Diverse data across A1, A2, A3.
        - No meta-commentary.
        
        Now generate a dialogue containing at least {len(instructions) * 3} full A–B exchanges.
    """, message_history=chat_history)
    ex_time = time() - start
    conf.model_time += ex_time
    input_tokens = dialogue._state.usage.input_tokens
    output_tokens = dialogue._state.usage.output_tokens
    print(f"Dialogue generation: {{Execution time: {round(ex_time, 2)}, Input tokens:  {input_tokens}, Output tokens: {output_tokens}}}")

    conf.chat_history.extend(dialogue.new_messages())
    dialogue_list = ast.literal_eval(repair_json(dialogue.output))
    return dialogue_list