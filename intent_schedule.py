"""Code-driven intent selection (--intent_selection schedule).

By default the querent model chooses each turn's intent, and in practice it rotates through all
intents almost evenly, ignoring the contract's cardinalities. In schedule mode the generator
chooses the intent and the querent only has to phrase the question for it.

Each turn, the eligible intents are the ones whose precondition slots all have at least one
entity in Redis (the same condition the querent prompt states). Among them, the intent is
picked by smooth weighted round-robin on the cardinalities: every eligible intent gains its
weight, the one with the highest total is chosen and pays back the sum of eligible weights.
Over many turns each intent's share converges to its weight / sum of weights, picks are
spread out instead of coming in bursts, an intent that is not yet eligible does not pile up
credit (so it cannot flood the dialogue once it becomes eligible), and the choice is
deterministic, so a run can be reproduced.

With --unique_slots (e.g. country_name), an intent that creates a value of such a slot stops being
eligible once every option of its closed list is used, so it never has to repeat or invent one.
"""
from collections import Counter

import conf
from conf import ops, redis, types

_credit = {intent: 0 for intent in ops}
picked = Counter()


def weight(intent):
    value = ops[intent]["preconditions"].get("cardinality") or 0
    return value if value > 0 else 0


def remaining_options(slot, suffix=""):
    """For a --unique_slots slot with a closed list of options: the options not used yet, else None."""
    if slot not in conf.unique_slots:
        return None
    for i in ops:
        kind = ops[i]["postconditions"]["slots"].get(slot)
        if kind and types.get(kind, {}).get("options"):
            used = {str(v).strip().lower() for v in redis.smembers(f"entities:{slot}{suffix}")}
            return [o for o in types[kind]["options"] if str(o).strip().lower() not in used]
    return None


def exhausted(intent, suffix=""):
    """True when the intent would have to repeat a value of a unique slot: every option is already used."""
    return any(remaining_options(slot, suffix) == [] for slot in ops[intent]["postconditions"]["slots"])


def eligible(suffix=""):
    return [i for i in ops
            if weight(i) > 0 and not exhausted(i, suffix)
            and all(redis.scard(f"entities:{slot}{suffix}") > 0 for slot in ops[i]["preconditions"]["slots"])]


def next_intent(suffix=""):
    candidates = eligible(suffix)
    if not candidates:
        raise RuntimeError("No intent is eligible: some intent with no preconditions needs cardinality > 0")
    for intent in candidates:
        _credit[intent] += weight(intent)
    chosen = max(candidates, key=lambda i: (_credit[i], weight(i)))   # ties: heavier intent, then contract order
    _credit[chosen] -= sum(weight(i) for i in candidates)
    picked[chosen] += 1
    return chosen
