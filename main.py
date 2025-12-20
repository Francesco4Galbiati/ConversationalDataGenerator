#import asyncio
import json
import conf
#import nest_asyncio
#from conf import dialogue_timestamps, parsing_timestamps
#from one_to_one.one_to_one_gen import __launch__ as oto_launch
#from one_to_many.one_to_many_gen import __launch__ as otm_launch
#from many_to_one.many_to_one_gen import __launch__ as mto_launch
#from many_to_many.many_to_many_gen import __launch__ as mtm_launch
#import time

'''
nest_asyncio.apply()
start = time.time()
asyncio.run(oto_launch(500))
end = time.time()
timestamps = {'total': {'start': start, 'end': end}, 'dialogue': dialogue_timestamps, 'parsing': parsing_timestamps}
'''
timestamps = {'total': {'start': 0, 'end': 250000},
              'dialogue': [{"start": 0.0, "end": 5.0}, {"start": 5.1, "end": 10.2}],
              'parsing': [{"start": 5.0, "end": 9.8}, {"start": 10.3, "end": 15.0}]}
events = []
# print(f"\nNumber of plan hallucinations: {conf.hallucinations}")

# Plots the timestamps
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

json.dump(events, conf.output_file, indent=2)