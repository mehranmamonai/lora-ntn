"""Test the Stage 3 control loop against the criteria fixed before the run.
Usage: summarize.py runs.txt cases_dir"""
import json
import os
import statistics as st
import sys
from collections import defaultdict

OBSERVABLE = {"pass", "received", "received_by_sf", "devices_heard", "rssi_mean_dbm", "rssi_min_dbm"}
COMPARED = ["sent", "received", "airtimeS", "visible", "skipped", "blocked", "usable", "rejDoppler",
            "underSens", "interfered", "noDemod", "thinned", "served", "jain"] + \
           [f"{k}Sf{sf}" for sf in range(7, 13) for k in ("sent", "recv")]


def fields(line):
    return dict(kv.split("=", 1) for kv in line.split()[1:])


runs = [fields(line) for line in open(sys.argv[1]) if line.startswith("RUN ")]
cases_dir = sys.argv[2]


def log_lines(case_id, prefix):
    with open(os.path.join(cases_dir, case_id + ".log")) as f:
        return [line[len(prefix):].strip() for line in f if line.startswith(prefix)]


# S1: the constant controller reproduces runs without the loop exactly.
pairs = defaultdict(dict)
for r in runs:
    if r["part"] == "s1":
        pairs[r["case"].rsplit("-", 1)[0]][r["kind"]] = r
mismatches = []
for key, pair in sorted(pairs.items()):
    if set(pair) != {"none", "const"}:
        mismatches.append((key, "missing run"))
        continue
    diff = [f for f in COMPARED if pair["none"][f] != pair["const"][f]]
    if diff:
        mismatches.append((key, diff))
for key, why in mismatches[:10]:
    print(f"S1 mismatch {key} {why}")
s1 = len(pairs) == 256 and not mismatches
print(f"S1 cases={len(pairs)} expected=256 mismatches={len(mismatches)} holds={s1}")

# S2: observations sum to the run totals and hold only observable fields.
s2_bad = []
rssi_low = []
for r in runs:
    if r["kind"] == "none":
        continue
    obs = [json.loads(x) for x in log_lines(r["case"], "OBS ")]
    if len(obs) != int(r["passes"]):
        s2_bad.append((r["case"], f"{len(obs)} observations for {r['passes']} passes"))
        continue
    if any(set(o) != OBSERVABLE for o in obs):
        s2_bad.append((r["case"], "fields"))
    if sum(o["received"] for o in obs) != int(r["received"]):
        s2_bad.append((r["case"], "received total"))
    for sf in range(7, 13):
        if sum(o["received_by_sf"][str(sf)] for o in obs) != int(r[f"recvSf{sf}"]):
            s2_bad.append((r["case"], f"SF{sf} total"))
    if sum(o["devices_heard"] > o["received"] for o in obs):
        s2_bad.append((r["case"], "devices above packets"))
    rssi_low += [o["rssi_min_dbm"] for o in obs if o["rssi_min_dbm"] is not None]
for case, why in s2_bad[:10]:
    print(f"S2 problem {case} {why}")
s2 = not s2_bad
checked = sum(r["kind"] != "none" for r in runs)
print(f"S2 runs_checked={checked} problems={len(s2_bad)} holds={s2}")
if rssi_low:
    print(f"S2 report: lowest received signal {min(rssi_low):.1f} dBm, median of per-pass minima "
          f"{st.median(rssi_low):.1f} dBm")


# S3: scripted controllers act from pass 10 and not before.
def per_pass(kind):
    run = next(r for r in runs if r["part"] == "s3" and r["kind"] == kind)
    return {int(f["pass"]): f for f in map(lambda x: dict(kv.split("=") for kv in x.split()),
                                             log_lines(run["case"], "PASS "))}


base, p0, m3 = per_pass("const"), per_pass("p0"), per_pass("m3")
same_before_p0 = all(base[k]["sent"] == p0[k]["sent"] and base[k]["received"] == p0[k]["received"] for k in range(10))
zero_after = all(int(p0[k]["sent"]) == 0 for k in range(10, 20))
same_before_m3 = all(base[k]["sent"] == m3[k]["sent"] and base[k]["received"] == m3[k]["received"] for k in range(10))
changes_after = any(base[k]["sent"] != m3[k]["sent"] for k in range(10, 20))
settings_ok = all(float(p0[k]["p"]) == (0.0 if k >= 10 else 1.0) for k in range(20)) and \
    all(float(m3[k]["marginDb"]) == (3.0 if k >= 10 else 0.0) for k in range(20))
s3 = same_before_p0 and zero_after and same_before_m3 and changes_after and settings_ok
print(f"S3 p0_same_before={same_before_p0} p0_zero_from_10={zero_after} m3_same_before={same_before_m3} "
      f"m3_changes_from_10={changes_after} settings_logged={settings_ok} holds={s3}")
print("S3 report sent per pass, const vs p0 vs m3: " + " ".join(
    f"{k}:{base[k]['sent']}/{p0[k]['sent']}/{m3[k]['sent']}" for k in range(8, 13)))

# S4: run-time overhead of the loop.
ratios = defaultdict(list)
for key, pair in pairs.items():
    if set(pair) == {"none", "const"}:
        ratios[int(pair["none"]["n"])].append(float(pair["const"]["wallS"]) / float(pair["none"]["wallS"]))
for n in sorted(ratios):
    print(f"S4 n={n} wall_ratio_median={st.median(ratios[n]):.3f} max={max(ratios[n]):.3f}")
print(f"GATE S1={s1} S2={s2} S3={s3} passes={s1 and s2 and s3}")
