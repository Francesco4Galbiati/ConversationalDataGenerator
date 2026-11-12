"""Make CDG runs survive transient Ollama server errors, and optionally lower the GPU load.
Imported by main.py right after conf. It wraps conf.dialogue_client.chat, the single client every dialogue
module calls, so no dialogue file needs to change.

Configuration through environment variables (conf.py is left untouched):
  CDG_RETRY_WAITS  seconds to wait before each retry, comma separated   (default "20,40,80,160,300")
  CDG_NUM_CTX      context window to request, e.g. 16384 (default: unset = server default, as in the paper)
  CDG_THINK        gpt-oss reasoning level: low | medium | high      (default: unset = model default, medium)
  CDG_TIMEOUT      seconds before a request with no answer fails and is retried (default 600, set in conf.py)

Only server-side failures are retried (HTTP 5xx, connection errors, timeouts). Client errors (4xx, e.g. a wrong
key) are raised immediately. The time spent waiting is recorded in stats and reported by main.py; note it is
INCLUDED in the querent/witness times measured by the dialogue code."""
import os
import time
import httpx
from ollama import ResponseError
import conf

stats = {'retries': 0, 'retry_wait': 0.0, 'errors': []}

WAITS = [float(x) for x in os.environ.get('CDG_RETRY_WAITS', '20,40,80,160,300').split(',') if x.strip()]
NUM_CTX = int(os.environ['CDG_NUM_CTX']) if os.environ.get('CDG_NUM_CTX') else None
THINK = os.environ.get('CDG_THINK') or None
if THINK is not None and THINK not in ('low', 'medium', 'high'):
    raise SystemExit(f"CDG_THINK must be low, medium or high (got {THINK!r}); other values are silently ignored by Ollama")

_raw_chat = conf.dialogue_client.chat


def _chat_with_retry(*args, **kwargs):
    if NUM_CTX:
        kwargs['options'] = {**(kwargs.get('options') or {}), 'num_ctx': NUM_CTX}
    if THINK:
        kwargs['think'] = THINK
    for attempt in range(len(WAITS) + 1):
        try:
            return _raw_chat(*args, **kwargs)
        except (ResponseError, httpx.HTTPError) as e:
            status = getattr(e, 'status_code', None)
            if isinstance(e, ResponseError) and status is not None and status < 500:
                raise                                   # client error: retrying will not help
            if attempt == len(WAITS):
                raise                                   # out of retries
            wait = WAITS[attempt]
            stats['retries'] += 1
            stats['retry_wait'] += wait
            stats['errors'].append(str(e)[:200])
            print(f"{conf.bcolors.FAIL}[server error, retry {attempt + 1}/{len(WAITS)} in {wait:.0f}s] "
                  f"{str(e)[:150]}{conf.bcolors.ENDC}", flush=True)
            time.sleep(wait)


conf.dialogue_client.chat = _chat_with_retry

settings = []
if NUM_CTX: settings.append(f'num_ctx={NUM_CTX}')
if THINK: settings.append(f'think={THINK}')
settings.append(f"timeout={os.getenv('CDG_TIMEOUT', '600')}s")
print(f"robustness: retries with waits {WAITS}" + (f"; {', '.join(settings)}" if settings else ''), flush=True)
