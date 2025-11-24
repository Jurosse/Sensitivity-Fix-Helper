# Sensitivity-Fix-Helper

Analyze osu! replays to compare your **mouse sensitivities** and find which one gives you the most precise aim.

This tool is inspired by projects like *Area-Fixer-Helper*, but focuses on **mouse players**: it measures how far your cursor is from the center of each hitcircle at the moment you click.

---

## Features

- Reads `.osr` replays and automatically finds the matching `.osu` beatmap (using the [`slider`](https://pypi.org/project/slider/) library).
- Computes the distance (error) between:
  - the center of each hitcircle  
  - your cursor position when you hit it
- Aggregates stats **per sensitivity**:
  - number of hitcircles
  - mean error
  - median error
  - 95th percentile (P95) error
- Optionally uses your **DPI** to compute **eDPI**.
- Prints which sensitivity looks "optimal" (lowest P95 error).

---

## How it works (short version)

1. Each replay file is associated with a **mouse sensitivity** via its filename.  
   Example:  
   - `MyMap [Hard] - sens0.7.osr` → sens = `0.7`  
   - `MyMap [Hard] - sens1.0.osr` → sens = `1.0`

2. For each hitcircle in the beatmap:
   - The script finds the closest click action (mouse1/mouse2/key1/key2).
   - It measures the distance between the circle center and your cursor in osu! pixels.

3. For each sensitivity, it aggregates all errors and prints statistics.  
   The **lowest P95** is used as a simple “best sensitivity” criterion.

---

## Requirements

- Python 3.9+ (recommended)
- osu! installed (to have a `Songs` folder with beatmaps)
- Python packages:
  - `slider`

Install dependencies:

```bash
pip install -r requirements.txt
