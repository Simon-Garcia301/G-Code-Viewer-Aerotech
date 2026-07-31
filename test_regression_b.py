#!/usr/bin/env python3
"""
test_regression_b.py
━━━━━━━━━━━━━━━━━━━━
Phase B regression test script — compares old-style vs new hardened
analysis settings on clean and flagged image sets.

Usage:
    python test_regression_b.py [--clean_dir PATH] [--flagged_dir PATH]

Exit code 1 if any clean run shows delta_mean_pct > 5%.
"""

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path


def find_images(directory: str) -> list:
    """Return sorted list of image paths from a directory (recursive)."""
    if not directory or not os.path.isdir(directory):
        return []
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    paths = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                paths.append(os.path.join(root, f))
    return sorted(paths)


def run_analysis(images: list, scale: float, use_adaptive: bool,
                 width_outlier_factor: float, threshold: int = 200) -> dict:
    """Run LineWidthAnalyzer with given settings and return results dict."""
    from line_width_engine import LineWidthAnalyzer

    with tempfile.TemporaryDirectory() as tmpdir:
        analyzer = LineWidthAnalyzer(
            images=images,
            scale=scale,
            threshold=threshold,
            orientation="vertical",
            smooth_window=0,
            overlap_px=0.0,
            unit="um",
            outdir=tmpdir,
            use_adaptive_threshold=use_adaptive,
            width_outlier_factor=width_outlier_factor,
        )
        results = analyzer.analyze()
    return results


def build_comparison_table(clean_dir: str, flagged_dir: str) -> list:
    """Run old and new analysis on both image sets; return list of row dicts."""
    rows = []

    scale = 0.8075  # 4x objective default

    for label, directory in [("clean", clean_dir), ("flagged", flagged_dir)]:
        images = find_images(directory)
        if not images:
            print(f"[SKIP] No images found in {label} directory: {directory}")
            continue

        print(f"\n{'='*60}")
        print(f"Processing {label.upper()} set: {len(images)} image(s) from {directory}")
        print(f"{'='*60}")

        for img_path in images:
            fname = os.path.basename(img_path)
            print(f"  → {fname} ...", end=" ", flush=True)

            try:
                # Old-style: manual threshold, no outlier filtering
                old = run_analysis(
                    [img_path], scale,
                    use_adaptive=False,
                    width_outlier_factor=999.0,  # effectively disabled
                    threshold=200,
                )
                old_mean = old["stats"]["mean"]
                old_cv = old["stats"]["cv_pct"]
                old_robust_cv = old["stats"]["robust_cv_pct"]
                old_threshold = old.get("thresholds_used", {}).get(img_path, 200)

                # New hardened: adaptive threshold, default outlier filtering
                new = run_analysis(
                    [img_path], scale,
                    use_adaptive=True,
                    width_outlier_factor=4.0,
                )
                new_mean = new["stats"]["mean"]
                new_cv = new["stats"]["cv_pct"]
                new_robust_cv = new["stats"]["robust_cv_pct"]
                new_threshold = new.get("thresholds_used", {}).get(img_path, 200)

                # Count rejected rows
                row_logs = new.get("row_logs", {}).get(img_path, [])
                rows_rejected = sum(1 for r in row_logs if r.get("status") == "rejected")

                # Stitch flag
                stitch_flag = new.get("stitch_quality", {}).get("stitch_flag", False)

                # Delta
                if old_mean and abs(old_mean) > 1e-9:
                    delta_mean_pct = abs(new_mean - old_mean) / abs(old_mean) * 100.0
                else:
                    delta_mean_pct = 0.0

                rows.append({
                    "image":              fname,
                    "set":                label,
                    "old_mean":           round(old_mean, 4),
                    "new_mean":           round(new_mean, 4),
                    "old_cv":             round(old_cv, 4),
                    "new_cv":             round(new_cv, 4),
                    "old_robust_cv":      round(old_robust_cv, 4),
                    "new_robust_cv":      round(new_robust_cv, 4),
                    "old_threshold":      old_threshold,
                    "new_threshold":      new_threshold,
                    "rows_rejected_new":  rows_rejected,
                    "stitch_flag_new":    stitch_flag,
                    "delta_mean_pct":     round(delta_mean_pct, 4),
                })

                print(f"Δmean={delta_mean_pct:.2f}%")

            except Exception as exc:
                print(f"ERROR: {exc}")
                rows.append({
                    "image":              fname,
                    "set":                label,
                    "old_mean":           "ERROR",
                    "new_mean":           "ERROR",
                    "old_cv":             "",
                    "new_cv":             "",
                    "old_robust_cv":      "",
                    "new_robust_cv":      "",
                    "old_threshold":      "",
                    "new_threshold":      "",
                    "rows_rejected_new":  "",
                    "stitch_flag_new":    "",
                    "delta_mean_pct":     "",
                })

    return rows


