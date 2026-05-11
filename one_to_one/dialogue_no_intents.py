import ast
import json
import conf
from time import time
from conf import ops, dialogue_client, llm, precondition_slots, redis
from json_repair import repair_json

def gen_dialogue_turn(clear = False):

    if(clear):
        conf.chat_history.clear()
        conf.turn_counter = 0
        conf.history_dict = []

    with open('./resources/ontologies/lubm_ontology.owl', 'r') as f:
        ontology_text = f.read()

    competency_questions = """
        - Retrieve a new graduate student.
        - Retrieve a new undergraduate student.
        - Retrieve a new person who is a member of a department.
        - Retrieve a new publication authored by a specific professor.
        - Retrieve a new professor who works for a specific department.
        - Retrieve a new student who is a member of a specific department.
        - Retrieve a new student who takes a course taught by a specific professor.
        - Retrieve a new student who takes a course in a specific department.
        - Retrieve a new student who has an advisor.
        - Retrieve a new student advised by a specific professor.
        - Retrieve a new research group in a specific university.
        - Retrieve a new chair of a department in a specific university.
        - Retrieve a new alumnus of a specific university.
        - Retrieve a new person who is a member of a research group.
    """

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
            1) Select exactly ONE competency question (CQ)
            2) Generate exactly ONE grounded question from it

            You NEVER answer questions or add new facts.

            ---

            ### ONTOLOGY ###
            {ontology_text}

            The ontology defines:
            - entity types (classes)
            - relations
            - constraints

            You MUST respect it when interpreting competency questions.

            ---

            ### COMPETENCY QUESTIONS ###
            {competency_questions}

            Each CQ belongs to one of two types:

            ---

            ### CQ TYPES ###

            1) INDEPENDENT CQs
            - Do NOT require any entity IDs
            - Can always be instantiated directly
            Example:
            "Retrieve a new graduate student."
            "Retrieve a new research group in a university."

            2) DEPENDENT CQs
            - Require specific entity IDs to be instantiated
            - Depend on AVAILABLE ENTITIES
            Example:
            "Retrieve a new student advised by a specific professor."

            ---

            ### AVAILABLE ENTITIES ###
            Only these entity IDs may be used:

            {entities_text}

            Rules:
            - Only use IDs in this list
            - Never invent entities

            ---

            ### CQ HISTORY ###
            Previously used competency questions (oldest → most recent):

            {conf.intent_history}

            ---

            ### SELECTION RULES ###

            Step 1 — Candidate selection:
            - You may consider ALL CQs

            Step 2 — Feasibility check:
            - If a CQ is DEPENDENT:
                → it MUST use AVAILABLE ENTITIES
            - If a CQ is INDEPENDENT:
                → it can always be selected (no entity requirement)

            Step 3 — Entity-aware preference:
            - If AVAILABLE ENTITIES is NOT empty:
                → prefer DEPENDENT CQs that can be grounded
            - If AVAILABLE ENTITIES is empty:
                → ONLY select INDEPENDENT CQs

            Step 4 — Diversity:
            - Do NOT select the most recent CQ
            - Prefer less frequently used CQs

            Step 5 — Selection:
            - Choose exactly ONE valid CQ

            ---

            ### QUESTION GENERATION RULES ###

            Generate EXACTLY ONE grounded question based on the selected CQ.

            The question MUST:
            - Preserve the meaning of the CQ
            - Be instance-level (NOT abstract)
            - Use ONLY entity IDs from AVAILABLE ENTITIES when applicable
            - Use IDs as actual values (NOT placeholders or examples)

            STRICTLY FORBIDDEN:
            - "e.g.", "for example", "such as"
            - Inventing entity IDs
            - Turning dependent CQs into abstract statements

            ---

            ### OUTPUT FORMAT ###
            Return ONLY:

            {{
                "CQ": "<selected_competency_question>",
                "Q": "<grounded_question>"
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
        model=llm,
        format='json',
        options={
            'temperature': 0.1,
            'top_p': 0.9,
            'top_k': 30
        }
    )
    while dialogue['message']['content'] == '' or 'CQ' not in dialogue['message']['content'] or 'Q' not in dialogue['message']['content']:
        dialogue = dialogue_client.chat(
            messages=conf.chat_history,
            model=llm,
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
    intent = output_json["CQ"]
    question = output_json["Q"]
    conf.intent_history.append(intent)
    conf.intent_history = conf.intent_history[-10:]

    entities_text = []
    for key in redis.scan_iter("entities:*"):
        slot = key.split(":")[1]
        values = sorted(redis.smembers(key))
        if values:
            entities_text.append(
                f"{slot.upper()}: {', '.join(values)}"
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

            Generate a structured FLAT JSON object representing facts about entities.

            ---

            ### INPUT ###
            - Question: {question}
            - Competency Question (CQ): {intent}
            - Conversation history (contains entity IDs and state)

            ---
ß
            ### ONTOLOGY ###
            {ontology_text}

            The ontology defines:
            - entity types
            - relations
            - attributes

            You MUST use it to ensure semantic correctness.

            ---

            ### TASK ###

            Using:
            - the Question
            - the Competency Question (CQ)
            - the Ontology

            You must:

            1) Identify what real-world situation is described  
            2) Infer the appropriate set of attributes (a schema) needed to represent it  
            3) Output a FLAT JSON object containing all relevant fields  

            ---

            ### SCHEMA INFERENCE RULE ###

            Since NO intent/schema is provided:

            - You MUST infer the structure from:
            - the CQ
            - the ontology
            - the type of entities involved

            The output should resemble realistic attribute groupings such as:

            - student-related fields → student_id, student_name
            - professor-related fields → professor_id, professor_email, professor_name
            - department-related fields → department_id, department_name
            - etc.

            ---

            ### OUTPUT STRUCTURE (STRICT) ###

            - Output MUST be a flat JSON object
            - Keys MUST be:
            - meaningful attribute names
            - lowercase with underscores
            - consistent (e.g., student_id, professor_name)

            - Values MUST be:
            - entity IDs (for entities)
            - literals (for attributes)

            ---

            ### CORE RULES ###

            1. ENTITY GROUNDING

            - Extract all entity IDs from the question
            - MUST reuse them exactly in the output

            ---

            2. COMPLETENESS

            - The JSON MUST fully answer the CQ
            - Include ALL relevant attributes needed to describe the situation
            - Do NOT omit important fields

            ---

            3. ONTOLOGY CONSISTENCY

            - Respect entity types and relationships
            - Do NOT assign attributes to the wrong type:
                - student_email → student
                - professor_email → professor
                - etc.

            ---

            4. ATTRIBUTE GENERATION

            - If an attribute is not given:
                - generate a realistic value
                - keep it consistent with entity type

            ---

            5. NEW ENTITIES

            - Create new entities ONLY if required
            - ID format: 1–3 uppercase letters + 3 digits
            - Must be unique

            ---

            6. CONSISTENCY

            - Do not contradict history
            - Reuse known attributes when available

            ---

            ### IMPORTANT CONSTRAINTS ###

            - JSON MUST be flat:
                - NO nesting
                - NO lists
            - Do NOT include:
                - intent names
                - schema names
                - explanations

            ---

            ### OUTPUT FORMAT ###
            Return ONLY one JSON object.

            ---

            ### FAIL CONDITIONS ###
            Regenerate if:
            - missing entity from question
            - inconsistent attribute naming
            - attributes assigned to wrong entity type
            - nested JSON appears
            - incomplete answer to CQ
        """
    })
    conf.chat_history.append({
        "role": "user",
        "content": "Continue the dialogue according to the system instructions by generating the answer to the last question. Return only your answer to the prompt without any reasoniong"
    })

    start = time()
    dialogue = dialogue_client.chat(
        messages=conf.chat_history,
        model=llm,
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
            model=llm,
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