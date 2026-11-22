"""Paper figures 2-4 from the CSVs written by extract_data.py.

Run from the repository root:
    uv run --no-project --with matplotlib --with numpy python figs/make_figures.py
"""
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orx_figstyle import (BASELINE, COLUMN, MUTED, PALETTE, WIDE, figure, figure_grid,  # noqa: E402
                          mean_ci, panel_labels, save, use_style)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
use_style()


def read(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


# Fig. 2: oracle vs link-only, verdict counts per collision model.
rows = read("headroom.csv")
models = [("C1", "C1 Goursaud"), ("C2", "C2 Croce"), ("C3", "C3 Croce + locking")]
kinds = [("better", "Clearly better", PALETTE["blue"]), ("overlap", "Intervals overlap", MUTED),
         ("worse", "Clearly worse", PALETTE["red"])]
fig, ax = figure(width=COLUMN, ratio=0.5)
for i, (m, _) in enumerate(models):
    left = 0
    for kind, label, color in kinds:
        n = sum(r["collision"] == m and r["verdict"] == kind for r in rows)
        ax.barh(i, n, left=left, color=color, edgecolor="white", linewidth=0.8, height=0.62,
                label=label if i == 0 else None)
        x = left + n / 2 if n >= 6 else left + n + 0.8
        ax.text(x, i, str(n), ha="center" if n >= 6 else "left", va="center", fontsize=6.5,
                color="white" if kind == "better" else "black")
        left += n
ax.set_yticks(range(3), [lab for _, lab in models])
ax.invert_yaxis()
ax.set_xlim(0, 64)
ax.set_xticks([0, 16, 32, 48, 64])
ax.set_xlabel("Scenarios (of 64 per collision model)")
ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.42), ncol=3, frameon=False, fontsize=6.5,
          handlelength=1.0, columnspacing=1.0)
save(fig, os.path.join(HERE, "fig_headroom"))

# Fig. 3: (a, b) Doppler-lost packets per 100 devices per pass at low latitude, 5 dBi; (c) learning
# over passes. Filled markers: paired 95% interval of controller minus link-only below zero.
dop = read("doppler_lost.csv")
order = [(c, n) for c in ("C1", "C2", "C3") for n in ("100", "500", "2000", "5000")]
fig, axes = figure_grid(1, 3, width=WIDE, ratio=0.36, gridspec_kw={"width_ratios": [1, 1, 1.15]})
for ax, reading in zip(axes[:2], ("R1", "R2")):
    for y, (c, n) in enumerate(order):
        hit = [r for r in dop if r["reading"] == reading and r["collision"] == c and r["devices"] == n]
        if not hit:
            continue
        r = hit[0]
        lo, ct = 100 * float(r["link_only"]), 100 * float(r["controller"])
        ax.plot([ct, lo], [y, y], color=BASELINE, linewidth=0.8, zorder=1)
        ax.errorbar(lo, y, xerr=100 * float(r["link_only_ci"]), fmt="o", color=PALETTE["blue"], ms=3.6,
                    elinewidth=0.7, capsize=0, zorder=2)
        clear = r["lower"] == "True"
        ax.errorbar(ct, y, xerr=100 * float(r["controller_ci"]), fmt="o", ms=3.6, elinewidth=0.7, capsize=0,
                    color=PALETTE["orange"], mfc=PALETTE["orange"] if clear else "white", zorder=3)
    for b in (3.5, 7.5):
        ax.axhline(b, color=MUTED, linewidth=0.5)
    ax.set_ylim(len(order) - 0.5, -0.5)
    ax.set_xlim(0, 11)
    ax.set_xlabel(f"Doppler-lost per 100 devices per pass, {reading}")
for ax in axes[:2]:
    ax.set_yticks(range(len(order)), [f"{c}, N={n}" for c, n in order], fontsize=5.5)
    ax.set_ylabel("Collision model, devices")
axes[0].plot([], [], "o", color=PALETTE["blue"], ms=3.6, label="Link-only")
axes[0].plot([], [], "o", color=PALETTE["orange"], ms=3.6, label="Controller, significantly lower")
axes[0].plot([], [], "o", color=PALETTE["orange"], mfc="white", ms=3.6, label="Controller, not significant")
fig.legend(loc="outside lower center", ncol=3, frameon=False, fontsize=6.5)

traj = read("trajectory.csv")
passes = sorted({int(r["pass"]) for r in traj})
seeds = sorted({int(r["seed"]) for r in traj})
# C3, R1, 500 devices: Doppler-lost packets per 100 devices.
grid = [[100 * float(next(x for x in traj if int(x["seed"]) == s and int(x["pass"]) == p)["doppler_lost"]) / 500
         for p in passes] for s in seeds]
means, lows, highs = mean_ci(grid)
ax = axes[2]
ax.axvspan(-0.5, 2.5, color=MUTED, alpha=0.45, linewidth=0)
ax.fill_between(passes, lows, highs, color=PALETTE["orange"], alpha=0.22, linewidth=0)
ax.plot(passes, means, color=PALETTE["orange"], marker="o", ms=2.6, linewidth=1.1)
top = max(highs) * 1.18
ax.text(1.0, top * 0.93, "learning", ha="center", va="bottom", fontsize=6, color="black")
ax.text(10.5, top * 0.93, "cut-off 50° in all seeds", ha="center", va="bottom", fontsize=6, color="black")
ax.set_xlim(-0.5, 19.5)
ax.set_ylim(0, top)
ax.set_xticks([0, 5, 10, 15, 19])
ax.set_xlabel("Pass")
ax.set_ylabel("Doppler-lost per 100 devices")
panel_labels(axes)
save(fig, os.path.join(HERE, "fig_doppler"))

# Fig. 4: delivery per device per pass, C3, low latitude, 5 dBi.
lim = [r for r in read("delivery_limit.csv") if r["collision"] == "C3"]
series = [("link_only", "Link-only", PALETTE["blue"]), ("beacon", "Controller, beacons", PALETTE["orange"]),
          ("instant", "Controller, instant", PALETTE["purple"]), ("best_fixed", "Best fixed cut-off", PALETTE["cyan"]),
          ("oracle", "Oracle", PALETTE["green"])]
ns = ["100", "500", "2000", "5000"]
fig, axes = figure_grid(1, 2, width=WIDE, ratio=0.3, sharey=True)
width = 0.16
for ax, reading in zip(axes, ("R1", "R2")):
    for j, (key, label, color) in enumerate(series):
        vals = [float(next(r for r in lim if r["reading"] == reading and r["devices"] == n)[key]) for n in ns]
        errs = [float(next(r for r in lim if r["reading"] == reading and r["devices"] == n)[key + "_ci"])
                for n in ns]
        x = np.arange(len(ns)) + (j - 2) * width
        ax.bar(x, vals, width=width * 0.92, color=color, label=label if reading == "R1" else None)
        ax.errorbar(x, vals, yerr=errs, fmt="none", ecolor="black", elinewidth=0.6, capsize=1.2)
    ax.set_xticks(range(len(ns)), [f"N={n}" for n in ns])
    ax.set_xlabel(f"Devices, {reading}")
axes[0].set_ylabel("Packets / device / pass")
axes[0].set_ylim(0, 0.12)
fig.legend(loc="outside lower center", ncol=5, frameon=False, fontsize=6.5)
panel_labels(axes)
save(fig, os.path.join(HERE, "fig_limit"))
