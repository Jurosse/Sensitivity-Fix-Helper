# Sensitivity-Fix-Helper

Tool for osu! mouse players to **analyze aim accuracy** from replays and:
- compare different mouse sensitivities, or
- with **one single sensitivity**, see if you tend to **overshoot / undershoot** jumps
  and get a suggestion on how to adjust your sens.

It works by measuring, for each hitcircle:
- the distance between the circle center and your cursor at hit time,
- and, for jumps, how much you overshoot/undershoot **along the direction of movement**.

---

## Features

- Reads `.osr` replays and finds the correct beatmap via the replay’s MD5.
- Supports beatmaps as **`.osu`** or **`.osz`** in a simple `beatmaps/` folder (no `slider.db` or osu! `Songs` folder needed).
- For each sensitivity, computes:
  - number of hitcircles,
  - mean error,
  - median error,
  - 95th percentile (P95) error.
- Computes **directional bias** on jumps:
  - positive = overshoot (sens a bit too high),
  - negative = undershoot (sens a bit too low),
  - expressed as % of jump distance.
- If you only use **one sensitivity** across all replays:
  - tells you if it’s already well calibrated,
  - or suggests a new sensitivity based on your average overshoot/undershoot.
- Optional **DPI input** to display eDPI.

---

## Requirements

- Python 3.9+
- Python package:
  - [`slider`](https://pypi.org/project/slider/)

Install:

```bash
pip install slider

or
```bash
pip install -r requirements.txt