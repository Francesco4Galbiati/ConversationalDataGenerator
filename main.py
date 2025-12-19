import asyncio
import conf
import nest_asyncio
from conf import dialogue_timestamps, parsing_timestamps
from one_to_one.one_to_one_gen import __launch__ as oto_launch
from one_to_many.one_to_many_gen import __launch__ as otm_launch
from many_to_one.many_to_one_gen import __launch__ as mto_launch
from many_to_many.many_to_many_gen import __launch__ as mtm_launch
import time

nest_asyncio.apply()
start = time.time()
asyncio.run(oto_launch(500))
end = time.time()
timestamps = {'total': {'start': start, 'end': end}, 'dialogue': dialogue_timestamps, 'parsing': parsing_timestamps}
print(f"\nNumber of plan hallucinations: {conf.hallucinations}")