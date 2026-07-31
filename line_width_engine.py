"""
line_width_engine.py
━━━━━━━━━━━━━━━━━━━
Engine class that encapsulates all analysis logic from line width analysis.

Phase B hardened — tracking-window edge detection, adaptive Otsu thresholding,
robust CV (MAD), overlap-aware stitching, and comprehensive QA traceability.
"""

import glob
import os
import warnings


class LineWidthAnalyzer:
    """
    Measures line-width consistency from one or more overlapping
    microscope images.
    """

    def __init__(
        self,
        images:        list,
        scale:         float,
        threshold:     int   = 200,
        orientation:   str   = "vertical",
        smooth_window: int   = 0,
        overlap_px:    float = 0.0,
        unit:          str   = "um",
        outdir:        str   = "./line_width_results",
        # ── Phase B new parameters ──────────────────────────────────
        use_adaptive_threshold:     bool  = True,   # auto-compute Otsu threshold per image
        tracking_margin_multiplier: float = 2.5,    # search window = half-width × this (unitless)
        width_outlier_factor:       float = 4.0,    # rows deviating beyond this multiple of median width are excluded
    ):
        self.images        = self._expand_paths(images)
        self.scale         = float(scale)
        self.threshold     = int(threshold)
        self.orientation   = orientation
        self.smooth_window = int(smooth_window)
        self.overlap_px    = float(overlap_px)
        self.unit          = unit
        self.outdir        = outdir

        # Phase B
        self.use_adaptive_threshold     = use_adaptive_threshold
        self.tracking_margin_multiplier = tracking_margin_multiplier
        self.width_outlier_factor       = width_outlier_factor

        # Per-image threshold tracking (set during _detect_edges)
        self._last_threshold_used: int = self.threshold

    # ── Public API ──────────────────────────────────────────────────

    def analyze(self) -> dict:
        """Run the full line-width analysis pipeline and return a results dict."""
        import numpy as np

        self._validate_inputs()

        all_positions   = []
        all_widths      = []
        cumulative_off  = 0.0
        last_overlay_rgb = None
        qa_images_all   = {}          # {image_path: rgb_array}
        row_logs        = {}          # {image_path: list_of_dicts}
        thresholds_used = {}          # {image_path: int}

        for path in self.images:
            img, gray = self._load_image(path)

            idxs, e1s, e2s, row_log = self._detect_edges(gray)
            thresholds_used[path] = self._last_threshold_used
            row_logs[path] = row_log

            # ── Detection quality validation (B5.3) ─────────────────
            total_rows = gray.shape[0]
            n_accepted = len(idxs)
            MIN_VALID_ROWS = 10
            detection_pct = n_accepted / total_rows * 100.0 if total_rows > 0 else 0.0

            if n_accepted < MIN_VALID_ROWS:
                raise RuntimeError(
                    f"Image '{os.path.basename(path)}': only {n_accepted} valid rows detected "
                    f"(minimum {MIN_VALID_ROWS}). Check threshold, orientation, and image quality."
                )
            if detection_pct < 5.0:
                raise RuntimeError(
                    f"Image '{os.path.basename(path)}': only {detection_pct:.1f}% of rows detected a line. "
                    f"Threshold may be too low or line may be absent."
                )
            if detection_pct > 99.0 and self.use_adaptive_threshold is False:
                warnings.warn(
                    f"Image '{os.path.basename(path)}': {detection_pct:.1f}% rows detected — "
                    f"threshold {self.threshold} may be too high (detecting background).",
                    RuntimeWarning,
                )

            if idxs.size == 0:
                continue

            widths_px    = e2s - e1s
            positions_px = idxs.astype(np.float64) + cumulative_off

            all_positions.append(positions_px)
            all_widths.append(widths_px)

            overlay_bgr  = self._draw_qa_overlay(img, idxs, e1s, e2s)
            overlay_rgb  = overlay_bgr[:, :, ::-1].copy()
            last_overlay_rgb = overlay_rgb
            qa_images_all[path] = overlay_rgb

            frame_extent = (
                gray.shape[0] if self.orientation == "vertical"
                else gray.shape[1]
            )
            cumulative_off += frame_extent - self.overlap_px

        if not all_positions:
            raise RuntimeError(
                "No edges detected in any image. "
                "Check threshold and orientation."
            )

        positions_px, widths_px, stitch_quality = self._stitch(all_positions, all_widths)

        unit_factor  = 1.0 if self.unit == "um" else 0.001
        position_out = (positions_px - positions_px.min()) * self.scale * unit_factor
        widths_raw   = widths_px * self.scale * unit_factor
        widths_sm    = self._smooth(widths_raw)

        stats = self._compute_stats(position_out, widths_sm, len(self.images))

        profile = np.column_stack([position_out, widths_raw, widths_sm])
        fig     = self._build_figure(position_out, widths_raw, widths_sm, stats)

        return {
            "width_profile":   profile,
            "stats":           stats,
            "qa_image":        last_overlay_rgb,
            "fig_plot":        fig,
            # ── Phase B new keys ────────────────────────────────────
            "qa_images_all":   qa_images_all,
            "row_logs":        row_logs,
            "thresholds_used": thresholds_used,
            "stitch_quality":  stitch_quality,
        }

    def save_results(self, results: dict, outdir: str = None) -> list:
        """Persist all analysis outputs to disk; returns list of saved file paths."""
        import cv2
        import numpy as np

        target = outdir or self.outdir
        os.makedirs(target, exist_ok=True)

        saved = []
        ul    = self.unit

        # ── Width profile CSV ───────────────────────────────────────
        profile  = results["width_profile"]
        csv_path = os.path.join(target, "width_profile.csv")
        self._write_csv(
            csv_path,
            [f"position_{ul}", f"width_{ul}", f"width_{ul}_smoothed"],
            profile,
        )
        saved.append(csv_path)

        # ── Summary stats CSV (extended with Phase B rows) ──────────
        st       = results["stats"]
        sum_path = os.path.join(target, "summary_stats.csv")
        rows = [
            [f"mean_width_{ul}",              st["mean"]],
            [f"std_dev_{ul}",                 st["std"]],
            ["CV_percent",                    st["cv_pct"]],
            [f"min_width_{ul}",               st["min"]],
            [f"min_width_position_{ul}",      st["min_pos"]],
            [f"max_width_{ul}",               st["max"]],
            [f"max_width_position_{ul}",      st["max_pos"]],
            ["n_points",                      st["n_points"]],
            ["n_images",                      st["n_images"]],
            ["threshold_used",                self.threshold],
            # Phase B robust stats
            [f"median_width_{ul}",            st.get("median", "")],
            [f"MAD_{ul}",                     st.get("mad", "")],
            [f"robust_std_{ul}",              st.get("robust_std", "")],
            ["robust_CV_percent",             st.get("robust_cv_pct", "")],
        ]

        # ── Stitch quality rows (B4) ────────────────────────────────
        sq = results.get("stitch_quality", {})
        if sq:
            rows.extend([
                ["stitch_n_overlapping_bins",    sq.get("n_overlapping_bins", 0)],
                ["stitch_mean_disagreement_px",  sq.get("mean_disagreement_px", 0.0)],
                ["stitch_max_disagreement_px",   sq.get("max_disagreement_px", 0.0)],
                ["stitch_flag",                  sq.get("stitch_flag", False)],
            ])

        self._write_summary_csv(sum_path, rows)
        saved.append(sum_path)

        # ── QA overlay images (B5.1 — fixed exception handling) ─────
        qa_failures = []
        for n, path in enumerate(self.images):
            try:
                img, gray = self._load_image(path)
                idxs, e1s, e2s, _row_log = self._detect_edges(gray)
                if idxs.size == 0:
                    continue
                overlay_bgr = self._draw_qa_overlay(img, idxs, e1s, e2s)
                qa_path     = os.path.join(target, f"qa_overlay_{n+1:02d}.png")
                cv2.imwrite(qa_path, overlay_bgr)
                saved.append(qa_path)
            except Exception as exc:
                qa_failures.append({"image": path, "error": str(exc)})

        # ── Per-image QA row CSVs (B1.3) ────────────────────────────
        row_logs = results.get("row_logs", {})
        for path, log in row_logs.items():
            if not log:
                continue
            base = os.path.splitext(os.path.basename(path))[0]
            qa_rows_path = os.path.join(target, f"qa_rows_{base}.csv")
            self._write_csv(
                qa_rows_path,
                ["row_index", "e1_px", "e2_px", "width_px", "status", "reason"],
                log,
            )
            saved.append(qa_rows_path)

        # ── Batch QA summary (B5.2) ─────────────────────────────────
        self._write_batch_qa_summary(
            target, results, qa_failures, saved,
        )

        # ── Figure ──────────────────────────────────────────────────
        fig      = results["fig_plot"]
        fig_path = os.path.join(target, "width_vs_position.png")
        fig.savefig(fig_path, dpi=200, bbox_inches="tight")
        saved.append(fig_path)

        return saved

    # ── Input Validation (B5.3) ─────────────────────────────────────

    def _validate_inputs(self) -> None:
        """Validate inputs and raise descriptive errors before processing begins."""
        if not self.images:
            raise ValueError("No images provided.")

        for path in self.images:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Image file not found: {path}")

        if self.scale <= 0:
            raise ValueError(f"Scale must be positive, got {self.scale}")

        if not (0 < self.threshold < 256):
            raise ValueError(f"Manual threshold must be 0–255, got {self.threshold}")

    # ── Path helpers ────────────────────────────────────────────────

    @staticmethod
    def _expand_paths(patterns: list) -> list:
        """Expand glob patterns into a deduplicated, sorted list of file paths."""
        expanded = []
        for p in patterns:
            matches = sorted(glob.glob(p))
            expanded.extend(matches if matches else [p])
        seen, result = set(), []
        for p in expanded:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def _load_image(self, path: str):
        """Load an image from disk as BGR and return (bgr, gray) tuple."""
        import cv2
        img = cv2.imread(path)
        if img is None:
            raise FileNotFoundError(f"Could not read image: {path}")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img, gray

    # ── Edge Detection (B1 + B2) ────────────────────────────────────

    def _detect_edges(self, gray):
        """
        Detect left/right edges using a tracking window with EMA smoothing,
        per-row width outlier filtering, and optional adaptive Otsu threshold.
        Returns (idxs, e1s, e2s, row_log).
        """
        import cv2
        import numpy as np

        g = gray
        if self.orientation == "horizontal":
            g = g.T

        h, w   = g.shape
        g_blur = cv2.GaussianBlur(g, (9, 9), 0)

        # ── B2.1: Adaptive threshold ────────────────────────────────
        if self.use_adaptive_threshold:
            threshold_used = self._compute_otsu_threshold(g_blur)
        else:
            threshold_used = self.threshold
        self._last_threshold_used = threshold_used

        # ── B1.1: Seed rows (first ~5%, min 3) — full-row scan ─────
        n_seed = max(3, int(h * 0.05))
        seed_centers = []
        seed_halfwidths = []

        for i in range(n_seed):
            row = g_blur[i, :]
            below = row < threshold_used
            if not below.any():
                continue
            l_idx = int(np.argmax(below))
            r_idx = int(w - 1 - np.argmax(below[::-1]))
            if r_idx <= l_idx:
                continue
            seed_centers.append((l_idx + r_idx) / 2.0)
            seed_halfwidths.append((r_idx - l_idx) / 2.0)

        if not seed_centers:
            # No valid seed rows — fall back to full-scan on all rows
            tracked_center = float(w) / 2.0
            tracked_half_width = float(w) / 4.0
        else:
            tracked_center = float(np.mean(seed_centers))
            tracked_half_width = float(np.mean(seed_halfwidths))

        # ── B1.1: Track through all rows ────────────────────────────
        alpha = 0.15  # EMA smoothing factor
        all_rows = []       # row_log entries
        accepted_idxs = []
        accepted_e1s = []
        accepted_e2s = []

        for i in range(h):
            row = g_blur[i, :]

            if i < n_seed:
                # Seed rows: full-row scan (already computed above, re-scan for logging)
                below = row < threshold_used
                if not below.any():
                    all_rows.append({
                        "row_index": i, "e1_px": -1, "e2_px": -1,
                        "width_px": -1, "status": "rejected", "reason": "no_detection",
                    })
                    continue
                l_idx = int(np.argmax(below))
                r_idx = int(w - 1 - np.argmax(below[::-1]))
                if r_idx <= l_idx:
                    all_rows.append({
                        "row_index": i, "e1_px": l_idx, "e2_px": r_idx,
                        "width_px": 0, "status": "rejected", "reason": "no_detection",
                    })
                    continue
                new_center = (l_idx + r_idx) / 2.0
                new_half_width = (r_idx - l_idx) / 2.0
                # Update tracker from seed rows too
                tracked_center = alpha * new_center + (1 - alpha) * tracked_center
                tracked_half_width = alpha * new_half_width + (1 - alpha) * tracked_half_width
                all_rows.append({
                    "row_index": i, "e1_px": l_idx, "e2_px": r_idx,
                    "width_px": r_idx - l_idx, "status": "accepted", "reason": "ok",
                })
                accepted_idxs.append(i)
                accepted_e1s.append(l_idx)
                accepted_e2s.append(r_idx)
            else:
                # Subsequent rows: windowed search
                search_margin = max(tracked_half_width * self.tracking_margin_multiplier, 20.0)
                win_start = max(0, int(tracked_center - search_margin))
                win_end   = min(w, int(tracked_center + search_margin))

                if win_end <= win_start:
                    all_rows.append({
                        "row_index": i, "e1_px": -1, "e2_px": -1,
                        "width_px": -1, "status": "rejected", "reason": "below_window",
                    })
                    continue

                row_window = row[win_start:win_end]
                below = row_window < threshold_used

                if not below.any():
                    all_rows.append({
                        "row_index": i, "e1_px": -1, "e2_px": -1,
                        "width_px": -1, "status": "rejected", "reason": "no_detection",
                    })
                    continue

                l_idx = win_start + int(np.argmax(below))
                r_idx = win_start + (len(row_window) - 1 - int(np.argmax(below[::-1])))

                if r_idx <= l_idx:
                    all_rows.append({
                        "row_index": i, "e1_px": l_idx, "e2_px": r_idx,
                        "width_px": 0, "status": "rejected", "reason": "no_detection",
                    })
                    continue

                new_center = (l_idx + r_idx) / 2.0
                new_half_width = (r_idx - l_idx) / 2.0

                # EMA update
                tracked_center = alpha * new_center + (1 - alpha) * tracked_center
                tracked_half_width = alpha * new_half_width + (1 - alpha) * tracked_half_width

                all_rows.append({
                    "row_index": i, "e1_px": l_idx, "e2_px": r_idx,
                    "width_px": r_idx - l_idx, "status": "accepted", "reason": "ok",
                })
                accepted_idxs.append(i)
                accepted_e1s.append(l_idx)
                accepted_e2s.append(r_idx)

        # ── B1.2: Per-row width sanity filter ───────────────────────
        if accepted_idxs:
            accepted_widths = np.array([
                r["width_px"] for r in all_rows if r["status"] == "accepted"
            ])
            if len(accepted_widths) > 0:
                local_median_width = float(np.median(accepted_widths))

                for row_dict in all_rows:
                    if row_dict["status"] != "accepted":
                        continue
                    w = row_dict["width_px"]
                    if local_median_width > 0:
                        if w > local_median_width * self.width_outlier_factor or \
                           w < local_median_width / self.width_outlier_factor:
                            row_dict["status"] = "rejected"
                            row_dict["reason"] = "width_outlier"

                # Rebuild accepted arrays after outlier filtering
                accepted_idxs = [r["row_index"] for r in all_rows if r["status"] == "accepted"]
                accepted_e1s  = [r["e1_px"] for r in all_rows if r["status"] == "accepted"]
                accepted_e2s  = [r["e2_px"] for r in all_rows if r["status"] == "accepted"]

        return (
            np.array(accepted_idxs, dtype=np.int64),
            np.array(accepted_e1s,  dtype=np.int64),
            np.array(accepted_e2s,  dtype=np.int64),
            all_rows,
        )

    # ── Adaptive Threshold (B2.1) ───────────────────────────────────

    def _compute_otsu_threshold(self, gray_array) -> int:
        """Compute Otsu threshold; fall back to manual threshold if result is extreme."""
        import cv2
        thresh_val, _ = cv2.threshold(
            gray_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        thresh_val = int(thresh_val)

        if thresh_val < 10 or thresh_val > 245:
            warnings.warn(
                f"Otsu threshold {thresh_val} is extreme (<10 or >245). "
                f"Falling back to manual threshold {self.threshold}.",
                RuntimeWarning,
            )
            return self.threshold

        return thresh_val

    # ── QA Overlay Drawing ──────────────────────────────────────────

    def _draw_qa_overlay(self, img, idxs, e1s, e2s):
        """Draw red circles at detected left/right edge positions on a copy of the image."""
        import cv2
        overlay = img.copy()
        for i, a, b in zip(idxs, e1s, e2s):
            if self.orientation == "vertical":
                cv2.circle(overlay, (int(a), int(i)), 2, (0, 0, 255), -1)
                cv2.circle(overlay, (int(b), int(i)), 2, (0, 0, 255), -1)
            else:
                cv2.circle(overlay, (int(i), int(a)), 2, (0, 0, 255), -1)
                cv2.circle(overlay, (int(i), int(b)), 2, (0, 0, 255), -1)
        return overlay

    # ── Stitching (B4) ──────────────────────────────────────────────

    def _stitch(self, all_positions: list, all_widths: list):
        """
        Stitch overlapping frame measurements with overlap reconciliation.
        Returns (positions_px, widths_px, stitch_quality_dict).
        """
        import numpy as np

        positions_px = np.concatenate(all_positions)
        widths_px    = np.concatenate(all_widths)
        order        = np.argsort(positions_px)
        positions_px = positions_px[order]
        widths_px    = widths_px[order]

        # Bin by rounded position (bin width = 1.0 px)
        bins = np.round(positions_px).astype(np.int64)
        unique_bins, inverse = np.unique(bins, return_inverse=True)

        reconciled_positions = []
        reconciled_widths    = []
        disagreements        = []
        n_overlapping        = 0

        for i in range(len(unique_bins)):
            mask = inverse == i
            ws = widths_px[mask]
            ps = positions_px[mask]

            if len(ws) > 1:
                n_overlapping += 1
                disagreements.append(float(np.std(ws, ddof=1) if len(ws) > 1 else 0.0))
            else:
                disagreements.append(0.0)

            reconciled_positions.append(float(np.mean(ps)))
            reconciled_widths.append(float(np.mean(ws)))

        positions_out = np.array(reconciled_positions)
        widths_out    = np.array(reconciled_widths)

        mean_disagreement = float(np.mean(disagreements)) if disagreements else 0.0
        max_disagreement  = float(np.max(disagreements)) if disagreements else 0.0

        stitch_flag = (
            mean_disagreement > 5.0
            or (len(unique_bins) > 0 and n_overlapping > 0.2 * len(unique_bins))
        )

        stitch_quality = {
            "n_overlapping_bins":    n_overlapping,
            "mean_disagreement_px":  mean_disagreement,
            "max_disagreement_px":   max_disagreement,
            "stitch_flag":           stitch_flag,
        }

        return positions_out, widths_out, stitch_quality

    # ── Smoothing ───────────────────────────────────────────────────

    def _smooth(self, widths):
        """Apply rolling-mean smoothing if smooth_window > 1."""
        import numpy as np
        if self.smooth_window and self.smooth_window > 1:
            try:
                import pandas as pd
                return (
                    pd.Series(widths)
                    .rolling(self.smooth_window, center=True, min_periods=1)
                    .mean()
                    .to_numpy()
                )
            except ImportError:
                kernel = np.ones(self.smooth_window) / self.smooth_window
                return np.convolve(widths, kernel, mode="same")
        return widths.copy()

    # ── Statistics (B3) ─────────────────────────────────────────────

    @staticmethod
    def _compute_stats(position_out, widths_sm, n_images: int) -> dict:
        """Compute classic + robust (MAD-based) summary statistics."""
        import numpy as np
        mean_w  = float(widths_sm.mean())
        std_w   = float(widths_sm.std(ddof=1)) if len(widths_sm) > 1 else 0.0
        cv_pct  = (std_w / mean_w * 100) if mean_w else 0.0
        min_w   = float(widths_sm.min())
        max_w   = float(widths_sm.max())
        min_pos = float(position_out[int(np.argmin(widths_sm))])
        max_pos = float(position_out[int(np.argmax(widths_sm))])

        # ── B3: Robust statistics using median and MAD ──────────────
        median_w     = float(np.median(widths_sm))
        mad_w        = float(np.median(np.abs(widths_sm - median_w)))
        robust_std_w = mad_w * 1.4826          # scale factor for normal-equivalent std
        robust_cv    = (robust_std_w / median_w * 100.0) if median_w else 0.0

        return {
            "mean":          mean_w,
            "std":           std_w,
            "cv_pct":        cv_pct,
            "min":           min_w,
            "max":           max_w,
            "min_pos":       min_pos,
            "max_pos":       max_pos,
            "n_points":      len(widths_sm),
            "n_images":      n_images,
            # Phase B robust stats
            "median":        median_w,
            "mad":           mad_w,
            "robust_std":    robust_std_w,
            "robust_cv_pct": robust_cv,
        }

    # ── Figure Builder (B3 median line + dual CV title) ─────────────

    def _build_figure(self, position_out, widths_raw, widths_sm, stats) -> object:
        """Build a matplotlib Figure with raw/smoothed profiles, mean, median, and ±1σ lines."""
        from matplotlib.figure import Figure

        ul   = self.unit
        st   = stats
        fig  = Figure(figsize=(11, 5), facecolor="#1e1e2e")
        ax   = fig.add_subplot(111)
        ax.set_facecolor("#1e1e2e")

        ax.plot(
            position_out, widths_raw,
            color="#888888", linewidth=0.7, alpha=0.5, label="raw",
        )
        if self.smooth_window and self.smooth_window > 1:
            ax.plot(
                position_out, widths_sm,
                color="#4da6ff", linewidth=2, label="smoothed",
            )
        else:
            ax.plot(
                position_out, widths_sm,
                color="#4da6ff", linewidth=1.2, label="width",
            )

        # Mean line
        ax.axhline(
            st["mean"], color="#44dd88", linestyle="--", linewidth=1,
            label=f"mean = {st['mean']:.2f} {ul}",
        )
        # ±1 std lines
        ax.axhline(
            st["mean"] + st["std"], color="orange", linestyle=":", linewidth=1,
            label=f"±1 std ({st['std']:.2f} {ul})",
        )
        ax.axhline(
            st["mean"] - st["std"], color="orange", linestyle=":", linewidth=1,
        )
        # ── B3: Median line ─────────────────────────────────────────
        ax.axhline(
            st["median"], color="#ffaa44", linestyle="-.", linewidth=1,
            label=f"median = {st['median']:.2f} {ul}",
        )

        ax.scatter(
            [st["min_pos"]], [st["min"]],
            color="red", zorder=5, label=f"min = {st['min']:.2f} {ul}",
        )
        ax.scatter(
            [st["max_pos"]], [st["max"]],
            color="#cc44ff", zorder=5, label=f"max = {st['max']:.2f} {ul}",
        )

        ax.set_xlabel(f"Position along line ({ul})", color="#cccccc", fontsize=10)
        ax.set_ylabel(f"Line width ({ul})", color="#cccccc", fontsize=10)
        # ── B3: Dual CV title ───────────────────────────────────────
        ax.set_title(
            f"Line Width vs. Position   |   "
            f"CV% = {st['cv_pct']:.2f}% (classic) | {st['robust_cv_pct']:.2f}% (robust MAD)"
            f"   |   n = {st['n_images']} image(s)",
            color="#eeeeff", fontsize=11, fontweight="bold",
        )
        ax.tick_params(colors="#cccccc")
        ax.grid(True, color="#444466", linewidth=0.4, linestyle=":", alpha=0.7)
        for spine in ax.spines.values():
            spine.set_edgecolor("#666688")

        ax.legend(
            loc="upper right", fontsize=8,
            facecolor="#2a2a3e", edgecolor="#666688", labelcolor="#cccccc",
        )
        fig.tight_layout()
        return fig

    # ── Batch QA Summary (B5.2) ─────────────────────────────────────

    def _write_batch_qa_summary(
        self, target: str, results: dict, qa_failures: list, saved_paths: list,
    ) -> None:
        """Generate qa_batch_summary.txt with full traceability report."""
        from datetime import datetime

        summary_path = os.path.join(target, "qa_batch_summary.txt")
        lines = []
        n_images = len(self.images)

        lines.append("=== BATCH QA SUMMARY ===")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Total images processed: {n_images}")
        lines.append(f"Output directory: {target}")
        lines.append("")

        # ── Adaptive thresholds ─────────────────────────────────────
        lines.append("--- ADAPTIVE THRESHOLDS ---")
        thresholds_used = results.get("thresholds_used", {})
        for path in self.images:
            tval = thresholds_used.get(path, self.threshold)
            warn = ""
            if tval < 30:
                warn = "  [WARN: low]"
            elif tval > 220:
                warn = "  [WARN: high]"
            lines.append(f"{os.path.basename(path)}: threshold={tval}{warn}")
        lines.append("")

        # ── Rejected rows ───────────────────────────────────────────
        lines.append("--- REJECTED ROWS ---")
        row_logs = results.get("row_logs", {})
        for path in self.images:
            log = row_logs.get(path, [])
            if not log:
                lines.append(f"{os.path.basename(path)}: 0 rows (no data)")
                continue
            total = len(log)
            rejected = [r for r in log if r.get("status") == "rejected"]
            n_rej = len(rejected)
            pct = n_rej / total * 100.0 if total > 0 else 0.0

            # Count reasons
            from collections import Counter
            reason_counts = Counter(r.get("reason", "unknown") for r in rejected)
            reason_str = ", ".join(f"{k}={v}" for k, v in reason_counts.items())

            lines.append(
                f"{os.path.basename(path)}: {n_rej} rows rejected ({pct:.1f}% of total)"
            )
            lines.append(f"  Reasons: {reason_str if reason_str else 'none'}")
        lines.append("")

        # ── Stitch quality ──────────────────────────────────────────
        lines.append("--- STITCH QUALITY ---")
        sq = results.get("stitch_quality", {})
        if sq:
            lines.append(
                f"Overlapping bins: {sq.get('n_overlapping_bins', 0)}  |  "
                f"Mean disagreement: {sq.get('mean_disagreement_px', 0.0):.2f}px  |  "
                f"Flag: {sq.get('stitch_flag', False)}"
            )
        else:
            lines.append("No stitch quality data available.")
        lines.append("")

        # ── QA overlay save failures ────────────────────────────────
        lines.append("--- QA OVERLAY SAVE FAILURES ---")
        if qa_failures:
            for f in qa_failures:
                lines.append(f"{os.path.basename(f['image'])}: {f['error']}")
        else:
            lines.append("None")
        lines.append("")

        # ── Flagged runs ────────────────────────────────────────────
        lines.append("--- FLAGGED RUNS ---")
        flagged_any = False
        for path in self.images:
            flags = []
            log = row_logs.get(path, [])
            if log:
                total = len(log)
                n_rej = sum(1 for r in log if r.get("status") == "rejected")
                if total > 0 and n_rej / total > 0.05:
                    flags.append(f">{n_rej / total * 100:.1f}% rows rejected")

            tval = thresholds_used.get(path, self.threshold)
            if tval < 30 or tval > 220:
                flags.append(f"threshold warning ({tval})")

            if sq and sq.get("stitch_flag", False):
                flags.append("stitch_flag=True")

            if flags:
                flagged_any = True
                lines.append(f"{os.path.basename(path)}: {'; '.join(flags)}")

        if not flagged_any:
            lines.append("None — all images passed QA checks.")
        lines.append("")

        # Write
        with open(summary_path, "w") as fh:
            fh.write("\n".join(lines))

    # ── CSV Writers ─────────────────────────────────────────────────

    @staticmethod
    def _write_csv(path: str, headers: list, data) -> None:
        """Write a list-of-dicts or 2D array to CSV with given headers."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            import pandas as pd
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                df = pd.DataFrame(data, columns=headers)
            else:
                df = pd.DataFrame(data, columns=headers)
            df.to_csv(path, index=False)
        except ImportError:
            import csv
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    for row in data:
                        w.writerow([row.get(h, "") for h in headers])
                else:
                    for row in data:
                        w.writerow(row)

    @staticmethod
    def _write_summary_csv(path: str, rows: list) -> None:
        """Write a two-column [metric, value] summary CSV."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            import pandas as pd
            df = pd.DataFrame(rows, columns=["metric", "value"])
            df.to_csv(path, index=False)
        except ImportError:
            import csv
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["metric", "value"])
                for row in rows:
                    w.writerow(row)