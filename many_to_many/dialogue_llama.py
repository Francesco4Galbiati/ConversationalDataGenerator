import ast
import conf
import json
from time import time
from conf import dialogue_client, ops, querent_llm, witness_llm, precondition_slots, redis
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
            You are Agent Q.

            Your task:
            1) Choose ONE valid intent
            2) Ask ONE question for it

            Do NOT answer. Do NOT invent entities.

            ---

            ### AVAILABLE ENTITIES ###
            Use ONLY these IDs:

            {entities_text}

            Rules:
            - Use IDs EXACTLY as written
            - If a type has no IDs → it cannot be used

            ---

            ### INTENT HISTORY ###
            Recent intents:
            {conf.intent_history}

            ---

            ### INTENTS ###
            {[
            {
                "name": i,
                "required_entities": ops[i]["preconditions"]["classes"]
            }
            for i in ops if i in instructions
            ]}

            ---

            ### VALID INTENTS ###

            An intent is VALID if:
            ALL its required entity types have at least ONE ID available.

            ALL other intents are INVALID. Ignore them completely.

            ---

            ### SELECTION ###

            From VALID intents:

            - Do NOT pick the most recent intent
            - Otherwise pick ANY valid intent

            ---

            ### QUESTION ###

            Generate ONE question.

            Rules:
            - Use REAL IDs from AVAILABLE ENTITIES
            - Include ALL required entity types
            - IDs must appear EXACTLY as written
            - Do NOT use placeholders like "id"

            Write a natural question that matches the intent.

            ---

            ### OUTPUT ###
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
    conf.intent_history.append(intent)
    conf.intent_history = conf.intent_history[-10:]
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
                You are Agent A.

                Generate ONE JSON object that fills all slots.

                ---

                ### INPUT ###
                - Question: {question}
                - Conversation history

                ---

                ### INTENT ###
                {intent}: {intent_content}

                ---

                ### SLOTS ###
                You MUST output exactly these slots:

                {intent_content['preconditions_slots'] | intent_content['postconditions_slots']}

                Rules:
                - ALL slots must appear
                - NO extra slots

                ---

                ### CORE RULES ###

                1. QUESTION GROUNDING (STRICT)

                - Extract ALL entity IDs from the question
                - These are PRECONDITION entities
                - You MUST reuse them EXACTLY

                ---

                2. PRECONDITION SLOTS (MANDATORY)

                If an entity ID appears in the question:
                - Its slot MUST be present
                - The value MUST be that exact ID

                ---

                3. SLOT FILLING (STRICT)

                For each slot:

                A. ID slots:
                - MUST contain a valid ID
                - If present in question → use it
                - Otherwise → generate a NEW valid ID (if required)

                B. ATTRIBUTE slots (name, email, etc.):
                - MUST NOT be null
                - If value is in question → use it
                - Otherwise → generate a realistic value

                Use null ONLY if:
                - the slot is optional AND
                - no value can be generated

                ---

                4. NEW ENTITIES

                Create ONLY if required.

                Rules:
                - ID format: 1–3 uppercase letters + 3 digits
                - MUST be new (never reused)

                ---

                5. CONSISTENCY

                - Do not change existing IDs
                - Do not contradict known data

                ---

                ### IMPORTANT ###

                - IDs in the question are REAL values
                - NEVER replace or ignore them
                - ATTRIBUTE slots should be filled, not left empty

                ---

                ### OUTPUT ###

                Return ONLY:

                {{
                "<slot1>": "<value>",
                "<slot2>": "<value>"
                }}
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
        conf.witness_times[answerer_idx] += (end - start)

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
