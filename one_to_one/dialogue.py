import ast
import json
import conf
from time import time
from conf import ops, dialogue_client, newl, types_def, async_dialogue_client, witness_llm, querent_llm, precondition_slots, redis
from json_repair import repair_json

def gen_dialogue_turn(clear = False):

    if(clear):
        conf.chat_history.clear()
        conf.turn_counter = 0
        conf.history_dict = []

    entities_text = []
    for slot in precondition_slots:
        ids = redis.smembers(f"entities:{slot}")
        if ids:
            entities_text.append(
                f"{slot.upper()}: {', '.join(ids)}"
            )
    conf.chat_history.append({
        'role': 'system',
        'content': (
            "AVAILABLE ENTITY IDS (use only these):\n"
            + "\n".join(entities_text)
        )
    })

    conf.chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent Q (Questioner).

            Task:
            1) Select exactly ONE valid intent
            2) Ask exactly ONE question for it

            You NEVER answer questions or add new information.

            ---

            ### AVAILABLE ENTITIES ###
            Only these entity IDs may be used:

            {entities_text}

            Rules:
            - Only use IDs in this list
            - Never invent entities
            - If a required entity type has no available IDs → the intent is invalid

            ---

            ### INTENT HISTORY ###
            Last selected intents (oldest → most recent):

            {conf.intent_history}

            ---

            ### INTENTS ###
            Available intents:

            {[
            {
                i: {
                    "description": ops[i]["preconditions"]["description"],
                    "required_entities": ops[i]["preconditions"]["classes"],
                    "selection_weight": ops[i].get("selection_weight", 1)
                }
            }
            for i in ops
            ]}

            ---

            ### INTENT SELECTION RULES ###

            Step 1 — Eligibility:
            - Keep only intents whose required entity types exist in AVAILABLE ENTITIES

            Step 2 — Exclusions:
            - Do NOT select the most recent intent
            - Deprioritize intents frequent in INTENT HISTORY

            Step 3 — Selection:
            - Prefer least recently used intents
            - Use selection_weight for long-term balance
            - If only one valid intent exists → select it

            ---

            ### QUESTION RULES ###

            Generate EXACTLY ONE question.

            The question MUST:
            - Use ONLY entity IDs from AVAILABLE ENTITIES
            - Include ALL required entity types using real IDs
            - Use IDs as actual values (NOT examples)
            - Be natural and unambiguous

            STRICTLY FORBIDDEN:
            - Using example patterns such as "e.g.", "for example", "such as"
            - Presenting IDs as illustrations instead of actual values

            If multiple valid entities exist:
            → choose any, but avoid repeating recent combinations

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
    while dialogue['message']['content'] == '':
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
    conf.querent_time += (end - start)

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue['message']['content']).replace('null', 'None'))
    intent = output_json["Intent"]
    question = output_json["Q"]
    conf.intent_history.append(intent)
    conf.intent_history = conf.intent_history[-10:]

    intent_content = {
        'description': {str(ops[intent]['preconditions']['description'])},
        'preconditions_slots': {str(ops[intent]['preconditions']['slots'])},
        'postconditions_slots': {str(ops[intent]['postconditions']['slots'])}
    }

    entities_text = []
    for slot in ops[intent]['postconditions']['slots']:
        slots = sorted(redis.smembers(f"entities:{slot}"))
        if slots:
            entities_text.append(
                f"{slot.upper()}: {', '.join(slots)}"
            )
    conf.chat_history.append({
        'role': 'system',
        'content': (
            "ALREADY USED SLOTS (DO NOT repeat these):\n"
            + "\n".join(entities_text)
        )
    })
    
    conf.chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent A (Answerer).

            Generate a structured JSON answer that extends a consistent world of entities and facts.

            ---

            ### INPUT ###
            - Question: {question}
            - Conversation history (contains entity IDs and state)

            ---

            ### INTENT ###
            {intent}: {intent_content}

            ---

            ### SLOT CONTRACT (STRICT) ###
            You MUST output ALL slots defined in the intent.

            This includes:
            - precondition slots (entities already mentioned)
            - postcondition slots (new entities or attributes)

            Rules:
            - No missing slots
            - No extra slots

            ---

            ### CORE RULES ###

            1. SLOT FILLING & ENTITY COMPLETENESS (UNIFIED)

            For each slot:

            - If the value is explicitly in the question → MUST use it
            - If the slot is a precondition and appears in the question → MUST be included in output
            - If the slot refers to an attribute (name, email, telephone):
                - If available in history for that entity → use it
                - Otherwise → generate a consistent value tied to the entity

            Use null ONLY if:
            - the value cannot be derived from the question
            AND
            - cannot be inferred from entity context

            IMPORTANT:
            - Attributes belong to entities, not independent values
            - Never generate values that contradict known entity data

            ---

            2. QUESTION GROUNDING

            - Extract all entity IDs explicitly mentioned in the question
            - These define the precondition entities
            - These IDs MUST be reused exactly in the output

            ---

            3. PRECONDITION ENFORCEMENT (STRICT)

            If a precondition entity appears in the question:

            - You MUST include its corresponding slot in the output
            - You MUST use the exact ID from the question
            - You MUST NOT omit it

            Preconditions are REQUIRED output fields, not optional context.

            ---

            4. NEW ENTITIES (POSTCONDITIONS)

            - Create new entities ONLY if required by the intent
            - New IDs must be globally unique
            - Format: 1–3 uppercase letters + 3 digits
            - NEVER reuse an existing ID for a NEW entity

            ---

            5. CONSISTENCY

            - Do not contradict history
            - Do not reuse IDs incorrectly
            - Preserve established facts across turns

            ---

            ### NOVELTY (SOFT CONSTRAINT) ###
            When multiple valid choices exist:
            - prefer less recently used entities
            - avoid repeating identical combinations

            Do NOT violate correctness for novelty.

            ---

            ### OUTPUT FORMAT ###
            Return ONLY one JSON object:

            {{
                "<slot1>": "<value>",
                "<slot2>": "<value>"
            }}

            ---

            ### FAIL CONDITIONS ###
            Regenerate if:
            - any slot is missing
            - a precondition slot is omitted
            - an invalid entity ID is used
            - a contradiction with history occurs
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
            'temperature': 0.3,
            'top_p': 0.95,
            'top_k': 70
        }
    )
    while dialogue['message']['content'] == '':
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=querent_llm,
            format='json',
            options={
                'temperature': 0.3,
                'top_p': 0.95,
                'top_k': 70
            }
        )
    end = time()
    conf.witness_time += (end - start)

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue['message']['content']).replace('null', 'None'))
    answer = output_json
    with open(conf.triples_file, 'a') as f:
        f.write(f'{intent}: ' + json.dumps(answer) + '\n')

    turn = {
        "Intent": intent,
        "Q": question,
        "A": answer
    }

    conf.turn_counter += 1
    return turn