def write_report(rows: list, output_path: str = "regression_report.csv") -> None:
    """Write comparison table to CSV."""
    fieldnames = [
        "image", "set",
        "old_mean", "new_mean",
        "old_cv", "new_cv",
        "old_robust_cv", "new_robust_cv",
        "old_threshold", "new_threshold",
        "rows_rejected_new", "stitch_flag_new",
        "delta_mean_pct",
    ]
    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\nReport written to: {os.path.abspath(output_path)}")


def print_summary(rows: list) -> bool:
    """Print console summary; returns True if all clean runs pass."""
    clean_rows = [r for r in rows if r.get("set") == "clean"]
    flagged_rows = [r for r in rows if r.get("set") == "flagged"]

    all_pass = True

    # ── Clean runs ──────────────────────────────────────────────────
    if clean_rows:
        deltas = [
            r["delta_mean_pct"] for r in clean_rows
            if isinstance(r.get("delta_mean_pct"), (int, float))
        ]
        if deltas:
            mean_delta = sum(deltas) / len(deltas)
            max_delta = max(deltas)
            pass_fail = "PASS" if max_delta < 5.0 else "FAIL"
            if max_delta >= 5.0:
                all_pass = False
            print(
                f"CLEAN RUNS:   {len(clean_rows)} images — "
                f"mean delta: {mean_delta:.2f}% — "
                f"max delta: {max_delta:.2f}% [{pass_fail} if max < 5%]"
            )
        else:
            print(f"CLEAN RUNS:   {len(clean_rows)} images — no valid delta data")
    else:
        print("CLEAN RUNS:   0 images")

    # ── Flagged runs ────────────────────────────────────────────────
    if flagged_rows:
        deltas = [
            r["delta_mean_pct"] for r in flagged_rows
            if isinstance(r.get("delta_mean_pct"), (int, float))
        ]
        if deltas:
            mean_delta = sum(deltas) / len(deltas)
            max_delta = max(deltas)
            print(
                f"FLAGGED RUNS: {len(flagged_rows)} images — "
                f"mean delta: {mean_delta:.2f}% — "
                f"max delta: {max_delta:.2f}% [EXPECT meaningful change]"
            )
        else:
            print(f"FLAGGED RUNS: {len(flagged_rows)} images — no valid delta data")
    else:
        print("FLAGGED RUNS: 0 images")

    return all_pass


def main():
    """Parse CLI args, run regression comparison, write report, exit with status."""
    parser = argparse.ArgumentParser(
        description="Phase B regression test — compare old vs new analysis settings",
    )
    parser.add_argument(
        "--clean_dir",
        default="./test_images/clean",
        help="Path to directory with known-good (clean) images",
    )
    parser.add_argument(
        "--flagged_dir",
        default="./test_images/flagged",
        help="Path to directory with known-bad (flagged) images",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Phase B Regression Test")
    print("=" * 60)
    print(f"Clean dir:   {args.clean_dir}")
    print(f"Flagged dir: {args.flagged_dir}")

    rows = build_comparison_table(args.clean_dir, args.flagged_dir)

    if not rows:
        print("\nNo images processed. Check that --clean_dir and/or --flagged_dir contain images.")
        sys.exit(0)

    write_report(rows)
    all_pass = print_summary(rows)

    if not all_pass:
        print("\n⚠ REGRESSION DETECTED: One or more clean runs exceeded 5% delta.")
        sys.exit(1)
    else:
        print("\n✓ All clean runs within tolerance.")
        sys.exit(0)


if __name__ == "__main__":
    main()