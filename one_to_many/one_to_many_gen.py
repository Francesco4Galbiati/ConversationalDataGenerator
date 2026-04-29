import conf
from conf import bcolors, ops, hallucinations, parallelization

from functions import dict_keys_to_snake, replace_ids
from one_to_many.dialogue import gen_dialogue_turn


async def __launch__(triples):

    n_t = 0
    i = 1

    while n_t < triples:

        # The one-to-many generator currently exposes only the synchronous turn
        # API, so the loop keeps the same outer structure but always fetches one
        # broadcast turn at a time.
        if parallelization:
            dialogue_turn = gen_dialogue_turn()
        else:
            dialogue_turn = gen_dialogue_turn()

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

            for a in answer:
                if answer[a] != "None" and answer[a] is not None:
                    answer[a] = str(answer[a]).replace("'", "")
                    answer[a] = str(answer[a]).replace("\"", "")

            for v in answer.values():
                if v == "None" or v is None:
                    hallucinations["missing_slot"] += 1

            for triple_def in ops[intent]["postconditions"]["triples"]:

                if triple_def[0] not in answer or answer[triple_def[0]] == "None" or answer[triple_def[0]] is None:
                    continue

                if triple_def[1] != "type":
                    if triple_def[2] not in answer or answer[triple_def[2]] == "None" or answer[triple_def[2]] is None:
                        continue

                if not (
                    triple_def[0] in ops[intent]["postconditions"]["slots"]
                    or triple_def[0] in ops[intent]["preconditions"]["slots"]
                ):
                    print(f"{bcolors.FAIL}No slot named {triple_def[0]} in the {intent} intent!")
                    hallucinations["dictionary_hallucination"] += 1
                    continue

                n_t += 1
                if n_t >= triples:
                    return

        i += 1

    return