async def gen_dialogue_turn_async(clear = False):

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
            } for i in ops]}

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
            'num_predict': 2048,
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
                'num_predict': 2048,
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

            Your task is to generate a structured JSON answer that extends a consistent world of entities and facts.

            ---

            ### PRIMARY REQUIREMENT (HIGHEST PRIORITY) ###
            Your output MUST be a valid JSON object that includes:

            1. ALL slots defined by the current intent
            2. ALL precondition entities (with their attributes)
            3. ALL newly created entities (if required)

            If ANY of the above is missing, the output is INVALID.

            ---

            ### INPUT ###
            - Current question: {question}
            - Conversation history

            ---

            ### CURRENT INTENT ###
            {intent}: {intent_content}

            ---

            ### OBJECTIVE ###
            Generate the answer by:

            1. Filling ALL intent slots
            2. Including ALL precondition entities with their attributes
            3. Introducing required new entities
            4. Maintaining full consistency with the conversation history

            ---

            ### PRECONDITION ENFORCEMENT ###
            - ALL entities required by the intent preconditions MUST appear in the JSON
            - You MUST reuse their EXACT IDs from the conversation history

            CRITICAL:
            - Precondition entities MUST be referenced by ID ONLY
            - DO NOT regenerate or expand their attributes
            - DO NOT duplicate previously defined entity data

            Preconditions are REQUIRED as references, NOT as full entity definitions.

            ---

            ### ENTITY RULES ###
            - Create new entities ONLY if required
            - Assign UNIQUE IDs:
                - Format: 1-3 uppercase letters + 3 digits
                - Prefix must match entity type
                - NEVER reuse an ID used in a previous conversation turn for a new entity

            - ONLY newly created entities should include attributes
            - EXISTING entities must NEVER be redefined or expanded

            ### ID CONSISTENCY (STRICT) ###
            - IDs are globally unique across the entire conversation
            - Before assigning a new ID:
            1. Check if it already exists in the conversation history
            2. If it exists → YOU MUST NOT use it

            - If unsure → generate a NEW higher-numbered ID
            (e.g., if U001-U010 exist → use U011 or higher)

            - Reusing an existing ID for a different entity = INVALID OUTPUT

            ---

            ### CONSISTENCY RULES ###
            - Preserve all previously established facts
            - Do not contradict earlier information
            - Use context only to resolve references (do not re-answer previous turns)
            - DO NOT repeat answers from previous turns

            ---

            ### DATA CONSTRAINTS ###
            {newl.join([types_def[t]['text'] for t in types_def if t != 'id']) if len([t for t in types_def if t != 0]) != 0 else ""}

            ---

            ### OUTPUT CONTRACT (STRICT) ###
            Return EXACTLY one JSON object (single line, JSONL) like this:
            {{
                "<slot1>": "<value-or-null>",
                "<slot2>": "<value-or-null>",
                ...
            }}

            The JSON must include:
            - ALL slots defined by the current intent
            - Precondition entities ONLY as ID references (within relevant slots)
            - Newly created entities ONLY if required by the intent

            Do NOT:
            - Add extra keys outside the intent schema
            - Inline or expand existing entities

            ---

            ### FAILURE CONDITIONS ###
            Regenerate internally if:
            - Any slot is missing
            - Any precondition entity is missing
            - Any required attribute is missing
            - Any entity ID is incorrect or inconsistent

            ---

            ### STRICT PROHIBITIONS ###
            Do NOT mention:
            - intents, operations
            - schema, ontology
            - rules or constraints
            - internal reasoning
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
            'temperature': 0.3,
            'num_predict': 2048,
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
                'temperature': 0.3,
                'num_predict': 2048,
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
        f.write(f'{intent}: ' + json.dumps(answer) + '\n')

    turn = {
        "Q": question,
        "A": answer
    }
    conf.history_dict.append(turn)
    turn['Intent'] = intent

    '''
    for turn in conf.history_dict[-20:]:
        conf.chat_history.append({
            'role': 'User',
            'content': turn
        })
    '''
    
    conf.chat_history.append({
        'role': 'user',
        'content': f"""This is the history of previous conversations, use it only to reference already existing entities in a 
            coherent way, do not modify it: {conf.history_dict[-20:]}"""
    })

    conf.turn_counter += 1
    return turn