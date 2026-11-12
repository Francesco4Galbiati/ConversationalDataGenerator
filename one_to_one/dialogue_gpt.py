import ast
import json
import conf
from time import time
from conf import ops, dialogue_client, querent_llm, witness_llm, redis
from json_repair import repair_json
from functions import least_used_precondition_ids
import intent_schedule

def gen_dialogue_turn(clear = False):

    if(clear):
        conf.chat_history.clear()
        conf.turn_counter = 0
        conf.history_dict = []

    scheduled = intent_schedule.next_intent() if conf.intent_selection == "schedule" else None
    shown_ops = {scheduled: ops[scheduled]} if scheduled else ops
    offered_ids = least_used_precondition_ids(shown_ops)
    if scheduled:
        selection_rules = f"""The generator has already chosen the intent for this turn: {scheduled}.
            Select exactly this intent and ignore INTENT HISTORY for the choice."""
    else:
        selection_rules = """Step 1 — Eligibility:
            - Keep only intents with an offered ID for every required slot of that intent

            Step 2 — Exclusions:
            - Do NOT select the most recent intent
            - Deprioritize intents frequent in INTENT HISTORY

            Step 3 — Selection:
            - Prefer least recently used intents
            - If only one valid intent exists → select it"""

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
            Eligible IDs are grouped by intent and slot:

            {json.dumps(offered_ids)}

            Rules:
            - Use only IDs listed for the selected intent and slot
            - Never invent entities
            - An intent is invalid if any required slot has an empty ID list

            ---

            ### INTENT HISTORY ###
            Last selected intents (oldest → most recent):

            {conf.intent_history}

            ---

            ### INTENTS ###
            Cardinality is the relative target frequency for choosing an eligible intent over multiple turns.
            Higher values mean more turns. A missing or zero value gives no frequency target.
            Available intents:

            {[
            {
                i: {
                    "description": ops[i]["preconditions"]["description"],
                    "required_entities": ops[i]["preconditions"]["classes"],
                    "cardinality": ops[i]["preconditions"]["cardinality"],
                }
            }
            for i in shown_ops
            ]}

            ---

            ### INTENT SELECTION RULES ###

            {selection_rules}

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

    del conf.chat_history[-2:]

    output_json = repair_json(dialogue['message']['content'], return_objects=True)
    intent = output_json["Intent"]
    if scheduled and intent != scheduled:   # the model ignored the scheduled intent: keep the schedule
        conf.schedule_overrides += 1
        intent = scheduled
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
    remaining = {slot: intent_schedule.remaining_options(slot) for slot in ops[intent]['postconditions']['slots']}
    remaining_text = [f"{slot.upper()}: {', '.join(map(str, opts))}" for slot, opts in remaining.items() if opts]
    conf.chat_history.append({
        'role': 'system',
        'content': (
            "ALREADY USED SLOTS (DO NOT repeat these):\n"
            + "\n".join(entities_text)
            + ("\n\nREMAINING ALLOWED VALUES (use exactly one of these, never a used or unlisted value):\n"
               + "\n".join(remaining_text) if remaining_text else "")
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
            - DO NOT repeat values contained in the ALREADY USED SLOTS section

            CUSTOM DATA TYPES:
            Refer to these data types to fill the slotsmarked with non-basic data types:
            {[
                {
                    t: {
                        "base_type": conf.types[t]['type'],
                        "description": conf.types[t]['text']
                    }
                }
                for t in conf.types if t in {**ops[intent]['preconditions']['slots'], **ops[intent]['postconditions']['slots']}.values()
            ]}

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
            model=witness_llm,
            format='json',
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

    output_json = repair_json(dialogue['message']['content'], return_objects=True)
    answer = output_json

    turn = {
        "Intent": intent,
        "Q": question,
        "A": answer
    }

    conf.turn_counter += 1
    return turn
