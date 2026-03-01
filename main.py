import json
import conf
import time
import asyncio
import nest_asyncio
from conf import dialogue_timestamps, parsing_timestamps, hallucinations, conversation_type, target_triples
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
timestamps = {'total': {'start': start, 'end': end}, 'dialogue': dialogue_timestamps, 'parsing': parsing_timestamps}

events = []
print(f"\nNumber of plan hallucinations: {conf.hallucinations}")
print(f"Total time: {end - start}")

d_id = 0
p_id = 0
for t in (timestamps['dialogue'] + timestamps['parsing']):

    if t in timestamps['dialogue']:
        events.append({
            'lane': 'dialogue',
            'id': d_id,
            'start': t['start'] - timestamps['total']['start'],
            'end': t['end'] - timestamps['total']['start']
        })
        d_id += 1

    if t in timestamps['parsing']:
        events.append({
            'lane': 'parsing',
            'id': p_id,
            'start': t['start'] - timestamps['total']['start'],
            'end': t['end'] - timestamps['total']['start']
        })
        p_id += 1

events.append({
    'lane': 'total',
    'id': 0,
    'start': start - start,
    'end': end - start
})

events.append({
    'lane': 'hallucinations',
    'id': 0,
    'data': hallucinations
})

json.dump(events, conf.output_file, indent=2)