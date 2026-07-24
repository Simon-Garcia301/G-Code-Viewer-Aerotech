"""
surface_roughness_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core surface roughness analyzer supporting self-calibrating flat-field
correction for 5x coaxial illumination and CV% reflectance profiling.
"""

import os
import csv
import warnings
import numpy as np
import cv2
from typing import List, Tuple, Optional
from ui_common import LENS_CALIBRATION_UM_PER_PX

class SurfaceRoughnessAnalyzer:
    """
    Quantifies surface roughness (mean, std, CV%) inside a user-defined ROI,
    excluding masked glare polygons and brightness thresholds. Automatically
    applies flat-field vignetting correction for 5x coaxial objective optics.
    """

    def __init__(
        self,
        images: List[str],
        rect: Tuple[int, int, int, int],
        masks: List[List[Tuple[int, int]]],
        glare_threshold: Optional[int],
        outdir: str,
        scale_um_per_px: float = LENS_CALIBRATION_UM_PER_PX["5x"],
        lens: str = "5x",
        flat_field_correction: bool = True,
    ):
        """
        Parameters
        ----------
        images : list of str
            Full paths to image files.
        rect : (x0, y0, x1, y1)
            Rectangle ROI in pixel coordinates (top-left, bottom-right inclusive).
        masks : list of list of (x, y)
            Polygons defining regions to exclude.
        glare_threshold : int or None
            If set, pixels > threshold are excluded from statistics.
        outdir : str
            Output directory for saved results.
        scale_um_per_px : float
            Microns per pixel scale factor for metadata traceability.
        lens : str
            Lens magnification descriptor ("5x").
        flat_field_correction : bool
            Enable self-calibrating optical vignetting correction.
        """
        self.images = images
        self.rect = rect
        self.masks = masks
        self.glare_threshold = glare_threshold
        self.outdir = outdir
        self.scale_um_per_px = scale_um_per_px
        self.lens = lens
        self.flat_field_correction = flat_field_correction

    def _flat_field_correct(self, gray: np.ndarray) -> np.ndarray:
        """
        Estimate and remove coaxial-illumination vignetting field from a
        grayscale image using a self-calibration (rolling-ball / heavy blur)
        background estimate — no reference/calibration image required.

        OPTICAL RATIONALE & BACKGROUND:
        The tool is used with the 5x LM (through-the-lens, coaxial) objective lens.
        Coaxial illumination produces a radially symmetric vignetting (brighter center,
        dimmer edges) that is a property of the optical path, not the sample surface.
        Computing CV% directly on raw grayscale intensity conflates true surface-reflectance
        variation with this optical vignetting, inflating CV% for any sample, especially
        near ROI edges.

        Steps:
          1. Estimate the illumination field by heavily blurring the image
             (large-kernel Gaussian, sigma scaled to image size ~1/8 of max(h, w))
             to remove high-frequency surface detail while retaining low-frequency optical falloff.
          2. Normalize: corrected = gray / (illumination_field + epsilon),
             rescaled back by the field's mean so absolute brightness scale is
             preserved and downstream glare_threshold comparisons remain meaningful.
          3. Return corrected image array clipped to [0, 255].
        """
        h, w = gray.shape
        sigma = max(h, w) / 8.0

        gray_f = gray.astype(np.float64)
        illumination_field = cv2.GaussianBlur(gray_f, (0, 0), sigmaX=sigma, sigmaY=sigma)

        field_range = illumination_field.max() - illumination_field.min()
        if field_range < 5.0:
            warnings.warn(
                f"[SurfaceRoughnessAnalyzer] Estimated illumination field has low dynamic range ({field_range:.2f}). "
                "Flat-field correction may have minimal impact."
            )

        epsilon = 1e-5
        field_mean = float(np.mean(illumination_field))
        corrected = (gray_f / (illumination_field + epsilon)) * field_mean
        return np.clip(corrected, 0, 255)

    def analyze(self) -> dict:
        """
        Process all loaded images and compute surface statistics.

        Returns
        -------
        dict with keys:
            "per_image": list of per-image metric dicts
            "aggregate": dict with overall_mean_cv, overall_std_cv, n_processed
            "histogram_data": 1D numpy array of valid corrected pixel intensities
            "mask_overlay": RGB overlay image built from uncorrected grayscale for visual fidelity
        """
        per_image_results = []
        valid_pools = []
        cvs = []
        last_overlay_gray = None
        last_rect = None

        for path in self.images:
            img = cv2.imread(path)
            if img is None:
                continue

            gray_orig = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray_orig.shape

            # Apply self-calibrating flat-field correction for statistical computation
            if self.flat_field_correction:
                gray_analysis = self._flat_field_correct(gray_orig)
            else:
                gray_analysis = gray_orig.astype(np.float64)

            # Build full mask
            mask = np.ones((h, w), dtype=np.uint8) * 255

            x0, y0, x1, y1 = self.rect
            x0 = max(0, min(x0, w - 1))
            x1 = max(0, min(x1, w - 1))
            y0 = max(0, min(y0, h - 1))
            y1 = max(0, min(y1, h - 1))
            if x0 > x1:
                x0, x1 = x1, x0
            if y0 > y1:
                y0, y1 = y1, y0

            mask[:] = 0
            mask[y0:y1 + 1, x0:x1 + 1] = 255

            for poly in self.masks:
                pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [pts], color=0)

            if self.glare_threshold is not None:
                glare_mask = gray_analysis > self.glare_threshold
                mask[glare_mask] = 0

            valid = gray_analysis[mask == 255]
            if len(valid) == 0:
                continue

            mean_val = float(np.mean(valid))
            std_val = float(np.std(valid, ddof=1)) if len(valid) > 1 else 0.0
            cv_pct = (std_val / mean_val) * 100.0 if mean_val != 0 else 0.0

            per_image_results.append({
                "filename": os.path.basename(path),
                "mean_intensity": mean_val,
                "std_intensity": std_val,
                "cv_percent": cv_pct,
                "n_valid_pixels": len(valid),
            })
            valid_pools.append(valid)
            cvs.append(cv_pct)

            # Preserve original uncorrected image for visual QA overlay
            last_overlay_gray = gray_orig.copy()
            last_rect = (x0, y0, x1, y1)

        if not cvs:
            agg = {"overall_mean_cv": 0.0, "overall_std_cv": 0.0, "n_processed": 0}
        else:
            agg = {
                "overall_mean_cv": float(np.mean(cvs)),
                "overall_std_cv": float(np.std(cvs, ddof=1)) if len(cvs) > 1 else 0.0,
                "n_processed": len(cvs),
            }

        hist_data = np.concatenate(valid_pools) if valid_pools else np.array([])
        overlay = self._build_overlay(last_overlay_gray, last_rect, self.masks) if last_overlay_gray is not None else None

        return {
            "per_image": per_image_results,
            "aggregate": agg,
            "histogram_data": hist_data,
            "mask_overlay": overlay,
        }

    def save_results(self, outdir: str = None) -> List[str]:
        """Write CSV summary output with lens and scale metadata for lab records."""
        target_dir = outdir if outdir is not None else self.outdir
        os.makedirs(target_dir, exist_ok=True)
        csv_path = os.path.join(target_dir, "surface_cv_results.csv")

        results = self.analyze()
        per_image = results["per_image"]
        agg = results["aggregate"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["filename", "mean_intensity", "std_intensity", "cv_percent", "n_valid_pixels"])
            for row in per_image:
                writer.writerow([
                    row["filename"],
                    row["mean_intensity"],
                    row["std_intensity"],
                    self._format_3sf(row["cv_percent"]),
                    row["n_valid_pixels"],
                ])
            writer.writerow([])
            writer.writerow(["Summary Metadata"])
            writer.writerow(["lens", self.lens])
            writer.writerow(["scale_um_per_px", self.scale_um_per_px])
            writer.writerow(["overall_mean_cv", self._format_3sf(agg["overall_mean_cv"])])
            writer.writerow(["overall_std_cv", self._format_3sf(agg["overall_std_cv"])])
            writer.writerow(["n_processed", agg["n_processed"]])

        return [csv_path]

    @staticmethod
    def _format_3sf(value: float) -> str:
        """Format number to 3 significant figures."""
        if value == 0:
            return "0"
        return f"{value:.3g}"

    def _build_overlay(self, gray: np.ndarray, rect: Tuple[int, int, int, int], polys: List[List[Tuple[int, int]]]) -> np.ndarray:
        """Build RGB overlay image showing ROI (green) and masks (red) on uncorrected grayscale."""
        h, w = gray.shape
        base_rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

        x0, y0, x1, y1 = rect
        overlay_rect = base_rgb.copy()
        cv2.rectangle(overlay_rect, (x0, y0), (x1, y1), (0, 255, 0), thickness=2)

        mask_poly = np.zeros((h, w), dtype=np.uint8)
        for poly in polys:
            pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(mask_poly, [pts], 255)

        poly_color = np.zeros_like(overlay_rect)
        poly_color[:] = (0, 0, 255)
        poly_color = cv2.bitwise_and(poly_color, poly_color, mask=mask_poly)

        alpha = 0.3
        return cv2.addWeighted(overlay_rect, 1.0, poly_color, alpha, 0)