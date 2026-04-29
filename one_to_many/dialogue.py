import ast
import json
from time import time

import conf
from conf import dialogue_client, newl, ops, querent_llm, types_def, witness_llm
from json_repair import repair_json

def gen_dialogue_turn(clear=False, n=3, allowed_ops=ops, triples_file=None):

    if clear:
        conf.chat_history.clear()
        conf.history_dict = []
        conf.chat_histories = [[] for _ in range(n)]
        conf.turn_counter = 0

    question_chat_history = conf.chat_history

    question_chat_history.append({
        "role": "system",
        "content": f"""
            ### ROLE ###
            You are Agent Q (Questioner).

            You are in a one-to-many setting:
            - you ask ONE question
            - the SAME question will be sent to multiple independent answerers
            - each answerer has its own separate world state
            - answerers do NOT see each other
            - answerers may diverge over time

            Your ONLY task is to:
            1) Select exactly ONE valid intent
            2) Ask exactly ONE question corresponding to that intent

            You NEVER answer questions.
            You NEVER introduce new information.

            ---

            ### CRITICAL FRAMEWORK CONSTRAINT ###
            Because the same question is broadcast to multiple isolated answerers, your question must be valid for ALL answerers.

            Therefore you MUST use ONLY shared context.

            Shared context means:
            - entities already present in the shared questioner history
            - entities that are guaranteed to be known by every answerer branch

            You MUST NOT use branch-specific context.

            Branch-specific context means:
            - entities that may have been created by only one answerer
            - facts that may exist in only one answerer conversation
            - follow-up references that are not guaranteed to exist in every branch

            If a question depends on branch-specific context, it is INVALID.

            ---

            ### ENTITY RULES ###
            You MUST ONLY use entities that already exist in the shared conversation history.

            - NEVER introduce a new entity
            - NEVER guess or invent entity names or IDs
            - EVERY entity mentioned in your question MUST already exist in shared history
            - you MUST reuse the EXACT entity IDs already seen
            - If a required entity is missing -> DO NOT select that intent

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
                    "description": allowed_ops[i]["preconditions"]["description"],
                    "required_entities": allowed_ops[i]["preconditions"]["classes"],
                    "cardinality": allowed_ops[i]["preconditions"]["cardinality"],
                }
            } for i in allowed_ops]}

            You may ONLY select from this list.

            ---

            ### DECISION RULES ###
            You MUST follow ALL rules:

            1. VALIDITY
            - Select an intent ONLY if ALL its required entities are already present in shared history
            - If no history exists -> select an intent with NO required entities

            2. SHARED-CONTEXT SAFETY
            - The question must be answerable by every answerer branch
            - Do not rely on any entity or fact that might exist in only one branch
            - Prefer intents grounded in stable shared entities

            3. ENTITY CONSISTENCY
            - You may ONLY reference entities that already appeared in shared history
            - You MUST reuse their EXACT IDs (no variation, no paraphrasing)

            4. DIVERSITY
            - The selected intent MUST be different from the immediately previous turn whenever any other valid intent exists
            - Repeat the immediately previous intent ONLY if it is the only valid intent under the shared context constraints
            - Prefer intents used less frequently
            - Prefer broader coverage over repeating the same pattern

            ---

            ### QUESTION RULES ###
            You must generate EXACTLY ONE question.

            The question MUST:
            - Explicitly include ALL required entities (using their EXACT IDs from history)
            - ONLY include shared entities already mentioned in the conversation
            - NOT introduce any new entity (strictly forbidden)
            - Request ALL required information (all slots)
            - Be natural and coherent
            - Remain branch-agnostic, so that all answerers can respond independently

            The question MUST NOT:
            - Depend on a fact introduced by only one answerer
            - Mention a branch-local entity
            - Continue a follow-up that only makes sense in one branch

            ---

            ### SELF-CHECK BEFORE OUTPUT (MANDATORY) ###
            Before answering, verify:

            - Did I introduce ANY new entity? -> If yes, REGENERATE
            - Are ALL entities in the question present in shared history? -> If no, REGENERATE
            - Could EVERY answerer branch understand and answer this same question? -> If no, REGENERATE
            - Am I repeating the immediately previous intent even though another valid intent exists? -> If yes, REGENERATE
            - Did I include ALL required entities? -> If no, REGENERATE
            - Did I ask exactly ONE question? -> If no, REGENERATE

            ---

            ### STRICT PROHIBITIONS ###
            NEVER mention:
            - intents or operations
            - rules, constraints, or validation steps
            - ontology, schema, or structure
            - branch logic or internal reasoning

            ---

            ### OUTPUT FORMAT ###
            Return ONLY:

            {{
                "Intent": "<intent_name>",
                "Q": "<question>"
            }}
        """,
    })
    question_chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating a new question. Return only your answer to the prompt without any reasoniong",
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=question_chat_history,
        model=querent_llm,
        format="json",
        options={
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 30,
        },
    )
    while dialogue["message"]["content"] == "":
        dialogue = dialogue_client.chat(
            messages=question_chat_history,
            model=querent_llm,
            format="json",
            options={
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 30,
            },
        )
    end = time()
    conf.dialogue_timestamps.append({"start": start, "end": end})

    if len(question_chat_history) != 0:
        question_chat_history.pop()
    if len(question_chat_history) != 0:
        question_chat_history.pop()

    output_json = ast.literal_eval(repair_json(dialogue["message"]["content"]))
    intent = output_json["Intent"]
    question = output_json["Q"]
    intent_content = {
        "description": str(ops[intent]["preconditions"]["description"]),
        "slots": str(ops[intent]["postconditions"]["slots"] | ops[intent]["preconditions"]["slots"]),
    }

    # Broadcast the exact same question to every answerer, while keeping each
    # answerer's evolving world state fully separated from the others.
    branch_turns = []
    branch_answers = []
    for answerer_idx in range(n):
        answerer_history_dict = conf.chat_histories[answerer_idx]
        answerer_chat_history = [{
            "role": "user",
            "content": f"""This is the history of previous conversations, use it only to reference already existing entities in a 
            coherent way, do not modify it: {answerer_history_dict[-20:]}""",
        }] if len(answerer_history_dict) != 0 else []

        answerer_chat_history.append({
            "role": "system",
            "content": f"""
                ### ROLE ###
                You are Agent A (Answerer).

                Your task is to generate a structured JSON answer that extends a consistent world of entities and facts.

                You are one of multiple independent answerers receiving the same question.
                You are answerer branch {answerer_idx + 1} out of {n}.
                Your answer should stay compatible with the shared entity structure of the question, but you should prefer diversity in non-ID attribute values whenever that does not violate the intent or the conversation history.

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

                ### CROSS-BRANCH ID ALIGNMENT ###
                - If the question refers to an existing entity, you MUST reuse the exact same ID
                - If this answer creates a new entity that is the direct answer to the shared broadcast question, prefer a stable, canonical ID choice rather than an arbitrary one
                - Keep IDs stable; vary attributes, not identity

                ### CROSS-BRANCH DIVERSITY ###
                - Prefer diversity in non-ID attribute values across answerers
                - Different answerers should try to generate different attribute values when multiple valid answers are possible
                - Use your branch identity to avoid collapsing to the most obvious/default attribute values
                - Diversity MUST NEVER change the identity of already referenced entities
                - Diversity MUST NEVER violate the current intent, required slots, or prior branch history

                ### ID CONSISTENCY (STRICT) ###
                - IDs are globally unique across the entire conversation
                - Before assigning a new ID:
                1. Check if it already exists in the conversation history
                2. If it exists -> YOU MUST NOT use it

                - If unsure -> generate a NEW higher-numbered ID
                - Reusing an existing ID for a different entity = INVALID OUTPUT

                ---

                ### CONSISTENCY RULES ###
                - Preserve all previously established facts
                - Do not contradict earlier information
                - Use context only to resolve references (do not re-answer previous turns)
                - DO NOT repeat answers from previous turns

                ---

                ### DATA CONSTRAINTS ###
                {newl.join([types_def[t]["text"] for t in types_def if t != "id"]) if len([t for t in types_def if t != "id"]) != 0 else ""}

                ---

                ### OUTPUT CONTRACT (STRICT) ###
                Return EXACTLY one JSON object (single line, JSONL) like this:
                {{
                    "<slot1>": "<value-or-null>",
                    "<slot2>": "<value-or-null>"
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
            """,
        })
        answerer_chat_history.append({
            "role": "user",
            "content": "Continue the dialogue according to the system instructions by generating the answer to the last question. Return only your answer to the prompt without any reasoniong",
        })

        start = time()
        answerer_temperature = min(0.6, 0.3 + (0.1 * answerer_idx))
        dialogue = dialogue_client.chat(
            messages=answerer_chat_history,
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
                messages=answerer_chat_history,
                model=witness_llm,
                format="json",
                options={
                    "temperature": answerer_temperature,
                    "top_p": 0.95,
                    "top_k": 70,
                },
            )
        end = time()
        conf.dialogue_timestamps.append({"start": start, "end": end})

        if len(answerer_chat_history) != 0:
            answerer_chat_history.pop()
        if len(answerer_chat_history) != 0:
            answerer_chat_history.pop()

        answer = ast.literal_eval(repair_json(dialogue["message"]["content"]))

        # Write only the answerer's JSON so downstream RDF extraction can read
        # the file line by line without topology metadata.
        target = triples_file or getattr(conf, "triples_file", None)
        if target is not None:
            with open(target, "a") as f:
                f.write(json.dumps(answer) + "\n")

        turn = {
            "Intent": intent,
            "Q": question,
            "A": answer,
        }
        answerer_history_dict.append(turn)
        branch_answers.append(answer)

        branch_turns.append({
            "answerer_id": answerer_idx,
            "Intent": intent,
            "Q": question,
            "A": answer,
        })

    # The broadcaster can only safely reuse facts that are present with the
    # same value in every branch. This prevents it from following up on
    # branch-specific entities while still giving it enough context to move
    # past the starting intent.
    shared_answer = {}
    if len(branch_answers) != 0:
        common_keys = set(branch_answers[0].keys())
        for answer in branch_answers[1:]:
            common_keys &= set(answer.keys())

        for key in common_keys:
            value = branch_answers[0][key]
            if value == "None" or value is None:
                continue
            if all(answer[key] == value for answer in branch_answers[1:]):
                shared_answer[key] = value

    question_turn = {
        "Intent": intent,
        "Q": question,
        "A": shared_answer,
    }
    conf.history_dict.append(question_turn)
    question_chat_history.append({
        "role": "user",
        "content": f"""This is the history of previous conversations, use it only to reference already existing entities in a 
            coherent way, do not modify it: {conf.history_dict[-20:]}""",
    })

    conf.turn_counter += 1
    return {
        "Intent": intent,
        "Q": question,
        "branches": branch_turns,
    }
