import ast
import json
from time import time

import conf
from conf import dialogue_client, newl, ops, querent_llm, types_def, witness_llm, precondition_slots, redis
from json_repair import repair_json

def gen_dialogue_turn(instructions, clear=False, n=3, triples_file=None):

    if clear:
        conf.chat_history.clear()
        conf.history_dict = []
        conf.chat_histories = [[] for _ in range(n)]
        conf.turn_counter = 0

    entities_text = []
    for slot in precondition_slots:
        ids = redis.smembers(f"entities:{slot}:idx0")
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
                for i in ops if i in instructions
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
        """,
    })
    conf.chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating a new question. Return only your answer to the prompt without any reasoniong",
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model=querent_llm,
        format="json",
        options={
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 30,
        },
    )
    while dialogue["message"]["content"] == '':
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=querent_llm,
            format="json",
            options={
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 30,
            },
        )
    end = time()
    conf.querent_time += (end - start)

    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()
    if len(conf.chat_history) != 0:
        conf.chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue["message"]["content"]).replace('null', 'None'))
    intent = output_json["Intent"]
    question = output_json["Q"]
    intent_content = {
        'description': {str(ops[intent]['preconditions']['description'])},
        'preconditions_slots': {str(ops[intent]['preconditions']['slots'])},
        'postconditions_slots': {str(ops[intent]['postconditions']['slots'])}
    }

    # Broadcast the exact same question to every answerer, while keeping each
    # answerer's evolving world state fully separated from the others.
    branch_turns = []
    branch_answers = []
    for answerer_idx in range(n):
        entities_text = []
        for slot in ops[intent]['postconditions']['slots']:
            slots = sorted(redis.smembers(f"entities:{slot}:idx{answerer_idx}"))
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
                - Format: 1-3 uppercase letters + 3 digits
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
            """,
        })
        conf.chat_history.append({
            "role": "user",
            "content": "Continue the dialogue according to the system instructions by generating the answer to the last question. Return only your answer to the prompt without any reasoniong",
        })

        start = time()
        answerer_temperature = min(0.6, 0.3 + (0.1 * answerer_idx))
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=witness_llm,
            format="json",
            options={
                "temperature": answerer_temperature,
                "top_p": 0.95,
                "top_k": 70,
            },
        )
        while dialogue["message"]["content"] == "":
            dialogue = dialogue_client.chat(
                messages=conf.chat_history,
                model=witness_llm,
                format="json",
                options={
                    "temperature": answerer_temperature,
                    "top_p": 0.95,
                    "top_k": 70,
                },
            )
        end = time()
        conf.witness_time += (end - start)

        if len(conf.chat_history) != 0:
            conf.chat_history.pop()
        if len(conf.chat_history) != 0:
            conf.chat_history.pop()
        if len(conf.chat_history) != 0:
            conf.chat_history.pop()

        answer = ast.literal_eval(repair_json(dialogue["message"]["content"]).replace('null', 'None'))

        if answerer_idx > 0:
            ids = [key for key in answer.keys() if '_id' in key]
            for id in ids:
                answer[id] = branch_answers[0][id]

        # Write only the answerer's JSON so downstream RDF extraction can read
        # the file line by line without topology metadata.
        target = conf.triples_files[answerer_idx]
        if target is not None:
            with open(target, "a") as f:
                f.write(f'{intent}: ' + json.dumps(answer) + "\n")

        branch_answers.append(answer)
        branch_turns.append({
            "answerer_id": answerer_idx,
            "Intent": intent,
            "Q": question,
            "A": answer,
        })

    conf.turn_counter += 1
    return {
        "Intent": intent,
        "Q": question,
        "branches": branch_turns,
    }
