#!/usr/bin/env python3
"""
image_analysis_gui.py
━━━━━━━━━━━━━━━━━━━━━
Desktop GUI front-end for Line Width Image Analysis. Refactored to consume
ui_common components, shared calibration constants, and suite header/footers.
"""

import os
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

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

def _open_folder(path: str) -> None:
    if path and os.path.isdir(path):
        subprocess.Popen(f'explorer "{os.path.normpath(path)}"')

def _try_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return default

def _try_int(s: str, default: int = 0) -> int:
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return default

def build_image_analysis_gui(root: ttk.Window = None) -> ttk.Window:
    if root is None:
        root = ttk.Window(title="Lee Research Lab — Image Analysis")
        root.style = ttk.Style()
        root.style.theme_use("clam")  # Using built-in 'clam' theme as fallback
        root.geometry("1400x900")
        root.resizable(True, True)
        # Manually set dark colors
        root.configure(background="#1e1e2e")

    load_app_icon(root)

    # State Variables
    _selected_images = []
    _last_results = {}
    _analyzer_ref = [None]

    outdir_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "line_width_results"))
    scale_var = tk.StringVar(value="4x")
    thresh_var = tk.StringVar(value="200")
    orient_var = tk.StringVar(value="vertical")
    smooth_var = tk.StringVar(value="0")
    overlap_var = tk.StringVar(value="0")
    unit_var = tk.StringVar(value="mm")

    _btn_analyze_cell = [None]
    _btn_save_cell = [None]
    _status_cell = [None]
    _progress_cell = [None]
    _fig_cell = [None]
    _canvas_cell = [None]
    _ax_qa_cell = [None]
    _ax_plot_cell = [None]

    # App Header & Footer
    make_app_header(
        root,
        title="Line Width Image Analysis",
        subtitle="Automated Microscopic Line Profiler",
        on_return=root.destroy,
        on_about=lambda: show_about_dialog(root),
    )
    make_app_footer(root)

    # Main Panedwindow
    main_pane = ttk.Panedwindow(root, orient=HORIZONTAL)
    main_pane.pack(fill=BOTH, expand=YES)

    # Left Panel Container
    left_container = ttk.Frame(main_pane, padding=(10, 10, 5, 10))
    _, left_inner = make_scrollable_left_panel(left_container)

    # Right Panel Container
    right_frame = ttk.Frame(main_pane, padding=(5, 10, 10, 10))
    canvas_frame = ttk.Frame(right_frame, relief="solid", borderwidth=1)
    canvas_frame.pack(fill=BOTH, expand=YES)

    # Matplotlib Figure
    fig = Figure(figsize=(10, 8), facecolor="#1e1e2e")
    ax_qa = fig.add_subplot(2, 1, 1)
    ax_plot = fig.add_subplot(2, 1, 2)
    _ax_qa_cell[0] = ax_qa
    _ax_plot_cell[0] = ax_plot
    _fig_cell[0] = fig

    for ax in (ax_qa, ax_plot):
        ax.set_facecolor("#1e1e2e")
        ax.tick_params(colors="#cccccc")
        for sp in ax.spines.values():
            sp.set_edgecolor("#666688")

    ax_qa.set_title("QA Overlay — Load images and run analysis", color="#eeeeff", fontsize=10)
    ax_plot.set_title("Width vs. Position — Run analysis to populate", color="#eeeeff", fontsize=10)
    fig.tight_layout(pad=2.5)

    canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
    _canvas_cell[0] = canvas

    toolbar_frame = ttk.Frame(canvas_frame)
    toolbar_frame.pack(fill=X, side=BOTTOM)
    NavigationToolbar2Tk(canvas, toolbar_frame).update()

    main_pane.add(left_container, weight=1)
    main_pane.add(right_frame, weight=4)

    # --- Section 1: Input Images ---
    sec_img = make_titled_panel(left_inner, "📂 Input Images")
    img_listbox = tk.Listbox(
        sec_img, height=5, bg="#1e1e2e", fg="#cccccc",
        selectbackground="#444466", font=("Segoe UI", 8), relief="flat", bd=0,
    )
    img_listbox.pack(fill=X, pady=(0, 4))

    def _browse_images():
        paths = filedialog.askopenfilenames(
            title="Select Image Files",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"), ("All files", "*.*")],
        )
        if not paths:
            return
        _selected_images.clear()
        _selected_images.extend(os.path.normpath(p) for p in paths)
        img_listbox.delete(0, tk.END)
        for p in _selected_images:
            img_listbox.insert(tk.END, os.path.basename(p))
        _update_analyze_btn()
        set_status(_status_cell[0], f"{len(_selected_images)} image(s) selected.", "success")

    btn_img = ttk.Button(sec_img, text="📂 Select Images", bootstyle="primary-outline", command=_browse_images)
    btn_img.pack(fill=X)
    attach_tooltip(btn_img, "Choose microscope line scan image files")

    # --- Section 2: Output Folder ---
    sec_out = make_titled_panel(left_inner, "📁 Output Folder")
    out_entry = ttk.Entry(sec_out, textvariable=outdir_var, state="readonly", style="secondary.TEntry")
    out_entry.pack(fill=X, pady=(0, 4))

    def _browse_outdir():
        d = filedialog.askdirectory(title="Select Output Folder", initialdir=outdir_var.get())
        if d:
            outdir_var.set(os.path.normpath(d))

    btn_out = ttk.Button(sec_out, text="📁 Browse Output Folder", bootstyle="primary-outline", command=_browse_outdir)
    btn_out.pack(fill=X)
    attach_tooltip(btn_out, "Select directory where line profile CSVs and QA images will be saved")

    # --- Section 3: Parameters ---
    sec_param = make_titled_panel(left_inner, "⚙️ Analysis Parameters")

    # Objective Scale Combo
    s_row = ttk.Frame(sec_param)
    s_row.pack(fill=X, pady=(0, 5))
    small_label(s_row, "Objective Lens / Scale:")
    scale_combo = ttk.Combobox(s_row, textvariable=scale_var, values=["4x", "5x"], state="readonly", width=10)
    scale_combo.pack(side=RIGHT)
    attach_tooltip(scale_combo, "Select objective lens magnification (4x = 0.8075 µm/px, 5x = 0.6408 µm/px)")

    # Threshold
    t_row = ttk.Frame(sec_param)
    t_row.pack(fill=X, pady=(0, 5))
    small_label(t_row, "Threshold (0–255):")
    t_entry = ttk.Entry(t_row, textvariable=thresh_var, width=10)
    t_entry.pack(side=RIGHT)
    attach_tooltip(t_entry, "Grayscale cutoff intensity for line edge detection")

    # Smoothing Window
    sm_row = ttk.Frame(sec_param)
    sm_row.pack(fill=X, pady=(0, 5))
    small_label(sm_row, "Smoothing Window:")
    sm_entry = ttk.Entry(sm_row, textvariable=smooth_var, width=10)
    sm_entry.pack(side=RIGHT)
    attach_tooltip(sm_entry, "Rolling average window size in pixels (0 = disabled)")

    # Overlap
    ov_row = ttk.Frame(sec_param)
    ov_row.pack(fill=X, pady=(0, 5))
    small_label(ov_row, "Frame Overlap (px):")
    ov_entry = ttk.Entry(ov_row, textvariable=overlap_var, width=10)
    ov_entry.pack(side=RIGHT)
    attach_tooltip(ov_entry, "Known overlap in pixels between stitched sequential frames")

    # Orientation
    or_row = ttk.Frame(sec_param)
    or_row.pack(fill=X, pady=(0, 5))
    small_label(or_row, "Line Orientation:")
    or_combo = ttk.Combobox(or_row, textvariable=orient_var, values=["vertical", "horizontal"], state="readonly", width=10)
    or_combo.pack(side=RIGHT)
    attach_tooltip(or_combo, "Select line orientation in raw image frames")

    # Output Unit
    u_row = ttk.Frame(sec_param)
    u_row.pack(fill=X, pady=(0, 2))
    small_label(u_row, "Plot / CSV Unit:")
    u_frame = ttk.Frame(u_row)
    u_frame.pack(side=RIGHT)
    ttk.Radiobutton(u_frame, text="µm", variable=unit_var, value="um", bootstyle="info").pack(side=LEFT, padx=(0, 6))
    ttk.Radiobutton(u_frame, text="mm", variable=unit_var, value="mm", bootstyle="info").pack(side=LEFT)

    # --- Section 4: Action Execution ---
    sec_act = make_titled_panel(left_inner, "🔬 Execution")
    analyze_btn = make_action_button(sec_act, text="🔬 Analyze & Preview", bootstyle="success", state="disabled")
    _btn_analyze_cell[0] = analyze_btn
    attach_tooltip(analyze_btn, "Run edge detection and generate line width profile")

    save_btn = make_action_button(sec_act, text="💾 Save Output Files", bootstyle="secondary", state="disabled")
    _btn_save_cell[0] = save_btn
    attach_tooltip(save_btn, "Export CSV profiles and QA overlay images to disk")

    btn_open = make_action_button(sec_act, text="📂 Open Output Folder", bootstyle="secondary", command=lambda: _open_folder(outdir_var.get()))
    attach_tooltip(btn_open, "Open output directory in file explorer")

    _progress_cell[0] = make_progress_bar(left_inner)
    _status_cell[0] = make_status_label(left_inner, "Ready — select images to begin")

    def _update_analyze_btn():
        analyze_btn.config(state="normal" if _selected_images else "disabled")

    def _on_analyze():
        if not _selected_images:
            set_status(_status_cell[0], "No images selected.", "error")
            return

        scale = LENS_CALIBRATION_UM_PER_PX.get(scale_var.get(), 0.8075)

        analyze_btn.config(state="disabled")
        save_btn.config(state="disabled")
        set_status(_status_cell[0], "Analyzing line width profiles...", "warning")
        _progress_cell[0].start(12)

        threading.Thread(
            target=_analysis_worker,
            args=(
                list(_selected_images),
                scale,
                _try_int(thresh_var.get(), 200),
                orient_var.get(),
                _try_int(smooth_var.get(), 0),
                _try_float(overlap_var.get(), 0.0),
                unit_var.get(),
                outdir_var.get(),
            ),
            daemon=True,
        ).start()

    def _analysis_worker(images, scale, threshold, orientation, smooth_window, overlap_px, unit, outdir):
        try:
            from line_width_engine import LineWidthAnalyzer
            analyzer = LineWidthAnalyzer(
                images=images,
                scale=scale,
                threshold=threshold,
                orientation=orientation,
                smooth_window=smooth_window,
                overlap_px=overlap_px,
                unit=unit,
                outdir=outdir,
            )
            results = analyzer.analyze()
            root.after(0, _analysis_done, analyzer, results)
        except Exception as exc:
            root.after(0, _analysis_error, str(exc))

    def _analysis_done(analyzer, results):
        _progress_cell[0].stop()
        _progress_cell[0]["value"] = 0
        _analyzer_ref[0] = analyzer
        _last_results.clear()
        _last_results.update(results)

        _update_plots(results)

        analyze_btn.config(state="normal")
        save_btn.config(state="normal")
        st = results["stats"]
        set_status(
            _status_cell[0],
            f"Done. Mean = {st['mean']:.3f} {analyzer.unit} | CV = {st['cv_pct']:.2f}% | n = {st['n_points']} pts",
            "success",
        )

    def _analysis_error(msg):
        _progress_cell[0].stop()
        _progress_cell[0]["value"] = 0
        analyze_btn.config(state="normal")
        set_status(_status_cell[0], f"Error: {msg}", "error")

    def _update_plots(results: dict):
        ax_qa_obj = _ax_qa_cell[0]
        ax_qa_obj.clear()
        ax_qa_obj.set_facecolor("#1e1e2e")

        qa_img = results.get("qa_image")
        if qa_img is not None:
            ax_qa_obj.imshow(qa_img, aspect="auto")
            ax_qa_obj.set_title("QA Overlay — Red dots mark detected line edges", color="#eeeeff", fontsize=10)
        else:
            ax_qa_obj.set_title("QA Overlay — No image available", color="#888888", fontsize=10)
        ax_qa_obj.axis("off")

        ax_plot_obj = _ax_plot_cell[0]
        ax_plot_obj.clear()
        ax_plot_obj.set_facecolor("#1e1e2e")

        engine_fig = results.get("fig_plot")
        if engine_fig is not None:
            src_ax = engine_fig.axes[0]
            for line in src_ax.get_lines():
                ax_plot_obj.plot(
                    line.get_xdata(), line.get_ydata(),
                    color=line.get_color(),
                    linewidth=line.get_linewidth(),
                    linestyle=line.get_linestyle(),
                    alpha=line.get_alpha() if line.get_alpha() is not None else 1.0,
                    label=line.get_label(),
                    zorder=line.get_zorder(),
                )
            for coll in src_ax.collections:
                offsets = coll.get_offsets()
                if len(offsets):
                    xs, ys = offsets[:, 0], offsets[:, 1]
                    fc = coll.get_facecolors()
                    color = fc[0] if len(fc) else "white"
                    ax_plot_obj.scatter(xs, ys, color=color, zorder=5, label=coll.get_label())

            ax_plot_obj.set_xlabel(src_ax.get_xlabel(), color="#cccccc", fontsize=10)
            ax_plot_obj.set_ylabel(src_ax.get_ylabel(), color="#cccccc", fontsize=10)
            ax_plot_obj.set_title(src_ax.get_title(), color="#eeeeff", fontsize=10, fontweight="bold")
            ax_plot_obj.tick_params(colors="#cccccc")
            ax_plot_obj.grid(True, color="#444466", linewidth=0.4, linestyle=":", alpha=0.7)
            for sp in ax_plot_obj.spines.values():
                sp.set_edgecolor("#666688")
            ax_plot_obj.legend(loc="upper right", fontsize=8, facecolor="#2a2a3e", edgecolor="#666688", labelcolor="#cccccc")

        _fig_cell[0].tight_layout(pad=2.5)
        _canvas_cell[0].draw()

    def _on_save():
        if not _last_results or _analyzer_ref[0] is None:
            return
        save_btn.config(state="disabled")
        set_status(_status_cell[0], "Saving results to disk...", "warning")

        threading.Thread(
            target=_save_worker,
            args=(_analyzer_ref[0], dict(_last_results), outdir_var.get()),
            daemon=True,
        ).start()

    def _save_worker(analyzer, results, outdir):
        try:
            analyzer.outdir = outdir
            saved = analyzer.save_results(results, outdir)
            root.after(0, _save_done, saved, outdir)
        except Exception as exc:
            root.after(0, _save_error, str(exc))

    def _save_done(saved: list, outdir: str):
        save_btn.config(state="normal")
        set_status(_status_cell[0], f"Saved {len(saved)} file(s) to: {outdir}", "success")
        messagebox.showinfo("Saved", f"Output successfully written to:\n{outdir}\n\n" + "\n".join(os.path.basename(p) for p in saved))

    def _save_error(msg: str):
        save_btn.config(state="normal")
        set_status(_status_cell[0], f"Save error: {msg}", "error")

    analyze_btn.config(command=_on_analyze)
    save_btn.config(command=_on_save)

    return root

def main():
    build_image_analysis_gui().mainloop()

if __name__ == "__main__":
    main()
