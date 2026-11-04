"""Check the Doppler model against Asad Ullah et al. (Table 5, 144 Hz/s) and the ns-3 packet run."""
import csv
import glob
import os
import sys
from collections import defaultdict

table_path, passes_path, pass_dir = sys.argv[1:4]
TOLERANCE_DEG = 5.0
MIN_ELEVATION = 1.0

# Table 5: (fc MHz, B kHz, SF) -> (lower bound, upper bound) of the working elevation range.
# None means the combination never works. "<= 90" and "< x" have no stated lower limit.
FULL = (None, 90)
TABLE5 = {
    (436.7, 31.25, 7): (40, 90), (436.7, 31.25, 10): (40, 43), (436.7, 31.25, 12): None,
    (436.7, 62.5, 7): FULL, (436.7, 62.5, 10): FULL, (436.7, 62.5, 12): (None, 25),
    (436.7, 125, 7): FULL, (436.7, 125, 10): FULL, (436.7, 125, 12): (None, 50),
    (868, 31.25, 7): (67, 90), (868, 31.25, 10): None, (868, 31.25, 12): None,
    (868, 62.5, 7): (40, 90), (868, 62.5, 10): (40, 64), (868, 62.5, 12): None,
    (868, 125, 7): FULL, (868, 125, 10): FULL, (868, 125, 12): (None, 35),
    (2100, 31.25, 7): (77, 90), (2100, 31.25, 10): None, (2100, 31.25, 12): None,
    (2100, 62.5, 7): (70, 90), (2100, 62.5, 10): None, (2100, 62.5, 12): None,
    (2100, 125, 7): (50, 90), (2100, 125, 10): (50, 90), (2100, 125, 12): None,
}


def fields(line):
    return dict(kv.split("=") for kv in line.split()[1:])


feasible_ok = bounds_ok = 0
peak_rate = None
with open(table_path) as f:
    for line in f:
        tag = line.split()[0]
        d = fields(line)
        if tag == "PEAK":
            print("CHECK2", line.strip())
            if float(d["fc"]) == 436.7:
                peak_rate = float(d["maxRateHzPerS"])
        elif tag == "LORAWAN":
            print("LORAWAN_RANGE", line.strip())
        elif tag == "TABLE":
            key = (float(d["fc"]), float(d["b"]), int(d["sf"]))
            expected = TABLE5[key]
            works = float(d["survive"]) > 0
            match_f = works == (expected is not None)
            feasible_ok += match_f
            match_b = match_f
            if works and expected is not None:
                lo = expected[0] if expected[0] is not None else MIN_ELEVATION
                match_b = (abs(float(d["lo"]) - lo) <= TOLERANCE_DEG
                           and abs(float(d["hi"]) - expected[1]) <= TOLERANCE_DEG)
            bounds_ok += match_b
            print(f"CHECK1 fc={key[0]} b={key[1]} sf={key[2]} toa={d['toa']} sim_lo={d['lo']} "
                  f"sim_hi={d['hi']} paper={expected} feasible_match={match_f} bounds_match={match_b}")

sent = agree = received = 0
with open(passes_path) as f:
    for line in f:
        d = fields(line)
        sent += int(d["sent"])
        agree += int(d["agree"])
        received += int(d["received"])

per_sf = defaultdict(lambda: [0, 0, 1e9, -1e9, 1e9, -1e9])
for path in glob.glob(os.path.join(pass_dir, "*.csv")):
    with open(path) as f:
        for r in csv.DictReader(f):
            s = per_sf[int(r["sf"])]
            s[0] += 1
            e = float(r["elevation"])
            if r["received"] == "1":
                s[1] += 1
                s[2], s[3] = min(s[2], e), max(s[3], e)
            else:
                s[4], s[5] = min(s[4], e), max(s[5], e)
for sf, s in sorted(per_sf.items()):
    print(f"PACKET sf={sf} sent={s[0]} received={s[1]} pdr={s[1] / s[0]:.3f} "
          f"received_elev=[{s[2]:.1f},{s[3]:.1f}] lost_elev=[{s[4]:.1f},{s[5]:.1f}]")

n = len(TABLE5)
agreement = agree / sent
rate_err = abs(peak_rate - 144) / 144
print(f"VALIDATION feasible={feasible_ok}/{n} bounds_within_{TOLERANCE_DEG:.0f}deg={bounds_ok}/{n} "
      f"peak_rate={peak_rate:.1f} rate_err={rate_err:.3f} packets={sent} received={received} "
      f"agreement={agreement:.4f} "
      f"pass={feasible_ok == n and bounds_ok == n and rate_err <= 0.05 and agreement >= 0.99}")
