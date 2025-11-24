import math
import argparse
import hashlib
import zipfile
import re
from pathlib import Path
from collections import defaultdict

from slider.replay import Replay
from slider.game_mode import GameMode
from slider.beatmap import Beatmap

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_BEATMAPS_PATH = BASE_DIR / "beatmaps"
DEFAULT_REPLAYS_PATH = BASE_DIR / "replays"

MIN_JUMP_DIST = 40.0      # px, ignore very small movements for directional bias
ADJUST_FACTOR = 0.7       # how strongly we follow the bias to suggest a new sens


def load_replay(path: Path) -> Replay:
    r = Replay.from_path(path, retrieve_beatmap=False)
    if r.mode != GameMode.standard:
        raise ValueError(f"{path} is not an osu!standard replay.")
    return r


def build_beatmap_index(beatmaps_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    cache_dir = beatmaps_dir / ".extracted_osu"
    cache_dir.mkdir(exist_ok=True)

    # Direct .osu files
    for osu_path in beatmaps_dir.glob("*.osu"):
        try:
            data = osu_path.read_bytes()
        except Exception as e:
            print(f"[WARN] Could not read {osu_path}: {e}")
            continue

        md5 = hashlib.md5(data).hexdigest()
        if md5 not in index:
            index[md5] = osu_path

    # .osz archives
    for osz_path in beatmaps_dir.glob("*.osz"):
        try:
            with zipfile.ZipFile(osz_path, "r") as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".osu"):
                        continue

                    try:
                        data = zf.read(name)
                    except Exception as e:
                        print(f"[WARN] Could not read {name} in {osz_path.name}: {e}")
                        continue

                    md5 = hashlib.md5(data).hexdigest()
                    if md5 in index:
                        continue

                    cache_path = cache_dir / f"{md5}.osu"
                    if not cache_path.exists():
                        try:
                            cache_path.write_bytes(data)
                        except Exception as e:
                            print(f"[WARN] Could not write cache file {cache_path}: {e}")
                            continue

                    index[md5] = cache_path
        except Exception as e:
            print(f"[WARN] Could not open osz {osz_path.name}: {e}")

    return index


def find_nearest_action_with_click(actions, target_time, max_delta_ms=80):
    best_action = None
    best_delta = None

    for act in actions:
        t_ms = act.offset.total_seconds() * 1000.0
        delta = abs(t_ms - target_time)
        if delta > max_delta_ms:
            continue

        pressed = act.mouse1 or act.mouse2 or act.key1 or act.key2
        if not pressed:
            continue

        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_action = act

    return best_action


def analyze_replay(replay: Replay, beatmap: Beatmap):
    """
    returns:
      errors: radial errors (distance to center)
      parallel_norms: signed errors along movement, normalised by jump length
    """
    errors = []
    parallel_norms = []
    last_pos = None

    for ho in beatmap.hit_objects():
        has_pos = hasattr(ho, "position")
        has_time = hasattr(ho, "time")
        has_end = hasattr(ho, "end_time")

        if not (has_pos and has_time):
            continue
        if has_end:
            continue

        cx, cy = ho.position.x, ho.position.y
        circle_time_ms = ho.time.total_seconds() * 1000.0
        action = find_nearest_action_with_click(replay.actions, circle_time_ms)

        if action is None:
            last_pos = ho.position
            continue

        px, py = action.position.x, action.position.y
        dx = px - cx
        dy = py - cy
        dist = math.hypot(dx, dy)
        errors.append(dist)

        # directional bias for larger jumps
        if last_pos is not None:
            mvx = cx - last_pos.x
            mvy = cy - last_pos.y
            move_dist = math.hypot(mvx, mvy)

            if move_dist > MIN_JUMP_DIST:
                vx = mvx / move_dist
                vy = mvy / move_dist

                ex = px - cx
                ey = py - cy
                parallel = ex * vx + ey * vy  # >0 overshoot, <0 undershoot

                parallel_norms.append(parallel / move_dist)

        last_pos = ho.position

    return errors, parallel_norms


def summarize_errors(errors):
    if not errors:
        return {
            "count": 0,
            "mean": float("nan"),
            "median": float("nan"),
            "p95": float("nan"),
        }

    errs = sorted(errors)
    n = len(errs)

    def percentile(p):
        if n == 1:
            return errs[0]
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return errs[int(k)]
        return errs[f] + (errs[c] - errs[f]) * (k - f)

    mean = sum(errs) / n
    median = percentile(0.5)
    p95 = percentile(0.95)

    return {
        "count": n,
        "mean": mean,
        "median": median,
        "p95": p95,
    }


