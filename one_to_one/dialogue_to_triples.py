import ast
import json
import conf
from time import time
from conf import ops, dialogue_client, querent_llm, witness_llm, precondition_slots, redis
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
            + "\n".join(entities_text[-3:])
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
            Use only entities already present in the chat history.

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
                    "required_entities": ops[i]["preconditions"]["classes"]
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
    while dialogue['message']['content'] == '' or 'Intent' not in dialogue['message']['content'] or 'Q' not in dialogue['message']['content']:
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

            Your task is to:
            1) Interpret the intent
            2) Fill all required slots
            3) Convert results into RDF triples

            You MUST output ONLY RDF triples.

            ---

            ### INPUT ###
            - Question: {question}
            - Conversation history

            ---

            ### INTENT ###
            {intent}

            ---

            ### SLOT CONTRACT ###
            {intent_content}

            All slots defined in the intent MUST be filled.

            ---

            ### SLOT → RDF MAPPING ###
            {str(ops[intent]['postconditions']['triples'])}

            This mapping defines EXACTLY how slots must be converted into RDF triples.
            You MUST follow it strictly.

            ---

            # =========================
            # RDF SYSTEM RULES (HARD LOCK)
            # =========================

            ### 1. OUTPUT MODE (ABSOLUTE RULE) ###
            You are in RDF generation mode.

            ONLY valid output: RDF triples in N-TRIPLES format.

            NO OTHER OUTPUT IS ALLOWED.

            This includes:
            - JSON ❌
            - dictionaries ❌
            - key-value objects ❌
            - graph structures ❌
            - nested representations ❌
            - explanations ❌
            - error messages ❌
            - empty output ❌

            Even if semantically equivalent.

            ---

            ### 2. FORBIDDEN OUTPUT STRUCTURES ###

            You MUST NOT output:

            - {{"subject": "..."}} structures
            - adjacency lists
            - grouped predicates per subject
            - any JSON-like representation
            - any dictionary-like structure

            ONLY flat RDF triples are valid.

            ---

            ### 3. FAILURE HANDLING (FORCED COMPLETION) ###

            If information is missing or ambiguous:

            - ALWAYS continue generation
            - NEVER refuse
            - NEVER output errors
            - NEVER output JSON
            - Use best-effort completion

            ---

            ### 4. ENTITY GENERATION RULE ###

            If a new entity is required:

            - Generate a unique ID: uppercase letters + digits (e.g., G1000, D2000)
            - Convert to RDF IRI:
            <http://example.org/G1000>

            - IDs MUST be reused consistently across triples

            ---

            ### 5. LITERAL REALISM RULE (IMPORTANT) ###

            All literal values MUST be realistic and human-like.

            STRICT RULES:

            - DO NOT use placeholders like:
            "New Student", "StudentName", "DepartmentName", "UniversityName", "Example"

            - PERSON NAMES MUST be realistic:
            e.g., "Emma Carter", "Lucas Meyer", "Sofia Alvarez", "Daniel Kim"

            - ORGANIZATIONS MUST be realistic:
            e.g., "Department of Computer Science", "Northbridge University"

            - EMAILS MUST be realistic if used:
            firstname.lastname@university.edu

            - Avoid repetition of generic patterns across entities

            ---

            ### 6. NATURALISTIC GENERATION PRIORITY ###

            When multiple valid values exist:

            1. Prefer realistic academic or institutional names
            2. Ensure diversity across entities
            3. Avoid template-like naming
            4. Ensure coherence within generated world

            ---

            ### 7. RDF FORMALISM ###

            You MUST output RDF triples in strict N-TRIPLES format:

            <subject> <predicate> <object> .

            RULES:
            - One triple per line
            - Each triple ends with a dot
            - No grouping
            - No indentation structure
            - No JSON or structured output

            ---

            ### 8. IRI RULES ###

            - Entity IDs → <http://example.org/ID>
            - rdf:type → <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
            - names → <http://example.org/name>
            - other predicates → as defined in mapping under http://example.org/

            ---

            ### 9. CONSISTENCY RULES ###

            - Generated entities MUST remain consistent across triples
            - Do not rename entities
            - Do not mix representations

            ---

            ### 10. NO STRUCTURED OUTPUT RULE (CRITICAL) ###

            You MUST NOT output RDF as:

            - JSON
            - dictionaries
            - key-value objects
            - graph structures
            - adjacency lists

            ONLY flat RDF triples are valid.

            ---

            ### OUTPUT FORMAT ###

            Return ONLY RDF triples:

            <subject> <predicate> <object> .
            <subject> <predicate> <object> .
            <subject> <predicate> <object> .
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
        format='',
        options={
            'temperature': 0.3,
            'top_p': 0.95,
            'top_k': 70
        }
    )
    while dialogue['message']['content'] == '':
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=witness_llm,
            format='',
            options={
                'temperature': 0.3,
                'top_p': 0.95,
                'top_k': 70
            }
        )
    end = time()
    conf.witness_times[0] += (end - start)

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    answer = dialogue['message']['content']
    with open(conf.triples_file, 'a') as f:
        f.write(f'{intent}: ' + answer + '\n')

    turn = {
        "Intent": intent,
        "Q": question,
        "A": answer
    }

    conf.turn_counter += 1
    return turn