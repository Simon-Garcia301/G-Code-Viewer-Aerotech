import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
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

# import the analysis engine
from surface_roughness_engine import SurfaceRoughnessAnalyzer

# ---------- helper widgets (matching image_analysis_gui.py style) ----------
def sec(parent, text, **kwargs):
    """Return a ttk.LabelFrame with consistent dark styling."""
    return ttk.LabelFrame(parent, text=text, bootstyle="primary", **kwargs)

def sml(parent, text, **kwargs):
    """Return a ttk.Label with a small font."""
    return ttk.Label(parent, text=text, font=("Segoe UI", 9), **kwargs)

# ---------------------------------------------------------------------------
class SurfaceRoughnessGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Surface Roughness Analysis")
        self.root.geometry("1400x900")

        # ----- state variables -------------------------------------------------
        self._images = []                    # list of file paths
        self._current_image_index = -1
        self._roi = None                     # (x0, y0, x1, y1)
        self._mask_polygons = []             # list of list of (x, y) tuples
        self._glare_enabled = tk.BooleanVar(value=False)
        self._glare_value = tk.StringVar(value="200")
        self._analyzer = None
        self._last_results = None
        self._outdir = tk.StringVar(value=os.getcwd())

        # artists for visual patches (so we can remove them)
        self._roi_patch = None
        self._mask_patches = []

        # selectors
        self._roi_selector = None
        self._poly_selector = None

        # ----- figure & canvas ------------------------------------------------
        self._fig, (self._ax_qa, self._ax_hist) = plt.subplots(
            2, 1, figsize=(8, 8), constrained_layout=True
        )
        self._ax_qa.set_title("Current Image (ROI & Masks)")
        self._ax_qa.axis("off")   # we'll set ticks off later
        self._ax_hist.set_title("Histogram of Valid Intensities")
        self._ax_hist.set_xlabel("Grayscale intensity")
        self._ax_hist.set_ylabel("Frequency")

        # ----- build GUI ------------------------------------------------------
        self._build_ui()

    # ======================================================================
    # UI construction
    # ======================================================================
    def _build_ui(self):
        # main paned window
        pw = ttk.Panedwindow(self.root, orient=HORIZONTAL, bootstyle="dark")
        pw.pack(fill=BOTH, expand=True)

        # left panel (scrollable)
        left_frame = ttk.Frame(pw)
        pw.add(left_frame, weight=1)

        canvas = tk.Canvas(left_frame, bg="#2b2b2b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_frame, orient=VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # right panel (plot + toolbar)
        right_frame = ttk.Frame(pw)
        pw.add(right_frame, weight=4)

        plot_frame = ttk.Frame(right_frame)
        plot_frame.pack(fill=BOTH, expand=True)

        self._canvas = FigureCanvasTkAgg(self._fig, master=plot_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(side=TOP, fill=BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(self._canvas, plot_frame)
        toolbar.update()
        self._canvas.get_tk_widget().pack(side=TOP, fill=BOTH, expand=True)

        # ---------- populate left panel sections (inside scrollable_frame) ---------
        # Title
        ttk.Label(scrollable_frame, text="🔬 Surface Roughness Analysis",
                  font=("Segoe UI", 14, "bold"), bootstyle="inverse-primary").pack(pady=10)

        # Image Selection
        img_sec = sec(scrollable_frame, "📂 Image Selection")
        img_sec.pack(fill=X, padx=10, pady=5)

        self._lb_images = tk.Listbox(img_sec, height=10, bg="#3c3c3c", fg="white",
                                     selectbackground="#0078d4")
        self._lb_images.pack(fill=X, padx=5, pady=5)
        self._lb_images.bind("<<ListboxSelect>>", self._on_image_select)

        btn_frame = ttk.Frame(img_sec)
        btn_frame.pack(fill=X, padx=5, pady=5)
        ttk.Button(btn_frame, text="➕ Select Images", bootstyle="primary-outline",
                   command=self._select_images).pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑 Clear", bootstyle="secondary",
                   command=self._clear_images).pack(side=LEFT, padx=2)

        # Output Folder
        out_sec = sec(scrollable_frame, "📁 Output Folder")
        out_sec.pack(fill=X, padx=10, pady=5)
        out_inner = ttk.Frame(out_sec)
        out_inner.pack(fill=X, padx=5, pady=5)
        ttk.Entry(out_inner, textvariable=self._outdir, bootstyle="dark").pack(side=LEFT, expand=True, fill=X, padx=(0,5))
        ttk.Button(out_inner, text="📁 Browse", bootstyle="secondary",
                   command=self._browse_outdir).pack(side=RIGHT)

        # ROI & Mask Controls
        roi_sec = sec(scrollable_frame, "📐 ROI & Masks")
        roi_sec.pack(fill=X, padx=10, pady=5)
        ttk.Button(roi_sec, text="📏 Draw ROI", bootstyle="primary-outline",
                   command=self._toggle_roi_selector).pack(fill=X, padx=5, pady=2)
        self._roi_label = ttk.Label(roi_sec, text="ROI: not set", bootstyle="inverse-info")
        self._roi_label.pack(padx=5, pady=2)

        ttk.Separator(roi_sec, orient=HORIZONTAL).pack(fill=X, padx=5, pady=5)

        ttk.Button(roi_sec, text="🖍 Add Mask Polygon", bootstyle="primary-outline",
                   command=self._toggle_poly_selector).pack(fill=X, padx=5, pady=2)
        ttk.Button(roi_sec, text="🗑 Clear All Masks", bootstyle="secondary",
                   command=self._clear_masks).pack(fill=X, padx=5, pady=2)

        # Glare Threshold
        glare_sec = sec(scrollable_frame, "💡 Glare Threshold")
        glare_sec.pack(fill=X, padx=10, pady=5)
        cbtn = ttk.Checkbutton(glare_sec, text="Enable glare threshold",
                               variable=self._glare_enabled,
                               bootstyle="primary-round-toggle",
                               command=self._on_glare_toggle)
        cbtn.pack(anchor=W, padx=5, pady=2)
        ttk.Label(glare_sec, text="Threshold (0‑255):").pack(anchor=W, padx=5)
        self._glare_entry = ttk.Entry(glare_sec, textvariable=self._glare_value,
                                      bootstyle="dark", state=DISABLED, width=10)
        self._glare_entry.pack(anchor=W, padx=5, pady=2)
        self._glare_enabled.trace_add("write", lambda *a: self._on_glare_toggle())

        # Action Buttons
        action_sec = sec(scrollable_frame, "⚙️ Actions")
        action_sec.pack(fill=X, padx=10, pady=5)
        self._btn_compute = ttk.Button(action_sec, text="🚀 Compute CV%",
                                       bootstyle="success",
                                       command=self._on_compute_cv)
        self._btn_compute.pack(fill=X, padx=5, pady=2)
        self._btn_save = ttk.Button(action_sec, text="💾 Save Output",
                                    bootstyle="primary-outline",
                                    command=self._on_save_output,
                                    state=DISABLED)
        self._btn_save.pack(fill=X, padx=5, pady=2)

        # Progress Bar
        self._progress = ttk.Progressbar(scrollable_frame, mode="indeterminate",
                                         bootstyle="info-striped")
        self._progress.pack(fill=X, padx=10, pady=5)

        # Status
        self._status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(scrollable_frame, textvariable=self._status_var,
                                 bootstyle="inverse-secondary")
        status_label.pack(padx=10, pady=5)

    # ======================================================================
    # callback / state methods
    # ======================================================================
    def _set_status(self, msg):
        self._status_var.set(msg)
        self.root.update_idletasks()

    def _try_int(self, s, default=0):
        """Validate integer, return default on error."""
        try:
            return int(s)
        except ValueError:
            return default

    # --- image handling ----------------------------------------------------
    def _select_images(self):
        files = filedialog.askopenfilenames(
            title="Select microscope images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp")]
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

    def _on_image_select(self, event):
        sel = self._lb_images.curselection()
        if sel:
            idx = sel[0]
            self._current_image_index = idx
            self._load_and_display_image(idx)

    def _clear_images(self):
        self._images = []
        self._lb_images.delete(0, tk.END)
        self._current_image_index = -1
        self._ax_qa.clear()
        self._ax_qa.set_title("Current Image (ROI & Masks)")
        self._ax_qa.axis("off")
        self._canvas.draw()

    def _load_and_display_image(self, index):
        """Load the image at index, display on ax_qa, redraw ROI and masks."""
        if index < 0 or index >= len(self._images):
            return
        path = self._images[index]
        img = cv2.imread(path)
        if img is None:
            self._set_status(f"Error loading {path}")
            return
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self._current_gray = gray

        self._ax_qa.clear()
        self._ax_qa.imshow(gray, cmap="gray", origin="upper")
        self._ax_qa.set_title(os.path.basename(path))
        self._ax_qa.axis("off")

        # redraw ROI if set
        if self._roi is not None:
            x0, y0, x1, y1 = self._roi
            width = x1 - x0
            height = y1 - y0
            roi_rect = Rectangle((x0, y0), width, height,
                                 linewidth=2, edgecolor="lime", facecolor="none")
            self._ax_qa.add_patch(roi_rect)
            self._roi_patch = roi_rect

        # redraw masks
        self._mask_patches = []
        for poly in self._mask_polygons:
            mp = Polygon(poly, closed=True, facecolor="red", edgecolor="red", alpha=0.3)
            self._ax_qa.add_patch(mp)
            self._mask_patches.append(mp)

        self._ax_qa.relim()
        self._ax_qa.autoscale_view()
        self._canvas.draw()

    # --- ROI selector ------------------------------------------------------
    def _toggle_roi_selector(self):
        if self._roi_selector is not None and self._roi_selector.active:
            # deactivate current selector
            self._roi_selector.set_active(False)
            self._roi_selector = None
            self._set_status("ROI selector deactivated")
            return

        if self._current_image_index < 0:
            messagebox.showwarning("No image", "Please load an image first.")
            return

        # start a new RectangleSelector
        self._set_status("Draw ROI on the image (click and drag)...")
        self._roi_selector = RectangleSelector(
            self._ax_qa, self._on_roi_selected,
            useblit=True,
            button=[1],  # left mouse button
            minspanx=5, minspany=5,
            spancoords='data',
            interactive=True
        )
        self._roi_selector.set_active(True)

    def _on_roi_selected(self, eclick, erelease):
        """Callback when rectangle is finalized."""
        x0, y0 = eclick.xdata, eclick.ydata
        x1, y1 = erelease.xdata, erelease.ydata
        if None in (x0, y0, x1, y1):
            return
        # sort to ensure (x0,y0) top-left, (x1,y1) bottom-right
        x0, x1 = sorted([int(round(x0)), int(round(x1))])
        y0, y1 = sorted([int(round(y0)), int(round(y1))])
        self._roi = (x0, y0, x1, y1)
        self._roi_selector.set_active(False)
        self._roi_selector = None
        self._roi_label.config(text=f"ROI: ({x0},{y0}) -> ({x1},{y1})")
        self._load_and_display_image(self._current_image_index)  # refresh with ROI patch
        self._set_status(f"ROI set: {self._roi}")

    # --- mask polygon selector ---------------------------------------------
    def _toggle_poly_selector(self):
        if self._poly_selector is not None and self._poly_selector.active:
            self._poly_selector.set_active(False)
            self._poly_selector = None
            self._set_status("Polygon selector deactivated")
            return

        if self._current_image_index < 0:
            messagebox.showwarning("No image", "Please load an image first.")
            return

        self._set_status("Click to add polygon vertices, double‑click to finish...")
        self._poly_selector = PolygonSelector(
            self._ax_qa, self._on_polygon_complete,
            useblit=True,
            lineprops=dict(color='red', linestyle='-', linewidth=2),
            markerprops=dict(marker='o', markersize=5, color='red')
        )
        self._poly_selector.set_active(True)

    def _on_polygon_complete(self, vertices):
        """Called when the user finishes a polygon (list of (x,y) arrays)."""
        if vertices is None or len(vertices) < 3:
            return
        # vertices is a list of (x,y) in image coordinates
        poly = [(int(round(v[0])), int(round(v[1]))) for v in vertices]
        self._mask_polygons.append(poly)
        # deactivate selector
        if self._poly_selector is not None:
            self._poly_selector.set_active(False)
            self._poly_selector = None
        # redraw image to show new polygon
        self._load_and_display_image(self._current_image_index)
        self._set_status(f"Mask polygon {len(self._mask_polygons)} added")

    def _clear_masks(self):
        self._mask_polygons.clear()
        self._mask_patches.clear()
        if self._current_image_index >= 0:
            self._load_and_display_image(self._current_image_index)
        self._set_status("All masks cleared")

    # --- glare threshold ---------------------------------------------------
    def _on_glare_toggle(self, *args):
        if self._glare_enabled.get():
            self._glare_entry.configure(state=NORMAL)
        else:
            self._glare_entry.configure(state=DISABLED)

    # --- output folder browse ----------------------------------------------
    def _browse_outdir(self):
        dirname = filedialog.askdirectory(title="Select Output Folder")
        if dirname:
            self._outdir.set(dirname)

    # --- compute CV% (background thread) -----------------------------------
    def _on_compute_cv(self):
        if not self._images:
            messagebox.showwarning("No images", "Please select images first.")
            return
        if self._roi is None:
            messagebox.showwarning("No ROI", "Please draw an ROI rectangle first.")
            return

        # disable button, start progress
        self._btn_compute.configure(state=DISABLED)
        self._progress.start(10)
        self._set_status("Processing images...")

        # get glare threshold
        glare_threshold = None
        if self._glare_enabled.get():
            glare_threshold = self._try_int(self._glare_value.get(), default=200)

        thread = threading.Thread(
            target=self._compute_thread,
            args=(self._images.copy(), self._roi, self._mask_polygons.copy(),
                  glare_threshold, self._outdir.get()),
            daemon=True
        )
        thread.start()

    def _compute_thread(self, images, rect, masks, glare_threshold, outdir):
        try:
            analyzer = SurfaceRoughnessAnalyzer(images, rect, masks,
                                                glare_threshold, outdir)
            results = analyzer.analyze()
            self.root.after(0, self._on_analysis_done, analyzer, results)
        except Exception as e:
            self.root.after(0, self._on_analysis_error, str(e))

    def _on_analysis_done(self, analyzer, results):
        self._analyzer = analyzer
        self._last_results = results
        self._progress.stop()
        self._btn_compute.configure(state=NORMAL)
        self._btn_save.configure(state=NORMAL)

        # update histogram subplot
        self._ax_hist.clear()
        if "histogram_data" in results and len(results["histogram_data"]) > 0:
            self._ax_hist.hist(results["histogram_data"], bins=50,
                               color="skyblue", edgecolor="black", alpha=0.7)
        self._ax_hist.set_title("Histogram of Valid Intensities")
        self._ax_hist.set_xlabel("Grayscale intensity")
        self._ax_hist.set_ylabel("Frequency")
        self._canvas.draw()

        # show summary in a messagebox
        agg = results.get("aggregate", {})
        n = agg.get("n_processed", 0)
        mean_cv = agg.get("overall_mean_cv", 0)
        std_cv = agg.get("overall_std_cv", 0)
        msg = (f"Analysis completed.\n"
               f"Images processed: {n}\n"
               f"Overall mean CV%: {self._fmt(mean_cv)}\n"
               f"Overall std CV%: {self._fmt(std_cv)}")
        messagebox.showinfo("Results", msg)
        self._set_status("Analysis complete")

    def _on_analysis_error(self, errmsg):
        self._progress.stop()
        self._btn_compute.configure(state=NORMAL)
        messagebox.showerror("Error", f"Analysis failed:\n{errmsg}")
        self._set_status("Error during analysis")

    def _fmt(self, val):
        return SurfaceRoughnessAnalyzer._format_3sf(val)

    # --- save output (background thread) -----------------------------------
    def _on_save_output(self):
        if self._analyzer is None:
            messagebox.showwarning("No results", "Run analysis first.")
            return
        self._btn_save.configure(state=DISABLED)
        self._progress.start(10)
        self._set_status("Saving results...")
        thread = threading.Thread(target=self._save_thread, daemon=True)
        thread.start()

    def _save_thread(self):
        try:
            saved = self._analyzer.save_results(outdir=self._outdir.get())
            self.root.after(0, self._on_save_done, saved)
        except Exception as e:
            self.root.after(0, self._on_analysis_error, str(e))

    def _on_save_done(self, paths):
        self._progress.stop()
        self._btn_save.configure(state=NORMAL)
        messagebox.showinfo("Saved", f"Results written to:\n{paths[0]}")
        self._set_status("Output saved")

# ============================================================================
def build_surface_roughness_gui():
    root = ttk.Window(themename="darkly")
    app = SurfaceRoughnessGUI(root)
    return root

def main():
    root = build_surface_roughness_gui()
    root.mainloop()

if __name__ == "__main__":
    main()
