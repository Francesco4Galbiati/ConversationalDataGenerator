"""Use Claude (Anthropic API) as querent and/or witness model, without touching the dialogue code.

The dialogue files call `conf.dialogue_client.chat(model=..., messages=..., format='json', options=...)`
and read `response['message']['content']`, as with Ollama. Importing this module (main.py does it
right after conf) wraps conf.dialogue_client in a ModelRouter that keeps that interface: models whose
name starts with "claude" go to the Anthropic API, every other model to the original Ollama client.
So the two can be mixed, e.g. a Claude querent with a gpt-oss witness.

Setup:   export ANTHROPIC_API_KEY=sk-ant-...
Run:     python main.py --contract OntoPFAS_contract.yaml --conversation 1 --target 300 \
             --querent_model claude-sonnet-5-5 --witness_model claude-sonnet-5-5

Conversion from the Ollama message list:
- 'system' messages are joined, in order, into Anthropic's `system` parameter.
- 'user'/'assistant' messages keep their order; consecutive ones with the same role are merged,
  because the API wants alternating roles starting with 'user'.
- format='json' becomes an explicit instruction to answer with one JSON object
  (the code already runs json_repair on every answer).
- Only `temperature` is passed from `options` (Ollama's top_p/top_k are dropped); if a model
  rejects it, the call is repeated without it.
Token usage is summed in conf.dialogue_client.usage; main.py writes it to output.txt.
"""
import os
import time

import conf

JSON_RULE = "Answer with exactly one JSON object and nothing else: no prose, no markdown fences."


def to_anthropic(messages, json_mode):
    system = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
    if json_mode:
        system.append(JSON_RULE)
    turns = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant") or not m.get("content"):
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + m["content"]
        else:
            turns.append({"role": role, "content": m["content"]})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "Follow the system instructions."})
    return "\n\n".join(system), turns


class ModelRouter:
    def __init__(self, ollama_client, anthropic_client=None, max_tokens=2048):
        self.ollama = ollama_client
        self._claude = anthropic_client
        self.max_tokens = max_tokens
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    @property
    def claude(self):
        if self._claude is None:
            import anthropic
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise SystemExit("Set ANTHROPIC_API_KEY to use a claude-* model")
            # the SDK itself retries rate limits, 5xx and connection errors with backoff
            self._claude = anthropic.Anthropic(max_retries=8, timeout=300)
        return self._claude

    def chat(self, *args, model=None, messages=None, format=None, options=None, **kwargs):
        if not str(model or "").startswith("claude"):
            return self.ollama.chat(*args, model=model, messages=messages, format=format,
                                    options=options, **kwargs)
        system, turns = to_anthropic(messages or [], format == "json")
        params = {"model": model, "max_tokens": self.max_tokens, "messages": turns}
        if system:
            params["system"] = system
        if options and "temperature" in options:
            params["temperature"] = options["temperature"]
        try:
            response = self.claude.messages.create(**params)
        except Exception as error:          # a model that does not accept temperature
            if "temperature" not in str(error) or "temperature" not in params:
                raise
            params.pop("temperature")
            response = self.claude.messages.create(**params)
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        self.usage["calls"] += 1
        self.usage["input_tokens"] += getattr(response.usage, "input_tokens", 0) or 0
        self.usage["output_tokens"] += getattr(response.usage, "output_tokens", 0) or 0
        return {"message": {"role": "assistant", "content": text}, "model": model,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "done": True}


if not isinstance(conf.dialogue_client, ModelRouter):
    conf.dialogue_client = ModelRouter(conf.dialogue_client)
