from conf import bcolors, ops, hallucinations, instructions, instructions_loop, redis, querent_llm
from functions import dict_keys_to_snake, replace_ids, update_world_state

if querent_llm == 'gpt-oss:120b':
    from many_to_many.dialogue_gpt import gen_dialogue_turn
elif querent_llm == 'llama3.3:70b':
    from many_to_many.dialogue_llama import gen_dialogue_turn
else:
    exit("Model not supported at the moment")


async def __launch__(triples):

    n_t = 0
    k = 0
    inst = next(instructions_loop)
    i = 1
    j = 1

    while n_t < triples:
        if k % instructions[inst]["cardinality"] == 0:
            k = 0
            if n_t != 0:
                inst = next(instructions_loop)
                j += 1

        clear = False
        if j == len(instructions) + 1 and k == 0:
            j = 1
            clear = True

        k += 1

        dialogue_turn = gen_dialogue_turn(instructions[inst]['inst'], clear=clear)
            

        t = dialogue_turn
        if "Intent" in t and "Q" in t and "branches" in t:
            intent = t["Intent"]
            question = t["Q"]
            branches = t["branches"]
        else:
            hallucinations["dictionary_hallucination"] += 1
            continue

        if intent not in list(ops):
            hallucinations["dictionary_hallucination"] += 1
            i += 1
            continue

        print(f'{bcolors.OKGREEN}Number of triples: ' + str(n_t) + f'{bcolors.ENDC}')
        print(f"{bcolors.FAIL}====================================TURN {i}===================================={bcolors.ENDC}")
        print(f"{bcolors.WARNING}Intent: {intent}{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Question: {question}{bcolors.ENDC}")

        for branch in branches:

            if "answerer_id" in branch and "A" in branch:
                answerer_id = branch["answerer_id"]
                answer = branch["A"]
            else:
                hallucinations["dictionary_hallucination"] += 1
                continue

            print(f"{bcolors.WARNING}Answerer {answerer_id}: {answer}{bcolors.ENDC}")

            answer = dict_keys_to_snake(answer)
            answer = replace_ids(answer, intent, answerer_id)

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
                    if not redis.sismember(f"entities:{slot}:idx{answerer_id}", str(val)):
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
    
            update_world_state(answer, intent, ':idx' + str(answerer_id))
        i += 1

    return
