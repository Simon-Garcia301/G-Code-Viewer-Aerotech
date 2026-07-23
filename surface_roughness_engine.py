import os
import numpy as np
import cv2
import csv
from typing import List, Tuple, Optional

class SurfaceRoughnessAnalyzer:
    """
    Quantifies surface roughness (mean, std, CV%) inside a user‑defined ROI,
    excluding masked glare polygons and optionally a brightness threshold.
    """

    def __init__(self,
                 images: List[str],
                 rect: Tuple[int, int, int, int],
                 masks: List[List[Tuple[int, int]]],
                 glare_threshold: Optional[int],
                 outdir: str):
        """
        Parameters
        ----------
        images : list of str
            Full paths to image files.
        rect : (x0, y0, x1, y1)
            Rectangle ROI in pixel coordinates (top‑left, bottom‑right inclusive).
        masks : list of list of (x, y)
            Each inner list defines a polygon whose interior is excluded.
        glare_threshold : int or None
            If not None, pixels with intensity > threshold are excluded.
        outdir : str
            Default output directory for save_results().
        """
        self.images = images
        self.rect = rect
        self.masks = masks
        self.glare_threshold = glare_threshold
        self.outdir = outdir

    # ----------------------------------------------------------------------
    # public interface
    # ----------------------------------------------------------------------
    def analyze(self) -> dict:
        """
        Process all images and return statistics.

        Returns
        -------
        dict with keys:
            "per_image" : list of per‑image dicts
            "aggregate" : dict with overall_mean_cv, overall_std_cv, n_processed
            "histogram_data" : 1D numpy array of all valid pixel intensities
            "mask_overlay" : last image as RGB with ROI (green) and masks (red)
        """
        per_image_results = []
        valid_pools = []
        cvs = []
        last_overlay = None

        for path in self.images:
            img = cv2.imread(path)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape

            # --- build full mask -------------------------------------------------
            mask = np.ones((h, w), dtype=np.uint8) * 255

            # 1) restrict to rectangle
            x0, y0, x1, y1 = self.rect
            # clip to image bounds
            x0 = max(0, min(x0, w - 1))
            x1 = max(0, min(x1, w - 1))
            y0 = max(0, min(y0, h - 1))
            y1 = max(0, min(y1, h - 1))
            if x0 > x1:
                x0, x1 = x1, x0
            if y0 > y1:
                y0, y1 = y1, y0

            mask[:] = 0                    # all black
            mask[y0:y1 + 1, x0:x1 + 1] = 255  # inside ROI white

            # 2) exclude polygon masks (black)
            for poly in self.masks:
                pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [pts], color=0)

            # 3) glare threshold
            if self.glare_threshold is not None:
                glare_mask = gray > self.glare_threshold
                mask[glare_mask] = 0

            # valid intensities
            valid = gray[mask == 255]
            if len(valid) == 0:
                continue

            mean_val = np.mean(valid)
            std_val = np.std(valid, ddof=1)
            cv_pct = (std_val / mean_val) * 100 if mean_val != 0 else 0.0

            per_image_results.append({
                "filename": os.path.basename(path),
                "mean_intensity": mean_val,
                "std_intensity": std_val,
                "cv_percent": cv_pct,
                "n_valid_pixels": len(valid)
            })
            valid_pools.append(valid)
            cvs.append(cv_pct)

            # keep the last image for overlay
            last_gray = gray.copy()
            last_rect = (x0, y0, x1, y1)

        # --- aggregate --------------------------------------------------------
        if not cvs:
            agg = {"overall_mean_cv": 0.0, "overall_std_cv": 0.0, "n_processed": 0}
        else:
            agg = {
                "overall_mean_cv": float(np.mean(cvs)),
                "overall_std_cv": float(np.std(cvs, ddof=1)),
                "n_processed": len(cvs)
            }

        # --- histogram pool ---------------------------------------------------
        if valid_pools:
            hist_data = np.concatenate(valid_pools)
        else:
            hist_data = np.array([])

        # --- mask overlay on last image ---------------------------------------
        if last_gray is not None:
            overlay = self._build_overlay(last_gray, last_rect, self.masks)
        else:
            overlay = None

        return {
            "per_image": per_image_results,
            "aggregate": agg,
            "histogram_data": hist_data,
            "mask_overlay": overlay
        }

    def save_results(self, outdir: str = None) -> List[str]:
        """
        Write a CSV summary to `outdir/surface_cv_results.csv`.

        Parameters
        ----------
        outdir : str, optional
            Overrides the output directory given at construction time.

        Returns
        -------
        list of str
            Paths of the written files (only the CSV).
        """
        target_dir = outdir if outdir is not None else self.outdir
        os.makedirs(target_dir, exist_ok=True)
        csv_path = os.path.join(target_dir, "surface_cv_results.csv")

        # run analysis if not done yet (we could cache it, but for simplicity run)
        results = self.analyze()
        per_image = results["per_image"]
        agg = results["aggregate"]

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["filename", "mean_intensity", "std_intensity",
                             "cv_percent", "n_valid_pixels"])
            for row in per_image:
                writer.writerow([
                    row["filename"],
                    row["mean_intensity"],
                    row["std_intensity"],
                    self._format_3sf(row["cv_percent"]),
                    row["n_valid_pixels"]
                ])
            writer.writerow([])  # blank row
            writer.writerow(["Summary"])
            writer.writerow([
                self._format_3sf(agg["overall_mean_cv"]),
                self._format_3sf(agg["overall_std_cv"]),
                agg["n_processed"]
            ])
        return [csv_path]

    # ----------------------------------------------------------------------
    # helpers
    # ----------------------------------------------------------------------
    @staticmethod
    def _format_3sf(value: float) -> str:
        """Return a string representation with 3 significant figures."""
        if value == 0:
            return "0"
        return f"{value:.3g}"

    def _build_overlay(self, gray: np.ndarray,
                       rect: Tuple[int, int, int, int],
                       polys: List[List[Tuple[int, int]]]) -> np.ndarray:
        """Create an RGB overlay image showing ROI (green) and masks (red semi‑transparent)."""
        h, w = gray.shape
        # base image as grayscale RGB
        base_rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

        # --- draw ROI rectangle (solid green) ----------------------------------
        x0, y0, x1, y1 = rect
        overlay_rect = base_rgb.copy()
        cv2.rectangle(overlay_rect, (x0, y0), (x1, y1), (0, 255, 0), thickness=2)

        # --- draw mask polygons as semi‑transparent red ------------------------
        # create a mask for polygons
        mask_poly = np.zeros((h, w), dtype=np.uint8)
        for poly in polys:
            pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(mask_poly, [pts], 255)

        # red image where polygons are
        poly_color = np.zeros_like(overlay_rect)
        poly_color[:] = (0, 0, 255)  # red
        poly_color = cv2.bitwise_and(poly_color, poly_color, mask=mask_poly)

        alpha = 0.3  # transparency
        final = cv2.addWeighted(overlay_rect, 1.0, poly_color, alpha, 0)
        return final  # This is BGR; the GUI will convert to RGB for display
