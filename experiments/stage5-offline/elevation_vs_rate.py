"""Offline geometry check for Stage 5 (no simulation). 560 km circular orbit, 868.1 MHz, devices spread
across the footprint at 20 deg minimum elevation (Asad Ullah 2024 Eqs. 1, 3, 5-9 as in sim/leo_doppler.h).
For each second a device sees the satellite above 20 deg: elevation, and mean Doppler rate over one SF12
packet (32 bytes, 1.810 s on air by the SX1276 formula). Compares the best elevation cut-off with a rate
threshold at the SF12 limits 93 Hz/s (Colombo 2022) and 144 Hz/s (Doroshkin 2019)."""
import math, random
R, G, C, H, FC = 6371e3, 9.80665, 299792458.0, 560e3, 868.1e6
W = math.sqrt(G / R) * (1 + H / R) ** -1.5; V = math.sqrt(G * R / (1 + H / R)); RS = R + H
TOA = 1.810
def sat(t): return (RS * math.cos(W * t), RS * math.sin(W * t), 0.0)
def vel(t): return (-V * math.sin(W * t), V * math.cos(W * t), 0.0)
def dop(t, d):
    s, v = sat(t), vel(t); to = [d[i] - s[i] for i in range(3)]; n = math.sqrt(sum(x * x for x in to))
    return FC / (1 + V / C * (-sum(v[i] * to[i] for i in range(3)) / (V * n))) - FC
def elev(t, d):
    s = sat(t); l = [s[i] - d[i] for i in range(3)]; n = math.sqrt(sum(x * x for x in l))
    return math.degrees(math.asin(sum(l[i] * d[i] for i in range(3)) / (n * R)))
e = math.radians(20); ratio = RS / R
dmax = R * (math.sqrt(ratio**2 - math.cos(e)**2) - math.sin(e)); gmax = R * math.asin(dmax * math.cos(e) / RS)
random.seed(1); pts = []
for _ in range(400):
    off = random.uniform(-gmax, gmax) / R
    d = (R * math.cos(off), 0.0, R * math.sin(off))
    for k in range(-400, 401):
        el = elev(k, d)
        if el >= 20:
            pts.append((el, abs(dop(k + TOA, d) - dop(k, d)) / TOA))
print(f"samples={len(pts)}  peak rate={max(r for _, r in pts):.0f} Hz/s")
for limit in (93, 144):
    best = min(((th, sum((el > th) != (r > limit) for el, r in pts)) for th in range(20, 91)), key=lambda x: x[1])
    print(f"limit {limit} Hz/s: {100*sum(r > limit for _, r in pts)/len(pts):.1f}% of SF12 opportunities exceed it; "
          f"best elevation cut-off {best[0]} deg misclassifies {100*best[1]/len(pts):.1f}%")
    for lo in (40, 50, 60, 70):
        band = sorted(r for el, r in pts if lo <= el < lo + 10)
        print(f"   elevation {lo}-{lo+10} deg: rate min {band[0]:.0f}, median {band[len(band)//2]:.0f}, max {band[-1]:.0f} Hz/s, "
              f"share above limit {100*sum(r > limit for r in band)/len(band):.0f}%")
