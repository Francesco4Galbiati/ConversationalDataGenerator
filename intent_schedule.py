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
"""
from collections import Counter

from conf import ops, redis

_credit = {intent: 0 for intent in ops}
picked = Counter()


def weight(intent):
    value = ops[intent]["preconditions"].get("cardinality") or 0
    return value if value > 0 else 0


def eligible(suffix=""):
    return [i for i in ops
            if weight(i) > 0 and all(redis.scard(f"entities:{slot}{suffix}") > 0
                                     for slot in ops[i]["preconditions"]["slots"])]


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
