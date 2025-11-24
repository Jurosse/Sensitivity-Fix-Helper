import math
import argparse
import hashlib
from pathlib import Path
from collections import defaultdict

from slider.replay import Replay
from slider.game_mode import GameMode
from slider.beatmap import Beatmap

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_BEATMAPS_PATH = BASE_DIR / "beatmaps"
DEFAULT_REPLAYS_PATH = BASE_DIR / "replays"


def load_replay(path: Path) -> Replay:
    r = Replay.from_path(path, retrieve_beatmap=False)
    if r.mode != GameMode.standard:
        raise ValueError(f"{path} is not an osu!standard replay.")
    return r


def build_beatmap_index(beatmaps_dir: Path) -> dict[str, Path]:
    """
    Build a dict: md5 -> .osu path for all .osu files in beatmaps_dir.
    """
    index: dict[str, Path] = {}
    for osu_path in beatmaps_dir.glob("*.osu"):
        data = osu_path.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        index[md5] = osu_path
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
    errors = []

    for ho in beatmap.hit_objects:
        has_pos = hasattr(ho, "position")
        has_time = hasattr(ho, "time")
        has_end = hasattr(ho, "end_time")

        if not (has_pos and has_time):
            continue
        if has_end:
            continue

        circle_time_ms = ho.time.total_seconds() * 1000.0
        action = find_nearest_action_with_click(replay.actions, circle_time_ms)

        if action is None:
            continue

        cx, cy = ho.position.x, ho.position.y
        px, py = action.position.x, action.position.y

        dx = px - cx
        dy = py - cy
        dist = math.hypot(dx, dy)

        errors.append(dist)

    return errors


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


def ask_sensitivity_for_replay(osr_path: Path):
    while True:
        raw = input(
            f"Enter in-game sensitivity for '{osr_path.name}' (empty to skip): "
        ).strip()

        if raw == "":
            print(f"[INFO] Replay {osr_path.name} skipped (no sensitivity provided).")
            return None

        try:
            sens = float(raw)
            return sens
        except ValueError:
            print("[WARN] Invalid sensitivity. Please enter a number (e.g. 0.8, 1.0).")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze osu! replays to compare accuracy for different mouse sensitivities."
    )
    parser.add_argument(
        "--beatmaps",
        type=Path,
        default=DEFAULT_BEATMAPS_PATH,
        help=(
            "Folder containing the .osu beatmaps used for the replays. "
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
        print("[ERROR] No .osu files found in beatmaps folder.")
        return

    print(f"[INFO] Indexed {len(beatmap_index)} beatmaps by MD5.")

    sens_errors = defaultdict(list)
    beatmap_cache: dict[Path, Beatmap] = {}

    for osr in sorted(replays_path.glob("*.osr")):
        sens = ask_sensitivity_for_replay(osr)
        if sens is None:
            continue

        try:
            replay = load_replay(osr)
        except Exception as e:
            print(f"[WARN] Error loading {osr.name}: {e}")
            continue

        md5 = replay.beatmap_md5
        osu_path = beatmap_index.get(md5)
        if osu_path is None:
            print(
                f"[WARN] No .osu matching MD5 {md5} for replay {osr.name}. "
                f"Make sure the correct .osu is in {beatmaps_path}."
            )
            continue

        if osu_path not in beatmap_cache:
            try:
                beatmap_cache[osu_path] = Beatmap.from_path(osu_path)
            except Exception as e:
                print(f"[WARN] Error parsing beatmap {osu_path.name}: {e}")
                continue

        beatmap = beatmap_cache[osu_path]
        errors = analyze_replay(replay, beatmap)
        if not errors:
            print(f"[WARN] No errors computed for {osr.name}")
            continue

        sens_errors[sens].extend(errors)
        print(
            f"[INFO] {osr.name}: {len(errors)} hitcircles analyzed for sens {sens}."
        )

    if not sens_errors:
        print("No data analyzed. No sensitivity provided or no valid replays/beatmaps.")
        return

    print("\n=== Sensitivity summary (error in osu! pixels) ===")
    if dpi is not None:
        print("Sens\tHitcircles\tMean\tMedian\tP95\t\teDPI")
    else:
        print("Sens\tHitcircles\tMean\tMedian\tP95")

    best_sens = None
    best_score = None

    for sens in sorted(sens_errors.keys()):
        stats = summarize_errors(sens_errors[sens])
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

    if best_sens is not None:
        if dpi is not None:
            best_edpi = dpi * best_sens
            print(
                f"\n>>> 'Optimal' sensitivity (lowest P95 error): {best_sens:.3f} "
                f"(eDPI ≈ {best_edpi:.1f})"
            )
        else:
            print(
                f"\n>>> 'Optimal' sensitivity (lowest P95 error): {best_sens:.3f}"
            )
    else:
        print("\nCould not determine an 'optimal' sensitivity (not enough data).")


if __name__ == "__main__":
    main()
