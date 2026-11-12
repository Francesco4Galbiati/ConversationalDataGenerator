import conf
import claude_client   # routes claude-* models to the Anthropic API
import robustness
import time
import asyncio
import nest_asyncio
from conf import hallucinations, conversation_type, target_triples, num_of_witnesses
from parameters import ConversationType
from one_to_one.one_to_one_gen import __launch__ as oto_launch
from one_to_many.one_to_many_gen import __launch__ as otm_launch
from many_to_one.many_to_one_gen import __launch__ as mto_launch
from many_to_many.many_to_many_gen import __launch__ as mtm_launch

nest_asyncio.apply()
start = time.time()
status = 'completed'
try:
    if conversation_type == ConversationType.ONE_TO_ONE:
        asyncio.run(oto_launch(target_triples))
    if conversation_type == ConversationType.MANY_TO_ONE:
        asyncio.run(mto_launch(target_triples))
    if conversation_type == ConversationType.ONE_TO_MANY:
        asyncio.run(otm_launch(target_triples))
    if conversation_type == ConversationType.MANY_TO_MANY:
        asyncio.run(mtm_launch(target_triples))
except BaseException as e:          # also KeyboardInterrupt (Ctrl+C)
    status = f'interrupted: {type(e).__name__}: {str(e)[:300]}'
    raise
finally:
    end = time.time()
    conf.output_file.write(f"Number of plan hallucinations: {hallucinations}\n")
    conf.output_file.write(f"Total time: {end - start}\n")
    conf.output_file.write(f"Total Querent time: {conf.querent_time}\n")
    if conversation_type == ConversationType.ONE_TO_ONE or conversation_type == ConversationType.MANY_TO_ONE:
        conf.output_file.write(f"Total Witness time: {conf.witness_times[0]}\n")
    if conversation_type == ConversationType.MANY_TO_ONE or conversation_type == ConversationType.MANY_TO_MANY:
        for n in range(num_of_witnesses):
            conf.output_file.write(f"Total Witness {n} time: {conf.witness_times[n]}\n")
    conf.output_file.write(f"Status: {status}\n")
    conf.output_file.write(f"Server retries: {robustness.stats['retries']} "
                           f"(waiting {robustness.stats['retry_wait']:.0f}s, included in the times above)\n")
    usage = getattr(conf.dialogue_client, 'usage', None)
    if usage and usage['calls']:
        conf.output_file.write(f"Claude API: {usage['calls']} calls, {usage['input_tokens']} input tokens, "
                               f"{usage['output_tokens']} output tokens\n")
    conf.output_file.write(f"Models: querent={conf.querent_llm} witness={conf.witness_llm}\n")
    conf.output_file.write(f"Contract: {conf.args.contract}  Intent selection: {conf.intent_selection}"
                           + (f" (querent overridden {conf.schedule_overrides} times)" if conf.intent_selection == "schedule" else "") + "\n")
    conf.output_file.flush()
