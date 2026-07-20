# ============================================================
# line_width_engine.py
# ============================================================
#!/usr/bin/env python3
"""
line_width_engine.py
━━━━━━━━━━━━━━━━━━━
Engine class that encapsulates all analysis logic from
line_width_analysis.py without saving anything to disk during
analyze().  Call save_results() to persist outputs.
"""

import glob
import os


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class LineWidthAnalyzer:
    """
    Measures line-width consistency from one or more overlapping
    microscope images.

    Parameters
    ----------
    images        : list[str]  – ordered file paths
    scale         : float      – µm per pixel
    threshold     : int        – grayscale cut-off (default 200)
    orientation   : str        – "vertical" or "horizontal"
    smooth_window : int        – rolling-average window; 0 = off
    overlap_px    : float      – known frame overlap in pixels (0 = none)
    unit          : str        – "um" or "mm"
    outdir        : str        – default output directory for save_results()
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
    ):
        self.images        = self._expand_paths(images)
        self.scale         = float(scale)
        self.threshold     = int(threshold)
        self.orientation   = orientation
        self.smooth_window = int(smooth_window)
        self.overlap_px    = float(overlap_px)
        self.unit          = unit
        self.outdir        = outdir

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def analyze(self) -> dict:
        """
        Run the full analysis pipeline.

        Returns
        -------
        dict with keys:
          "width_profile"  – numpy array shape (N, 3):
                             [position, width_raw, width_smoothed]
          "stats"          – dict: mean, std, cv_pct, min, max,
                                   min_pos, max_pos, n_points, n_images
          "qa_image"       – numpy RGB image (last processed frame
                             with red edge dots)
          "fig_plot"       – matplotlib Figure (width vs position)
        """
        import numpy as np

        all_positions   = []
        all_widths      = []
        cumulative_off  = 0.0
        last_overlay_rgb = None

        for path in self.images:
            img, gray = self._load_image(path)

            idxs, e1s, e2s = self._detect_edges(gray)
            if idxs.size == 0:
                continue

            widths_px    = e2s - e1s
            positions_px = idxs.astype(np.float64) + cumulative_off

            all_positions.append(positions_px)
            all_widths.append(widths_px)

            # QA overlay (kept in memory; written only in save_results)
            overlay_bgr  = self._draw_qa_overlay(img, idxs, e1s, e2s)
            last_overlay_rgb = overlay_bgr[:, :, ::-1].copy()   # BGR→RGB

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

        positions_px, widths_px = self._stitch(all_positions, all_widths)

        unit_factor  = 1.0 if self.unit == "um" else 0.001
        position_out = (positions_px - positions_px.min()) * self.scale * unit_factor
        widths_raw   = widths_px * self.scale * unit_factor
        widths_sm    = self._smooth(widths_raw)

        stats = self._compute_stats(position_out, widths_sm, len(self.images))

        profile = np.column_stack([position_out, widths_raw, widths_sm])
        fig     = self._build_figure(position_out, widths_raw, widths_sm, stats)

        return {
            "width_profile": profile,
            "stats":         stats,
            "qa_image":      last_overlay_rgb,
            "fig_plot":      fig,
        }

    def save_results(self, results: dict, outdir: str = None) -> list:
        """
        Write CSV files and QA overlay images to *outdir*.

        Returns list of saved file paths.
        """
        import cv2
        import numpy as np

        target = outdir or self.outdir
        os.makedirs(target, exist_ok=True)

        saved = []
        ul    = self.unit

        # ── width_profile.csv ───────────────────────────────────────────
        profile  = results["width_profile"]
        csv_path = os.path.join(target, "width_profile.csv")
        self._write_csv(
            csv_path,
            [f"position_{ul}", f"width_{ul}", f"width_{ul}_smoothed"],
            profile,
        )
        saved.append(csv_path)

        # ── summary_stats.csv ───────────────────────────────────────────
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
        ]
        self._write_summary_csv(sum_path, rows)
        saved.append(sum_path)

        # ── QA overlay images ────────────────────────────────────────────
        for n, path in enumerate(self.images):
            try:
                img, gray = self._load_image(path)
                idxs, e1s, e2s = self._detect_edges(gray)
                if idxs.size == 0:
                    continue
                overlay_bgr = self._draw_qa_overlay(img, idxs, e1s, e2s)
                qa_path     = os.path.join(target, f"qa_overlay_{n+1:02d}.png")
                cv2.imwrite(qa_path, overlay_bgr)
                saved.append(qa_path)
            except Exception:
                pass

        # ── width_vs_position.png ────────────────────────────────────────
        fig      = results["fig_plot"]
        fig_path = os.path.join(target, "width_vs_position.png")
        fig.savefig(fig_path, dpi=200, bbox_inches="tight")
        saved.append(fig_path)

        return saved

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_paths(patterns: list) -> list:
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
        import cv2
        img = cv2.imread(path)
        if img is None:
            raise FileNotFoundError(f"Could not read image: {path}")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img, gray

    def _detect_edges(self, gray):
        """
        Detect left/right (or top/bottom) line edges in every row/column.
        Returns (idxs, e1s, e2s) as numpy integer arrays.
        """
        import cv2
        import numpy as np

        g = gray
        if self.orientation == "horizontal":
            g = g.T

        h, w   = g.shape
        g_blur = cv2.GaussianBlur(g, (9, 9), 0)

        idxs, e1s, e2s = [], [], []
        for i in range(h):
            row   = g_blur[i, :]
            below = row < self.threshold
            if not below.any():
                continue
            l_idx = int(np.argmax(below))
            r_idx = int(w - 1 - np.argmax(below[::-1]))
            if r_idx <= l_idx:
                continue
            idxs.append(i)
            e1s.append(l_idx)
            e2s.append(r_idx)

        return (
            np.array(idxs,  dtype=np.int64),
            np.array(e1s,   dtype=np.int64),
            np.array(e2s,   dtype=np.int64),
        )

    def _draw_qa_overlay(self, img, idxs, e1s, e2s):
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

    @staticmethod
    def _stitch(all_positions: list, all_widths: list):
        import numpy as np
        positions_px = np.concatenate(all_positions)
        widths_px    = np.concatenate(all_widths)
        order        = np.argsort(positions_px)
        positions_px = positions_px[order]
        widths_px    = widths_px[order]
        bins         = np.round(positions_px).astype(np.int64)
        _, unique    = np.unique(bins, return_index=True)
        return positions_px[unique], widths_px[unique]

    def _smooth(self, widths):
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
                # Fallback: simple uniform convolution
                kernel = np.ones(self.smooth_window) / self.smooth_window
                return np.convolve(widths, kernel, mode="same")
        return widths.copy()

    @staticmethod
    def _compute_stats(position_out, widths_sm, n_images: int) -> dict:
        import numpy as np
        mean_w  = float(widths_sm.mean())
        std_w   = float(widths_sm.std(ddof=1)) if len(widths_sm) > 1 else 0.0
        cv_pct  = (std_w / mean_w * 100) if mean_w else 0.0
        min_w   = float(widths_sm.min())
        max_w   = float(widths_sm.max())
        min_pos = float(position_out[int(np.argmin(widths_sm))])
        max_pos = float(position_out[int(np.argmax(widths_sm))])
        return {
            "mean":     mean_w,
            "std":      std_w,
            "cv_pct":   cv_pct,
            "min":      min_w,
            "max":      max_w,
            "min_pos":  min_pos,
            "max_pos":  max_pos,
            "n_points": len(widths_sm),
            "n_images": n_images,
        }

    def _build_figure(self, position_out, widths_raw, widths_sm, stats) -> object:
        """Build and return a matplotlib Figure (not shown, not saved)."""
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

        ax.axhline(
            st["mean"], color="#44dd88", linestyle="--", linewidth=1,
            label=f"mean = {st['mean']:.2f} {ul}",
        )
        ax.axhline(
            st["mean"] + st["std"], color="orange", linestyle=":", linewidth=1,
            label=f"±1 std ({st['std']:.2f} {ul})",
        )
        ax.axhline(
            st["mean"] - st["std"], color="orange", linestyle=":", linewidth=1,
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
        ax.set_title(
            f"Line Width vs. Position   |   CV% = {st['cv_pct']:.2f}%"
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

    # ------------------------------------------------------------------
    # CSV helpers (no pandas dependency required)
    # ------------------------------------------------------------------

    @staticmethod
    def _write_csv(path: str, headers: list, data) -> None:
        """Write a CSV with given headers and a 2-D array of data rows."""
        try:
            import pandas as pd
            import numpy as np
            df = pd.DataFrame(data, columns=headers)
            df.to_csv(path, index=False)
        except ImportError:
            import csv, numpy as np
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                for row in data:
                    w.writerow(row)

    @staticmethod
    def _write_summary_csv(path: str, rows: list) -> None:
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