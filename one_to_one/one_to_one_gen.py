import asyncio
from conf import bcolors, ops, hallucinations, parallelization, redis
from agents import parser_agent
from functions import  replace_ids, dict_keys_to_snake, update_world_state
from one_to_one.dialogue import gen_dialogue_turn, gen_dialogue_turn_async

async def __launch__(triples):

    n_t = 0
    next_dialogue = None
    i = 1

    while n_t < triples:

        if parallelization:
            if n_t == 0:
                parser_agent.run(user_prompt="")
                dialogue_turn = gen_dialogue_turn()
                next_dialogue = asyncio.create_task(gen_dialogue_turn_async())
            else:
                dialogue_turn = await next_dialogue
                next_dialogue = asyncio.create_task(gen_dialogue_turn_async())
        else:
            dialogue_turn = gen_dialogue_turn()

        t = dialogue_turn
        if 'Intent' in t and 'Q' in t and 'A' in t:
            intent = t['Intent']
            question = t['Q']
            answer = t['A']
        else:
            hallucinations['dictionary_hallucination'] += 1
            continue

        if intent not in list(ops):
            hallucinations['dictionary_hallucination'] += 1
            i += 1
            continue

        print(f'{bcolors.OKGREEN}Number of triples: ' + str(n_t) + f'{bcolors.ENDC}')
        print(f"{bcolors.FAIL}====================================TURN {i}===================================={bcolors.ENDC}")
        print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Answer: {answer}{bcolors.ENDC}")

        answer = dict_keys_to_snake(answer)
        answer = replace_ids(answer, intent, 0)

        valid_slots = set(ops[intent]['postconditions']['slots']) | set(ops[intent]['preconditions']['slots'])
        for slot in answer:
            if slot not in valid_slots:
                hallucinations['dictionary_hallucination'] += 1

        expected_slots = set(ops[intent]['postconditions']['slots'])
        for slot in expected_slots:
            if slot not in answer or answer[slot] in [None, 'None']:
                hallucinations['missing_slot'] += 1


        preconditions_slots = ops[intent]['preconditions']['slots']
        for slot in preconditions_slots:
            val = answer.get(slot)
            if val not in [None, 'None']:
                if not redis.sismember(f"entities:{slot}", val):
                    hallucinations['false_precondition'] += 1

        for a in answer:
            if answer[a] != 'None' and answer[a] is not None:
                answer[a] = str(answer[a]).replace("'", "")
                answer[a] = str(answer[a]).replace("\"", "")

        for t in ops[intent]["postconditions"]["triples"]:

            if t[0] not in answer or answer[t[0]] == 'None' or answer[t[0]] is None:
                continue
            if t[1] != 'type':
                if t[2] not in answer or answer[t[2]] == 'None' or answer[t[2]] is None:
                    continue
            if not(t[0] in ops[intent]['postconditions']['slots'] or t[0] in ops[intent]['preconditions']['slots']):
                continue

            n_t += 1
            if n_t >= triples:
                return
            
        update_world_state(answer, intent)
        
        i += 1
            
    return