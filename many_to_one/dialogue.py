import ast
import json
import conf
from time import time
from conf import ops, default_n, dialogue_client, newl, types_def, async_dialogue_client, witness_llm, querent_llm
from json_repair import repair_json

def gen_dialogue_turn(instructions, clear = False):

    if(clear):
        conf.chat_history.clear()
        conf.turn_counter = 0
        conf.history_dict = []

    conf.chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent Q (Questioner).

            You are in a one-to-one conversation with Agent A.
            Your ONLY task is to:
            1) Select exactly ONE valid intent
            2) Ask exactly ONE question corresponding to that intent

            You NEVER answer questions.
            You NEVER introduce new information.

            ---

            ### CORE CONSTRAINT (CRITICAL) ###
            You MUST ONLY use entities that already exist in the conversation history.

            - NEVER introduce a new entity
            - NEVER guess or invent entity names or IDs
            - EVERY entity mentioned in your question MUST already appear in the chat history
            - If a required entity is missing → DO NOT select that intent

            If you violate this rule, your output is INVALID.

            ---

            ### INTENTS ###
            Each intent includes:
            - description
            - required entities (preconditions)
            - cardinality

            Available intents:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'required_entities': ops[i]['preconditions']['classes'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops if i in instructions]}

            You may ONLY select from this list.

            ---

            ### DECISION RULES ###
            You MUST follow ALL rules:

            1. VALIDITY:
            - Select an intent ONLY if ALL its required entities are already present in the conversation
            - If no history exists → select an intent with NO required entities

            2. ENTITY CONSISTENCY (HARD RULE):
            - You may ONLY reference entities that already appeared
            - You MUST reuse their EXACT IDs (no variation, no paraphrasing)

            3. DIVERSITY:
            - The selected intent MUST be different from the immediately previous turn
            - Prefer intents used less frequently
            - Prefer higher-cardinality intents, but avoid repetition
            - Ensure all intents are eventually covered

            ---

            ### QUESTION RULES ###
            You must generate EXACTLY ONE question.

            The question MUST:
            - Explicitly include ALL required entities (using their EXACT IDs from history)
            - ONLY include entities already mentioned in the conversation
            - NOT introduce any new entity (strictly forbidden)
            - Request ALL required information (all slots)
            - Be natural and coherent

            ---

            ### SELF-CHECK BEFORE OUTPUT (MANDATORY) ###
            Before answering, verify:

            - Did I introduce ANY new entity? → If yes, REGENERATE
            - Are ALL entities in the question present in history? → If no, REGENERATE
            - Did I include ALL required entities? → If no, REGENERATE
            - Did I ask exactly ONE question? → If no, REGENERATE

            ---

            ### STRICT PROHIBITIONS ###
            NEVER mention:
            - intents or operations
            - rules, constraints, or validation steps
            - ontology, schema, or structure

            ---

            ### OUTPUT FORMAT ###
            Return ONLY:

            {{
                "Intent": "<intent_name>",
                "Q": "<question>"
            }}
        """
    })
    conf.chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating a new question. Return only your answer to the prompt without any reasoniong"
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model=querent_llm,
        format='json',
        options={
            'temperature': 0.1,
            'top_p': 0.9,
            'top_k': 30
        }
    )
    while dialogue['message']['content'] == '{}':
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=querent_llm,
            format='json',
            options={
                'temperature': 0.1,
                'top_p': 0.9,
                'top_k': 30
            }
        )
    end = time()
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue['message']['content']))
    intent = output_json["Intent"]
    question = output_json["Q"]

    intent_content = {
        'description': {str(ops[intent]['preconditions']['description'])},
        'slots': {str(ops[intent]['postconditions']['slots'] | ops[intent]['preconditions']['slots'])}
    }
    
    conf.chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent A (Answerer).

            You generate a STRICT structured JSON object that extends a persistent knowledge base of entities and facts.

            ---

            ### CORE BEHAVIOR ###
            This system is INCREMENTAL.

            Each turn is a PATCH to an existing database:
            - You ONLY output new information requested by the current intent
            - You MUST NOT reconstruct or repeat existing knowledge

            ---

            ### INPUT ###
            - Current question: {question}
            - Conversation history (contains all existing entities and facts)

            ---

            ### CURRENT INTENT ###
            {intent}: {intent_content}

            ---

            ### OBJECTIVE ###
            Produce a JSON object that:

            1. Fills ALL required intent slots
            2. Adds ONLY NEW entities introduced in this turn (if any)
            3. Uses EXISTING entities ONLY by ID reference
            4. Never duplicates or restates existing facts

            ---

            ### STATE RULE (CRITICAL) ###
            The conversation is a persistent state.

            You are NOT allowed to:
            - Re-describe existing entities
            - Repeat previously stated facts
            - Reprint attributes already known from history

            You are ONLY allowed to output:
            - New entities
            - New facts
            - Slot values required for this turn

            ---

            ### PRECONDITION RULE ###
            - Precondition entities MUST be referenced ONLY by ID
            - DO NOT expand or redefine pre-existing entities
            - DO NOT include full entity objects for preconditions

            ---

            ### ENTITY RULES ###
            - New entities only if strictly required by intent
            - IDs must be unique (FORMAT: AAA999)
            - Never reuse an existing ID
            - Existing entities must never be modified

            ---

            ### OUTPUT MINIMALITY RULE ###
            Your output must contain ONLY:
            - Required intent slots
            - New entities (if any)
            - References to existing entities (by ID only)

            NO additional fields are allowed.

            ---

            ### STRICT ANTI-REPETITION RULE ###
            It is strictly forbidden to:
            - Repeat entities from previous turns
            - Repeat facts already present in history
            - Restate known attributes in any form
            - Reconstruct full object state

            If information already exists → OMIT IT completely.

            ---

            ### OUTPUT FORMAT ###
            Return exactly one JSON object (single line):

            {{
                "<slot1>": "<value>",
                "<slot2>": "<value>",
                ...
            }}

            Rules:
            - Must be valid JSON
            - Must be flat (no nested objects for entities)
            - Must include ALL intent slots
            - Must NOT include redundant or historical data

            ---

            ### FAILURE CONDITIONS ###
            Output is INVALID if:
            - Any required slot is missing
            - Any precondition entity is expanded or duplicated
            - Any previously known fact is repeated
            - Any entity ID is reused incorrectly

            ---

            ### STRICT PROHIBITIONS ###
            Do NOT mention:
            - rules, schema, ontology
            - reasoning or internal state
            - explanations or commentary
        """
    })
    conf.chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating the answer to the last question. Return only your answer to the prompt without any reasoniong"
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model=witness_llm,
        format='json',
        options={
            'temperature': 0.5,
            'top_p': 0.95,
            'top_k': 70
        }
    )
    while dialogue['message']['content'] == '{}':
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=querent_llm,
            format='json',
            options={
                'temperature': 0.5,
                'top_p': 0.95,
                'top_k': 70
            }
        )
    end = time()
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue['message']['content']))
    answer = output_json
    with open(conf.triples_file, 'a') as f:
        f.write(json.dumps(answer) + '\n')

    turn = {
        "Q": question,
        "A": answer
    }
    conf.history_dict.append(turn)
    turn['Intent'] = intent

    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing entities in a 
            coherent way, do not modify it: {conf.history_dict[-20:]}"""
    })

    conf.turn_counter += 1
    return turn

async def gen_dialogue_turn_async(instructions, clear = False):

    if(clear):
        conf.chat_history.clear()
        conf.turn_counter = 0
        conf.history_dict = []

    conf.chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent Q (Questioner).

            You participate in a one-to-one conversation with Agent A. Your role is to select valid operations and ask questions 
            that allow the construction of structured domain knowledge.

            ### OBJECTIVE ###
            1. Select exactly ONE valid operation.
            2. Ask exactly ONE natural-language question corresponding to that operation.

            You NEVER answer questions.

            ### INTENTS ###
            Each operation is defined by:
            - description
            - required classes/entities
            - slots (data that must appear in the answer)
            - cardinality (frequency weight)

            Available intents:
            {[{
                i: {
                    'description': ops[i]['preconditions']['description'],
                    'preconditions': ops[i]['preconditions']['classes'],
                    'cardinality': ops[i]['preconditions']['cardinality']
                }
            } for i in ops if i in instructions]}

            You may ONLY use one of the intents listed above.

            ### DECISION RULES ###
            - Select an intent whose required entities already exist in the conversation history.
                - If there is no chat history, start by the intents without preconditions
            - The selected intent MUST be different from the one used in the immediately previous turn.
            - Prefer intents that have not been used recently.
            - If multiple intents are valid, prefer those used less frequently so far.
            - Intents with higher cardinality should be chosen more often, but not repeatedly if alternatives are available.
            - Ensure that all intents are eventually used across the dialogue.

            ### QUESTION RULES ###
            - Ask exactly ONE question.
            - The question MUST:
                - Explicitly reference ALL required entities using their IDs as reported in the chat history
                - Request ALL information needed to fulfill the intent (all slots)
                - Be natural and coherent with the conversation.
            - Keep the answer concise, don't make it too long

            ### STRICT PROHIBITIONS ###
            NEVER mention:
            - intents or operations
            - preconditions or postconditions
            - ontology or schema
            - rules or constraints

            ### OUTPUT FORMAT ###
            Return ONLY:
            {{
                "Intent": "<intent_name>",
                "Q": "<question>"
            }}
        """
    })
    conf.chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating a new question. Return only your answer to the prompt without any reasoniong"
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model=querent_llm,
        format='json',
        options={
            'temperature': 0.1,
            'top_p': 0.9,
            'top_k': 30
        }
    )
    if dialogue['message']['content'] == '':
        del conf.chat_history[0]
        conf.history_dict = []
        conf.turn_counter = 0
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=querent_llm,
            format='json',
            options={
                'temperature': 0.1,
                'top_p': 0.9,
                'top_k': 30
            }
        )
    end = time()
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue['message']['content']))
    intent = output_json["Intent"]
    question = output_json["Q"]

    intent_content = {
        'description': {str(ops[intent]['preconditions']['description'])},
        'slots': {str(ops[intent]['postconditions']['slots'] | ops[intent]['preconditions']['slots'])}
    }
    
    conf.chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent A (Answerer).

            You generate a STRICT structured JSON object that extends a persistent knowledge base of entities and facts.

            ---

            ### CORE BEHAVIOR ###
            This system is INCREMENTAL.

            Each turn is a PATCH to an existing database:
            - You ONLY output new information requested by the current intent
            - You MUST NOT reconstruct or repeat existing knowledge

            ---

            ### INPUT ###
            - Current question: {question}
            - Conversation history (contains all existing entities and facts)

            ---

            ### CURRENT INTENT ###
            {intent}: {intent_content}

            ---

            ### OBJECTIVE ###
            Produce a JSON object that:

            1. Fills ALL required intent slots
            2. Adds ONLY NEW entities introduced in this turn (if any)
            3. Uses EXISTING entities ONLY by ID reference
            4. Never duplicates or restates existing facts

            ---

            ### STATE RULE (CRITICAL) ###
            The conversation is a persistent state.

            You are NOT allowed to:
            - Re-describe existing entities
            - Repeat previously stated facts
            - Reprint attributes already known from history

            You are ONLY allowed to output:
            - New entities
            - New facts
            - Slot values required for this turn

            ---

            ### PRECONDITION RULE ###
            - Precondition entities MUST be referenced ONLY by ID
            - DO NOT expand or redefine pre-existing entities
            - DO NOT include full entity objects for preconditions

            ---

            ### ENTITY RULES ###
            - New entities only if strictly required by intent
            - IDs must be unique (FORMAT: AAA999)
            - Never reuse an existing ID
            - Existing entities must never be modified

            ---

            ### OUTPUT MINIMALITY RULE ###
            Your output must contain ONLY:
            - Required intent slots
            - New entities (if any)
            - References to existing entities (by ID only)

            NO additional fields are allowed.

            ---

            ### STRICT ANTI-REPETITION RULE ###
            It is strictly forbidden to:
            - Repeat entities from previous turns
            - Repeat facts already present in history
            - Restate known attributes in any form
            - Reconstruct full object state

            If information already exists → OMIT IT completely.

            ---

            ### OUTPUT FORMAT ###
            Return exactly one JSON object (single line):

            {{
                "<slot1>": "<value>",
                "<slot2>": "<value>",
                ...
            }}

            Rules:
            - Must be valid JSON
            - Must be flat (no nested objects for entities)
            - Must include ALL intent slots
            - Must NOT include redundant or historical data

            ---

            ### FAILURE CONDITIONS ###
            Output is INVALID if:
            - Any required slot is missing
            - Any precondition entity is expanded or duplicated
            - Any previously known fact is repeated
            - Any entity ID is reused incorrectly

            ---

            ### STRICT PROHIBITIONS ###
            Do NOT mention:
            - rules, schema, ontology
            - reasoning or internal state
            - explanations or commentary
        """
    })
    conf.chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating the answer to the last question. Return only your answer to the prompt without any reasoniong"
    })

    start = time()
    dialogue = await async_dialogue_client.chat(
        messages=conf.chat_history,
        model=witness_llm,
        format='json',
        options={
            'temperature': 0.5,
            'top_p': 0.95,
            'top_k': 70
        }
    )
    if dialogue['message']['content'] == '':
        del conf.chat_history[0]
        conf.history_dict = []
        conf.turn_counter = 0
        dialogue = await async_dialogue_client.chat(
            messages=conf.chat_history,
            model=querent_llm,
            format='json',
            options={
                'temperature': 0.5,
                'top_p': 0.95,
                'top_k': 70
            }
        )
    end = time()
    # print('[DEBUG] Ready!')
    conf.dialogue_timestamps.append({'start': start, 'end': end})

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    
    output_json = ast.literal_eval(repair_json(dialogue['message']['content']))
    answer = output_json
    with open(conf.triples_file, 'a') as f:
        f.write(json.dumps(answer) + '\n')

    turn = {
        "Q": question,
        "A": answer
    }
    conf.history_dict.append(turn)
    turn['Intent'] = intent

    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing entities in a 
            coherent way, do not modify it: {conf.history_dict[-20:]}"""
    })

    conf.turn_counter += 1
    return turn