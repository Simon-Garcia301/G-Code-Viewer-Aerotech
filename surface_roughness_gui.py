#!/usr/bin/env python3
"""
surface_roughness_gui.py
━━━━━━━━━━━━━━━━━━━━━━━━
GUI front-end for Surface Roughness Analyzer. Refactored to match suite
design language using ui_common components and enforcing 5x coaxial lens constraints.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Rectangle, Polygon
from matplotlib.widgets import RectangleSelector, PolygonSelector

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from surface_roughness_engine import SurfaceRoughnessAnalyzer
from ui_common import (
    LENS_CALIBRATION_UM_PER_PX,
    make_app_header,
    make_app_footer,
    make_scrollable_left_panel,
    make_titled_panel,
    section_label,
    small_label,
    make_status_label,
    set_status,
    make_progress_bar,
    make_action_button,
    attach_tooltip,
    load_app_icon,
    show_about_dialog,
)

class SurfaceRoughnessGUI:
    def __init__(self, root: ttk.Window):
        self.root = root
        self.root.title("Lee Research Lab — Surface Roughness Analysis")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)

        load_app_icon(self.root)

        # State Variables
        self._images = []
        self._current_image_index = -1
        self._roi = None
        self._mask_polygons = []
        self._glare_enabled = tk.BooleanVar(value=False)
        self._glare_value = tk.StringVar(value="200")
        self._scale_var = tk.StringVar(value="5x")
        self._outdir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "surface_roughness_results"))

        self._analyzer = None
        self._last_results = None

        self._roi_patch = None
        self._mask_patches = []
        self._roi_selector = None
        self._poly_selector = None

        # Figure & Canvas Setup
        self._fig, (self._ax_qa, self._ax_hist) = plt.subplots(
            2, 1, figsize=(8, 8), constrained_layout=True
        )
        for ax in (self._ax_qa, self._ax_hist):
            ax.set_facecolor("#1e1e2e")
            ax.tick_params(colors="#cccccc")
            for sp in ax.spines.values():
                sp.set_edgecolor("#666688")

        self._ax_qa.set_title("Current Image (ROI & Glare Masks)", color="#eeeeff", fontsize=11)
        self._ax_qa.axis("off")
        self._ax_hist.set_title("Histogram of Valid Reflectance Intensities", color="#eeeeff", fontsize=11)
        self._ax_hist.set_xlabel("Grayscale Intensity", color="#cccccc", fontsize=9)
        self._ax_hist.set_ylabel("Frequency", color="#cccccc", fontsize=9)

        self._fig.patch.set_facecolor("#1e1e2e")

        self._build_ui()

    def _build_ui(self):
        # Top Header
        make_app_header(
            self.root,
            title="Surface Roughness Analysis",
            subtitle="5x Coaxial Reflectance & CV% Profiler",
            on_return=self.root.destroy,
            on_about=lambda: show_about_dialog(self.root),
        )

        # Persistent Footer
        make_app_footer(self.root)

        # Main Paned Window
        main_pane = ttk.Panedwindow(self.root, orient=HORIZONTAL)
        main_pane.pack(fill=BOTH, expand=YES)

        # Left Column (Scrollable Controls)
        left_container = ttk.Frame(main_pane, padding=(10, 10, 5, 10))
        left_canvas, scrollable_frame = make_scrollable_left_panel(left_container)

        # Right Column (Matplotlib Preview)
        right_frame = ttk.Frame(main_pane, padding=(5, 10, 10, 10))
        canvas_frame = ttk.Frame(right_frame, relief="solid", borderwidth=1)
        canvas_frame.pack(fill=BOTH, expand=YES)

        self._canvas = FigureCanvasTkAgg(self._fig, master=canvas_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(side=TOP, fill=BOTH, expand=YES)

        toolbar_frame = ttk.Frame(canvas_frame)
        toolbar_frame.pack(fill=X, side=BOTTOM)
        NavigationToolbar2Tk(self._canvas, toolbar_frame).update()

        main_pane.add(left_container, weight=1)
        main_pane.add(right_frame, weight=4)

        # --- Section 1: Image Selection ---
        sec_img = make_titled_panel(scrollable_frame, "📂 Image Selection")
        self._lb_images = tk.Listbox(
            sec_img, height=6, bg="#1e1e2e", fg="#cccccc",
            selectbackground="#444466", font=("Segoe UI", 8), relief="flat", bd=0,
        )
        self._lb_images.pack(fill=X, pady=(0, 4))
        self._lb_images.bind("<<ListboxSelect>>", self._on_image_select)

        btn_row = ttk.Frame(sec_img)
        btn_row.pack(fill=X, pady=(0, 2))
        btn_add = ttk.Button(btn_row, text="➕ Add Images", bootstyle="primary-outline", command=self._select_images)
        btn_add.pack(side=LEFT, fill=X, expand=YES, padx=(0, 2))
        attach_tooltip(btn_add, "Select input microscope images for roughness analysis")

        btn_clr = ttk.Button(btn_row, text="🗑 Clear", bootstyle="secondary", command=self._clear_images)
        btn_clr.pack(side=LEFT, fill=X, expand=YES, padx=(2, 0))
        attach_tooltip(btn_clr, "Clear current image selection")

        # --- Section 2: Lens / Scale Selection ---
        sec_lens = make_titled_panel(scrollable_frame, "🔬 Lens / Calibration")
        section_label(sec_lens, "Objective Lens:")
        self._combo_scale = ttk.Combobox(
            sec_lens,
            textvariable=self._scale_var,
            values=["5x", "4x (backlight — unsupported)"],
            state="readonly",
            width=24,
        )
        self._combo_scale.pack(fill=X, pady=(0, 4))
        attach_tooltip(
            self._combo_scale,
            "4x uses backlight illumination and is not compatible with reflectance-based surface CV% measurement. Only the 5x coaxial lens is supported.",
        )
        self._combo_scale.bind("<<ComboboxSelected>>", self._on_lens_selected)
        small_label(sec_lens, "Scale: 0.6408 µm/px (5x Coaxial Reflectance)")

        # --- Section 3: Output Folder ---
        sec_out = make_titled_panel(scrollable_frame, "📁 Output Directory")
        out_entry = ttk.Entry(sec_out, textvariable=self._outdir, state="readonly", style="secondary.TEntry")
        out_entry.pack(fill=X, pady=(0, 4))
        btn_out = ttk.Button(sec_out, text="📁 Browse Folder", bootstyle="primary-outline", command=self._browse_outdir)
        btn_out.pack(fill=X)
        attach_tooltip(btn_out, "Select destination folder for output CSV and overlays")

        # --- Section 4: ROI & Mask Controls ---
        sec_roi = make_titled_panel(scrollable_frame, "📐 ROI & Mask Region")
        btn_roi = ttk.Button(sec_roi, text="📏 Draw ROI Rectangle", bootstyle="primary-outline", command=self._toggle_roi_selector)
        btn_roi.pack(fill=X, pady=(0, 4))
        attach_tooltip(btn_roi, "Click and drag on the preview image to set evaluation region")

        self._roi_label = ttk.Label(sec_roi, text="ROI: Not set", font=("Segoe UI", 8), foreground="#888888")
        self._roi_label.pack(fill=X, pady=(0, 6))

        btn_poly = ttk.Button(sec_roi, text="🖍 Add Glare Mask Polygon", bootstyle="primary-outline", command=self._toggle_poly_selector)
        btn_poly.pack(fill=X, pady=(0, 4))
        attach_tooltip(btn_poly, "Click vertices to draw an exclusion polygon around glare/artifacts")

        btn_clr_mask = ttk.Button(sec_roi, text="🗑 Clear Glare Masks", bootstyle="secondary", command=self._clear_masks)
        btn_clr_mask.pack(fill=X)
        attach_tooltip(btn_clr_mask, "Remove all drawn exclusion mask polygons")

        # --- Section 5: Glare Thresholding ---
        sec_glare = make_titled_panel(scrollable_frame, "💡 Glare Thresholding")
        cbtn = ttk.Checkbutton(
            sec_glare,
            text="Enable intensity cap",
            variable=self._glare_enabled,
            bootstyle="primary-round-toggle",
            command=self._on_glare_toggle,
        )
        cbtn.pack(anchor=W, pady=(0, 4))
        attach_tooltip(cbtn, "Exclude pixels brighter than cutoff value")

        glare_row = ttk.Frame(sec_glare)
        glare_row.pack(fill=X)
        small_label(glare_row, "Cutoff (0–255):")
        self._glare_entry = ttk.Entry(glare_row, textvariable=self._glare_value, state=DISABLED, width=10)
        self._glare_entry.pack(side=RIGHT)

        # --- Section 6: Action Execution ---
        sec_act = make_titled_panel(scrollable_frame, "⚙️ Analysis Actions")
        self._btn_compute = make_action_button(
            sec_act, text="🚀 Compute Surface CV%", bootstyle="success", command=self._on_compute_cv
        )
        attach_tooltip(self._btn_compute, "Run flat-field correction and compute surface CV% statistics")

        self._btn_save = make_action_button(
            sec_act, text="💾 Save CSV Summary", bootstyle="secondary", command=self._on_save_output, state="disabled"
        )
        attach_tooltip(self._btn_save, "Save per-image and aggregate roughness metrics to CSV")

        self._progress = make_progress_bar(scrollable_frame)
        self._status_label = make_status_label(scrollable_frame, "Ready — select images and draw ROI")

    def _on_lens_selected(self, event=None):
        if self._scale_var.get() == "4x (backlight — unsupported)":
            self._scale_var.set("5x")
            messagebox.showwarning(
                "Unsupported Objective Lens",
                "4x objective uses backlight/transmitted illumination and is not compatible with reflectance-based surface CV% measurement. Only the 5x coaxial lens is supported.",
            )
            set_status(self._status_label, "4x lens unsupported for reflectance roughness. Reverted to 5x.", "warning")

    def _select_images(self):
        files = filedialog.askopenfilenames(
            title="Select Microscope Images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"), ("All files", "*.*")],
        )
        if not files:
            return
        self._images = list(files)
        self._lb_images.delete(0, tk.END)
        for f in files:
            self._lb_images.insert(tk.END, os.path.basename(f))
        self._current_image_index = 0
        self._lb_images.selection_set(0)
        self._load_and_display_image(0)
        set_status(self._status_label, f"Loaded {len(self._images)} image(s). Draw ROI to proceed.", "info")

    def _on_image_select(self, event=None):
        sel = self._lb_images.curselection()
        if sel:
            idx = sel[0]
            self._current_image_index = idx
            self._load_and_display_image(idx)

    def _clear_images(self):
        self._images.clear()
        self._lb_images.delete(0, tk.END)
        self._current_image_index = -1
        self._ax_qa.clear()
        self._ax_qa.set_title("Current Image (ROI & Glare Masks)", color="#eeeeff")
        self._ax_qa.axis("off")
        self._canvas.draw()
        set_status(self._status_label, "Images cleared.", "info")

    def _load_and_display_image(self, index: int):
        if index < 0 or index >= len(self._images):
            return
        path = self._images[index]
        img = cv2.imread(path)
        if img is None:
            set_status(self._status_label, f"Error loading image: {path}", "error")
            return
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        self._ax_qa.clear()
        self._ax_qa.imshow(gray, cmap="gray", origin="upper")
        self._ax_qa.set_title(os.path.basename(path), color="#eeeeff", fontsize=10)
        self._ax_qa.axis("off")

        if self._roi is not None:
            x0, y0, x1, y1 = self._roi
            width, height = x1 - x0, y1 - y0
            roi_rect = Rectangle((x0, y0), width, height, linewidth=2, edgecolor="#44dd88", facecolor="none")
            self._ax_qa.add_patch(roi_rect)

        self._mask_patches.clear()
        for poly in self._mask_polygons:
            mp = Polygon(poly, closed=True, facecolor="#ff5555", edgecolor="#ff5555", alpha=0.35)
            self._ax_qa.add_patch(mp)
            self._mask_patches.append(mp)

        self._ax_qa.relim()
        self._ax_qa.autoscale_view()
        self._canvas.draw()

    def _toggle_roi_selector(self):
        if self._roi_selector is not None and self._roi_selector.active:
            self._roi_selector.set_active(False)
            self._roi_selector = None
            set_status(self._status_label, "ROI selector deactivated", "info")
            return

        if self._current_image_index < 0:
            messagebox.showwarning("No Image", "Please select image files first.")
            return

        set_status(self._status_label, "Click & drag on preview image to set ROI rectangle...", "warning")
        self._roi_selector = RectangleSelector(
            self._ax_qa,
            self._on_roi_selected,
            useblit=True,
            button=[1],
            minspanx=5,
            minspany=5,
            spancoords="data",
            interactive=True,
        )
        self._roi_selector.set_active(True)

    def _on_roi_selected(self, eclick, erelease):
        x0, y0 = eclick.xdata, eclick.ydata
        x1, y1 = erelease.xdata, erelease.ydata
        if None in (x0, y0, x1, y1):
            return
        x0, x1 = sorted([int(round(x0)), int(round(x1))])
        y0, y1 = sorted([int(round(y0)), int(round(y1))])
        self._roi = (x0, y0, x1, y1)
        if self._roi_selector:
            self._roi_selector.set_active(False)
            self._roi_selector = None
        self._roi_label.config(text=f"ROI: ({x0},{y0}) → ({x1},{y1})")
        self._load_and_display_image(self._current_image_index)
        set_status(self._status_label, f"ROI updated: ({x0},{y0}) to ({x1},{y1})", "success")

    def _toggle_poly_selector(self):
        if self._poly_selector is not None and self._poly_selector.active:
            self._poly_selector.set_active(False)
            self._poly_selector = None
            set_status(self._status_label, "Polygon selector deactivated", "info")
            return

        if self._current_image_index < 0:
            messagebox.showwarning("No Image", "Please select image files first.")
            return

        set_status(self._status_label, "Click polygon vertices, double-click to finalize mask...", "warning")
        self._poly_selector = PolygonSelector(
            self._ax_qa,
            self._on_polygon_complete,
            useblit=True,
            lineprops=dict(color="#ff5555", linestyle="-", linewidth=2),
            markerprops=dict(marker="o", markersize=4, color="#ff5555"),
        )
        self._poly_selector.set_active(True)

    def _on_polygon_complete(self, vertices):
        if vertices is None or len(vertices) < 3:
            return
        poly = [(int(round(v[0])), int(round(v[1]))) for v in vertices]
        self._mask_polygons.append(poly)
        if self._poly_selector:
            self._poly_selector.set_active(False)
            self._poly_selector = None
        self._load_and_display_image(self._current_image_index)
        set_status(self._status_label, f"Added glare mask #{len(self._mask_polygons)}", "success")

    def _clear_masks(self):
        self._mask_polygons.clear()
        self._mask_patches.clear()
        if self._current_image_index >= 0:
            self._load_and_display_image(self._current_image_index)
        set_status(self._status_label, "All glare masks cleared.", "info")

    def _on_glare_toggle(self, *args):
        if self._glare_enabled.get():
            self._glare_entry.configure(state=NORMAL)
        else:
            self._glare_entry.configure(state=DISABLED)

    def _browse_outdir(self):
        dirname = filedialog.askdirectory(title="Select Output Directory")
        if dirname:
            self._outdir.set(os.path.normpath(dirname))

    def _on_compute_cv(self):
        if not self._images:
            messagebox.showwarning("No Images", "Please select input images.")
            return
        if self._roi is None:
            messagebox.showwarning("No ROI", "Please draw an ROI rectangle first.")
            return

        self._btn_compute.configure(state=DISABLED)
        self._progress.start(12)
        set_status(self._status_label, "Applying flat-field correction & computing CV%...", "warning")

        glare_threshold = None
        if self._glare_enabled.get():
            try:
                glare_threshold = int(self._glare_value.get().strip())
            except ValueError:
                glare_threshold = 200

        scale_val = LENS_CALIBRATION_UM_PER_PX["5x"]

        threading.Thread(
            target=self._compute_thread,
            args=(
                list(self._images),
                self._roi,
                list(self._mask_polygons),
                glare_threshold,
                self._outdir.get(),
                scale_val,
            ),
            daemon=True,
        ).start()

    def _compute_thread(self, images, rect, masks, glare_threshold, outdir, scale_val):
        try:
            analyzer = SurfaceRoughnessAnalyzer(
                images=images,
                rect=rect,
                masks=masks,
                glare_threshold=glare_threshold,
                outdir=outdir,
                scale_um_per_px=scale_val,
                lens="5x",
                flat_field_correction=True,
            )
            results = analyzer.analyze()
            self.root.after(0, self._on_analysis_done, analyzer, results)
        except Exception as exc:
            self.root.after(0, self._on_analysis_error, str(exc))

    def _on_analysis_done(self, analyzer, results):
        self._analyzer = analyzer
        self._last_results = results
        self._progress.stop()
        self._btn_compute.configure(state=NORMAL)
        self._btn_save.configure(state=NORMAL)

        # Update Histogram Subplot
        self._ax_hist.clear()
        if "histogram_data" in results and len(results["histogram_data"]) > 0:
            self._ax_hist.hist(
                results["histogram_data"],
                bins=50,
                color="#4da6ff",
                edgecolor="#1e1e2e",
                alpha=0.85,
            )
        self._ax_hist.set_title("Histogram of Flat-Field Corrected Intensities", color="#eeeeff", fontsize=10)
        self._ax_hist.set_xlabel("Grayscale Intensity", color="#cccccc", fontsize=9)
        self._ax_hist.set_ylabel("Frequency", color="#cccccc", fontsize=9)
        self._canvas.draw()

        agg = results.get("aggregate", {})
        n = agg.get("n_processed", 0)
        mean_cv = agg.get("overall_mean_cv", 0.0)
        std_cv = agg.get("overall_std_cv", 0.0)

        set_status(
            self._status_label,
            f"Done. Overall Mean CV = {mean_cv:.2f}%  (±{std_cv:.2f}%) across {n} image(s)",
            "success",
        )

        msg = (
            f"Surface CV% Analysis Complete (5x Coaxial Lens)\n\n"
            f"Images Processed: {n}\n"
            f"Flat-Field Correction: Applied (self-calibrating)\n"
            f"Overall Mean CV%: {mean_cv:.3g}%\n"
            f"Overall Std CV%: {std_cv:.3g}%"
        )
        messagebox.showinfo("Roughness Results", msg)

    def _on_analysis_error(self, errmsg):
        self._progress.stop()
        self._btn_compute.configure(state=NORMAL)
        set_status(self._status_label, f"Analysis failed: {errmsg}", "error")
        messagebox.showerror("Analysis Error", f"Analysis failed:\n{errmsg}")

    def _on_save_output(self):
        if self._analyzer is None:
            return
        self._btn_save.configure(state=DISABLED)
        self._progress.start(12)
        set_status(self._status_label, "Writing CSV summary...", "warning")

        threading.Thread(target=self._save_thread, daemon=True).start()

    def _save_thread(self):
        try:
            saved = self._analyzer.save_results(outdir=self._outdir.get())
            self.root.after(0, self._on_save_done, saved)
        except Exception as exc:
            self.root.after(0, self._on_analysis_error, str(exc))

    def _on_save_done(self, paths):
        self._progress.stop()
        self._btn_save.configure(state=NORMAL)
        set_status(self._status_label, f"CSV saved to: {paths[0]}", "success")
        messagebox.showinfo("Saved", f"Results successfully saved to:\n{paths[0]}")

def build_surface_roughness_gui(root: ttk.Window = None) -> ttk.Window:
    """Builder function creating and returning the Surface Roughness GUI window."""
    if root is None:
        root = ttk.Window(
            title="Lee Research Lab — Surface Roughness Analysis",
            themename="darkly",
            size=(1400, 900),
            resizable=(True, True),
        )
    SurfaceRoughnessGUI(root)
    return root

def main():
    root = build_surface_roughness_gui()
    root.mainloop()

if __name__ == "__main__":
    main()