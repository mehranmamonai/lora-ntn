"""Builds the Stage 5 Q-table from training runs (seeds 16-20), whose controller chose a random arm each pass.

For each run and each pass k < last: context = context after the OBS of pass k (cumulative), action = the
threshold applied in pass k+1 (PASS line), reward = packets received in pass k+1 (OBS line).
Q[context][arm] = mean reward and count. Usage: train_bandit.py cases_dir out.json"""
import json
import os
import re
import sys
from collections import defaultdict

from bandit_context import arm_key, context_key

cases_dir, out = sys.argv[1], sys.argv[2]
q = defaultdict(lambda: defaultdict(list))
runs = 0
for name in sorted(os.listdir(cases_dir)):
    if not name.startswith("train-"):
        continue
    obs, limits = [], {}
    with open(os.path.join(cases_dir, name)) as f:
        for line in f:
            if line.startswith("OBS "):
                obs.append(json.loads(line[4:]))
            elif line.startswith("PASS "):
                fields = dict(kv.split("=") for kv in line.split()[1:])
                limits[int(fields["pass"])] = float(fields["rateLimit"])
    runs += 1
    cumulative = [0] * 6
    for k in range(len(obs) - 1):
        cumulative = [a + b for a, b in zip(cumulative, obs[k]["sf12_by_rate"])]
        key = context_key(cumulative, obs[k]["devices_heard_total"])
        limit = limits.get(k + 1, 1e9)
        arm = None if limit >= 1e9 else limit
        q[key][arm_key(arm)].append(obs[k + 1]["received"])
table = {c: {a: [sum(v) / len(v), len(v)] for a, v in arms.items()} for c, arms in q.items()}
with open(out, "w") as f:
    json.dump(table, f, indent=1, sort_keys=True)
print(f"TRAIN runs={runs} contexts={len(table)} samples={sum(n for arms in table.values() for _, n in arms.values())}")
for c in sorted(table):
    best = max(((m, a) for a, (m, n) in table[c].items() if n >= 10), default=(None, "none"))
    print(f"TRAIN context={c} best={best[1]} " + " ".join(f"{a}:{m:.1f}/{n}" for a, (m, n) in sorted(table[c].items())))
