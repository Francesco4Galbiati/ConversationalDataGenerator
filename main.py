import json
import conf
import time
import asyncio
import nest_asyncio
from conf import dialogue_timestamps, parsing_timestamps, hallucinations, conversation_type, target_triples, num_of_witnesses
from parameters import ConversationType
from one_to_one.one_to_one_gen import __launch__ as oto_launch
from one_to_many.one_to_many_gen import __launch__ as otm_launch
from many_to_one.many_to_one_gen import __launch__ as mto_launch
from many_to_many.many_to_many_gen import __launch__ as mtm_launch

nest_asyncio.apply()
start = time.time()
if conversation_type == ConversationType.ONE_TO_ONE:
    asyncio.run(oto_launch(target_triples))
if conversation_type == ConversationType.MANY_TO_ONE:
    asyncio.run(mto_launch(target_triples))
if conversation_type == ConversationType.ONE_TO_MANY:
    asyncio.run(otm_launch(target_triples))
if conversation_type == ConversationType.MANY_TO_MANY:
    asyncio.run(mtm_launch(target_triples))
end = time.time()

print(f"\nNumber of plan hallucinations: {hallucinations}")
print(f"Total time: {end - start}")
print(f"Total Querent time: {conf.querent_time}")
if conversation_type == ConversationType.ONE_TO_ONE or conversation_type == ConversationType.MANY_TO_ONE:
    print(f"Total Witness time: {conf.witness_time}")
if conversation_type == ConversationType.MANY_TO_ONE or conversation_type == ConversationType.MANY_TO_MANY:
    for n in range(num_of_witnesses):
        print(f"Total Witness {n} time: {conf.witness_times[n]}")