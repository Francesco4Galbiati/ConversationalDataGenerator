import ast
from json_repair import repair_json
from agents import tbox_agent, repair_agent
from conf import ops, bcolors
from functions import repair_dialogue

dialogue = tbox_agent.run_sync(user_prompt=f"""
    ### ROLE ###
    You are simulating a conversation between two cooperative agents exploring a knowledge domain.
    
    - **Agent A (Questioner):** asks contextually relevant questions to progressively uncover the domain.
    - **Agent B (Answerer):** replies by providing facts, descriptions, or relations based on the defined *intents*.
    
    ### OBJECTIVE ###
    Generate a coherent and natural dialogue that:
    1. Gradually explores the domain implied by the provided intents.
    2. Respects all dependencies — an intent can only be used when its preconditions are satisfied.
    3. Includes at least 25 full A–B exchanges (minimum 50 turns).
    4. Introduces all slot information from each executed intent using realistic names and details (no placeholders).
    
    ### INTENTS ###
    Each intent defines an operation within the domain:
    
    Each intent follows this schema:
    IntentName:
    description: <summary>
    preconditions: <classes or relations required before execution>
    postconditions: <classes or relations introduced after execution>
    slots: <list of values to be expressed naturally in text>
    
    This is the list of intents:
    {[{
        i: {
            'description': ops[i]['preconditions']['description'],
            'preconditions': ops[i]['preconditions']['classes'], 
            'postconditions': ops[i]['postconditions']['classes'],
            'slots': ops[i]['postconditions']['slots']
        }
    } for i in ops if i != 'superclasses']}
    
    ### DIALOGUE RULES ###
    - Each (A, B) turn pair corresponds to one logical intent.
    - Agent A’s question must:
      - Anticipate the knowledge that the intent provides
      - Refer to every single one of the dialogue entities present in the intent precondition slots using only
        their previously mentioned ids and put them inside quotation marks: e.g. "Now let's create a department within
        University 'U001'", "What professor teaches inside Department 'D001'?"
      - Always specify the class of the entity the question refers to: "Student 'S001'" is better than just "'S001'"
    - Agent B’s answer must:
      - Include all the slot information found in the intent postcondition slots in a
      plain text format, but still naturally phrased.
      - Stay consistent with previously mentioned facts and relations.
      - Continue until all intents have been used or no further logical step is possible.
      - Generate entity ids consistent with the entity's type, e.g. U001 for a University or S001 for a Student
    - Do not refer to “intents”, “preconditions”, or “postconditions” in the dialogue.
    - For each turn, provide also the intent you are executing.
    
    ### OUTPUT FORMAT ###
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
    
    ### STYLE ###
    - Natural, informative, and conversational tone.
    - Use realistic entity names
    - Avoid repetition; ensure that answers progressively build the world.
    - Each turn must contribute new, logically consistent knowledge
    - Include only the JSON text in your answer, without any other explanation.
""")

dialogue_list = ast.literal_eval(repair_json(dialogue.output))
print(f'{bcolors.OKGREEN}Dialogue generated...{bcolors.ENDC}')

repair_record = repair_dialogue(dialogue_list)
print(f'{bcolors.OKGREEN}Fixing {len(list(repair_record))} error(s)...{bcolors.ENDC}')

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
    issues by specifying the missing ids, if any, for the entities mentioned by the question.
    - Keep the IDs consistent across all turns.
    - Do not change the dialogue structure or intent order.
    - If an entity is referenced only by name, add its id to the question according to the context

    ### OUTPUT ###
    Return the corrected dialogue, formatted exactly as:
    QUse a JSON format for the output:
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

dialogue_list = ast.literal_eval(repair_json(repaired_dialogue.output))