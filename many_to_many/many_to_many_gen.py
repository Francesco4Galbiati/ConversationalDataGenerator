import conf
import asyncio

from conf import bcolors, ops, hallucinations, instructions, instructions_loop, parallelization
from agents import parser_agent
from functions import dict_keys_to_snake, replace_ids
from many_to_many.dialogue import gen_dialogue_turn


async def __launch__(triples):

    n_t = 0
    k = 0
    next_dialogue = None
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

        if parallelization:
            if n_t == 0:
                parser_agent.run(user_prompt="")
                dialogue_turn = gen_dialogue_turn(instructions[inst]['inst'], clear=clear)
                next_dialogue = asyncio.create_task(
                    asyncio.to_thread(
                        gen_dialogue_turn,
                        False,
                        3,
                        instructions[inst]["inst"],
                        None,
                    )
                )
            else:
                dialogue_turn = await next_dialogue
                next_dialogue = asyncio.create_task(
                    asyncio.to_thread(
                        gen_dialogue_turn,
                        False,
                        3,
                        instructions[inst]["inst"],
                        None,
                    )
                )
        else:
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

            for a in answer:
                if answer[a] != "None" and answer[a] is not None:
                    answer[a] = str(answer[a]).replace("'", "")
                    answer[a] = str(answer[a]).replace("\"", "")

            for v in answer.values():
                if v == "None" or v is None:
                    hallucinations["missing_slot"] += 1

            for t in ops[intent]["postconditions"]["triples"]:

                if t[0] not in answer or answer[t[0]] == "None" or answer[t[0]] is None:
                    continue

                if t[1] != "type":
                    if t[2] not in answer or answer[t[2]] == "None" or answer[t[2]] is None:
                        continue

                if not (t[0] in ops[intent]["postconditions"]["slots"] or t[0] in ops[intent]["preconditions"]["slots"]):
                    print(f"{bcolors.FAIL}No slot named {t[0]} in the {intent} intent!")
                    hallucinations["dictionary_hallucination"] += 1
                    continue

                n_t += 1
                if n_t >= triples:
                    return

        i += 1

    return