def get_sensitivity_for_replay(osr_path: Path, default_sens: float = 1.0) -> float:
    # try from filename: ...sens0.8.osr
    m = re.search(r"sens([0-9]+(?:\.[0-9]+)?)", osr_path.stem)
    if m:
        sens = float(m.group(1))
        print(f"[INFO] Using sensitivity {sens} from filename '{osr_path.name}'.")
        return sens

    # otherwise ask user, default if empty
    while True:
        raw = input(
            f"Enter in-game sensitivity for '{osr_path.name}' "
            f"(empty to use default {default_sens}): "
        ).strip()

        if raw == "":
            print(
                f"[INFO] No sensitivity provided for {osr_path.name}, "
                f"using default {default_sens}."
            )
            return default_sens

        try:
            sens = float(raw)
            return sens
        except ValueError:
            print("[WARN] Invalid sensitivity. Please enter a number (e.g. 0.8, 1.0).")


def ask_global_sensitivity() -> float | None:
    """
    Ask once if all replays share the same sens.
    If user enters a value, it's used for every replay.
    If user presses Enter, per-replay sensitivities are used.
    """
    while True:
        raw = input(
            "If ALL your replays use the same in-game sensitivity, enter it here "
            "(e.g. 0.6). Otherwise, press Enter to set sensitivity per replay: "
        ).strip()

        if raw == "":
            print("[INFO] No global sensitivity provided, will set sensitivity per replay.")
            return None

        try:
            sens = float(raw)
            print(f"[INFO] Using global sensitivity {sens} for all replays.")
            return sens
        except ValueError:
            print("[WARN] Invalid sensitivity. Please enter a number (e.g. 0.8, 1.0).")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze osu! replays to compare and adjust mouse sensitivities."
    )
    parser.add_argument(
        "--beatmaps",
        type=Path,
        default=DEFAULT_BEATMAPS_PATH,
        help=(
            "Folder containing the .osu/.osz beatmaps used for the replays. "
            f"Default: {DEFAULT_BEATMAPS_PATH}"
        ),
    )
    parser.add_argument(
        "--replays",
        type=Path,
        default=DEFAULT_REPLAYS_PATH,
        help=(
            "Folder containing the .osr replays to analyze. "
            f"Default: {DEFAULT_REPLAYS_PATH}"
        ),
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="Mouse DPI (same for all replays). Used to compute eDPI.",
    )

    args = parser.parse_args()

    beatmaps_path = args.beatmaps
    replays_path = args.replays
    dpi = args.dpi

    print(f"[INFO] Beatmaps folder : {beatmaps_path}")
    print(f"[INFO] Replays folder  : {replays_path}")
    if dpi is not None:
        print(f"[INFO] Mouse DPI       : {dpi}")
    else:
        print("[INFO] Mouse DPI       : not provided (eDPI will not be shown)")

    if not beatmaps_path.exists():
        print(f"[ERROR] Beatmaps folder does not exist: {beatmaps_path}")
        return
    if not replays_path.exists():
        print(f"[ERROR] Replays folder does not exist: {replays_path}")
        return

    beatmap_index = build_beatmap_index(beatmaps_path)
    if not beatmap_index:
        print("[ERROR] No .osu or .osz beatmaps found in beatmaps folder.")
        return

    print(f"[INFO] Indexed {len(beatmap_index)} beatmaps by MD5.")

    # ask once if user uses the same sens for all replays
    global_sens = ask_global_sensitivity()

    sens_radial_errors = defaultdict(list)
    sens_parallel_norms = defaultdict(list)
    beatmap_cache: dict[Path, Beatmap] = {}

    for osr in sorted(replays_path.glob("*.osr")):
        if global_sens is not None:
            sens = global_sens
        else:
            sens = get_sensitivity_for_replay(osr)

        try:
            replay = load_replay(osr)
        except Exception as e:
            print(f"[WARN] Error loading {osr.name}: {e}")
            continue

        md5 = replay.beatmap_md5
        osu_path = beatmap_index.get(md5)
        if osu_path is None:
            print(
                f"[WARN] No beatmap matching MD5 {md5} for replay {osr.name}. "
                f"Make sure the correct .osu or .osz is in {beatmaps_path}."
            )
            continue

        if osu_path not in beatmap_cache:
            try:
                beatmap_cache[osu_path] = Beatmap.from_path(osu_path)
            except Exception as e:
                print(f"[WARN] Error parsing beatmap {osu_path.name}: {e}")
                continue

        beatmap = beatmap_cache[osu_path]
        errors, parallels = analyze_replay(replay, beatmap)
        if not errors:
            print(f"[WARN] No errors computed for {osr.name}")
            continue

        sens_radial_errors[sens].extend(errors)
        sens_parallel_norms[sens].extend(parallels)
        print(
            f"[INFO] {osr.name}: {len(errors)} hitcircles analyzed for sens {sens}."
        )

    if not sens_radial_errors:
        print("No data analyzed. No valid replays/beatmaps or sensitivity provided.")
        return

    print("\n=== Sensitivity summary (error in osu! pixels) ===")
    if dpi is not None:
        print("Sens\tHitcircles\tMean\tMedian\tP95\t\teDPI")
    else:
        print("Sens\tHitcircles\tMean\tMedian\tP95")

    best_sens = None
    best_score = None
    per_sens_bias: dict[float, float | None] = {}

    for sens in sorted(sens_radial_errors.keys()):
        stats = summarize_errors(sens_radial_errors[sens])

        parallels = sens_parallel_norms.get(sens, [])
        if parallels:
            mean_bias = sum(parallels) / len(parallels)  # >0 overshoot, <0 undershoot
        else:
            mean_bias = None
        per_sens_bias[sens] = mean_bias

        if dpi is not None:
            edpi = dpi * sens
            print(
                f"{sens:.3f}\t{stats['count']}\t\t"
                f"{stats['mean']:.2f}\t{stats['median']:.2f}\t{stats['p95']:.2f}\t\t"
                f"{edpi:.1f}"
            )
        else:
            print(
                f"{sens:.3f}\t{stats['count']}\t\t"
                f"{stats['mean']:.2f}\t{stats['median']:.2f}\t{stats['p95']:.2f}"
            )

        if not math.isnan(stats["p95"]):
            if best_score is None or stats["p95"] < best_score:
                best_score = stats["p95"]
                best_sens = sens

    print("\n=== Directional bias along movement (jumps) ===")
    print("Sens\tMean bias (% of jump)\tInterpretation")
    for sens in sorted(per_sens_bias.keys()):
        bias = per_sens_bias[sens]
        if bias is None:
            print(f"{sens:.3f}\tN/A\t\t\t(no valid jumps)")
            continue

        bias_pct = bias * 100.0
        if abs(bias_pct) < 1.5:
            interp = "roughly balanced"
        elif bias_pct > 0:
            interp = "overshoot (sens a bit high)"
        else:
            interp = "undershoot (sens a bit low)"

        print(f"{sens:.3f}\t{bias_pct:+6.2f}%\t\t{interp}")

    if len(sens_radial_errors) == 1:
        sens = next(iter(sens_radial_errors.keys()))
        bias = per_sens_bias.get(sens)

        print("\n=== Single-sensitivity suggestion ===")

        if bias is None:
            print("Not enough directional data (jumps) to suggest an adjustment.")
        else:
            bias_pct = bias * 100.0
            if abs(bias_pct) < 1.5:
                print(
                    f"Your sensitivity {sens:.3f} looks well-calibrated: "
                    f"average directional bias is only {bias_pct:+.2f}% of jump distance."
                )
            else:
                direction = "overshoot (sens too high)" if bias > 0 else "undershoot (sens too low)"
                new_sens = sens * (1.0 - bias * ADJUST_FACTOR)
                new_sens = max(sens * 0.5, min(sens * 1.5, new_sens))
                change_pct = (new_sens / sens - 1.0) * 100.0

                print(
                    f"On average you have a {direction}: {bias_pct:+.2f}% of the jump distance."
                )
                print(
                    f"As a rough suggestion, you could adjust your sens from {sens:.3f} "
                    f"to about {new_sens:.3f} ({change_pct:+.1f}% change)."
                )
                print("This is a heuristic; fine-tune around that value based on feel.")

    if best_sens is not None and len(sens_radial_errors) > 1:
        print(
            f"\n>>> 'Optimal' sensitivity (lowest P95 error across all tested): {best_sens:.3f}"
        )


if __name__ == "__main__":
    main()
