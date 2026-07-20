# ============================================================
# image_analysis_gui.py
# ============================================================
#!/usr/bin/env python3
"""
image_analysis_gui.py
━━━━━━━━━━━━━━━━━━━━━
ttkbootstrap GUI front-end for the LineWidthAnalyzer engine.
Two-column layout mirrors the existing G-Code Converter style.
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


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _set_status(label: ttk.Label, text: str, colour: str = "#888888") -> None:
    label.config(text=text, foreground=colour)


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


# ──────────────────────────────────────────────────────────────────────────────
#  GUI construction
# ──────────────────────────────────────────────────────────────────────────────

def build_image_analysis_gui() -> ttk.Window:

    root = ttk.Window(
        title="Lee Research Lab — Image Analysis",
        themename="darkly",
        size=(1400, 900),
        resizable=(True, True),
    )

    # ── Mutable state ─────────────────────────────────────────────────────────
    _selected_images: list = []          # file paths chosen by the user
    _last_results:    dict = {}          # filled after a successful analysis
    _analyzer_ref:    list = [None]      # LineWidthAnalyzer instance (reuse)

    # ── StringVars / other vars ───────────────────────────────────────────────
    outdir_var    = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "line_width_results"))
    scale_var     = tk.StringVar(value="1.0")
    thresh_var    = tk.StringVar(value="200")
    orient_var    = tk.StringVar(value="vertical")
    smooth_var    = tk.StringVar(value="0")
    overlap_var   = tk.StringVar(value="0")
    unit_var      = tk.StringVar(value="um")

    # forward references (mutable cells)
    _analyze_btn_cell  = [None]
    _save_btn_cell     = [None]
    _status_cell       = [None]
    _progress_cell     = [None]
    _fig_cell          = [None]
    _canvas_cell       = [None]
    _ax_qa_cell        = [None]
    _ax_plot_cell      = [None]
    _listbox_cell      = [None]

    # ── Main paned window ─────────────────────────────────────────────────────
    main_pane = ttk.Panedwindow(root, orient=HORIZONTAL)
    main_pane.pack(fill=BOTH, expand=YES)

    # ═════════════════════════════════════════════════════════════════════════
    #  LEFT PANEL
    # ═════════════════════════════════════════════════════════════════════════
    left_frame = ttk.Frame(main_pane, padding=(15, 15, 10, 15))

    ttk.Label(
        left_frame,
        text="Image Analysis",
        font=("Segoe UI", 16, "bold"),
        foreground="#eeeeff",
        anchor=CENTER,
    ).pack(fill=X, pady=(0, 6))
    ttk.Separator(left_frame, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

    # scrollable inner content
    left_canvas_widget = tk.Canvas(left_frame, highlightthickness=0, bg="#2b2b2b")
    left_scroll        = ttk.Scrollbar(left_frame, orient=VERTICAL,
                                       command=left_canvas_widget.yview)
    left_inner         = ttk.Frame(left_canvas_widget, padding=(0, 0, 4, 0))

    left_inner.bind(
        "<Configure>",
        lambda e: left_canvas_widget.configure(
            scrollregion=left_canvas_widget.bbox("all")
        ),
    )
    left_canvas_widget.create_window((0, 0), window=left_inner, anchor="nw")
    left_canvas_widget.configure(yscrollcommand=left_scroll.set)
    left_canvas_widget.pack(side=LEFT, fill=BOTH, expand=YES)
    left_scroll.pack(side=RIGHT, fill=Y)

    def _on_mw(event):
        left_canvas_widget.yview_scroll(int(-1 * (event.delta / 120)), "units")

    left_canvas_widget.bind(
        "<Enter>",
        lambda e: left_canvas_widget.bind_all("<MouseWheel>", _on_mw, add="+"),
    )
    left_canvas_widget.bind(
        "<Leave>",
        lambda e: left_canvas_widget.unbind_all("<MouseWheel>"),
    )

    def _configure_inner_width(event):
        items = left_canvas_widget.find_all()
        if items:
            left_canvas_widget.itemconfig(items[0], width=event.width)

    left_canvas_widget.bind("<Configure>", _configure_inner_width)

    # ── section / small label helpers ────────────────────────────────────────
    def sec(text):
        ttk.Label(
            left_inner, text=text,
            font=("Segoe UI", 10, "bold"),
            foreground="#cccccc", anchor=W,
        ).pack(fill=X, pady=(12, 3))

    def sml(text):
        ttk.Label(
            left_inner, text=text,
            font=("Segoe UI", 8),
            foreground="#888888", anchor=W,
        ).pack(fill=X, pady=(0, 2))

    # ── 1. Select Images ──────────────────────────────────────────────────────
    sec("Input Images")

    img_listbox = tk.Listbox(
        left_inner,
        height=5,
        bg="#1e1e2e",
        fg="#cccccc",
        selectbackground="#444466",
        font=("Segoe UI", 8),
        relief="flat",
        bd=0,
    )
    img_listbox.pack(fill=X, pady=(0, 4))
    _listbox_cell[0] = img_listbox

    def _browse_images():
        paths = filedialog.askopenfilenames(
            title="Select Image Files",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return
        _selected_images.clear()
        _selected_images.extend(os.path.normpath(p) for p in paths)
        img_listbox.delete(0, tk.END)
        for p in _selected_images:
            img_listbox.insert(tk.END, os.path.basename(p))
        _update_analyze_btn()
        _set_status(_status_cell[0], f"{len(_selected_images)} image(s) selected.", "#44dd88")

    ttk.Button(
        left_inner,
        text="📂  Select Images",
        bootstyle="primary-outline",
        command=_browse_images,
    ).pack(fill=X, pady=(0, 8))

    # ── 2. Output Folder ──────────────────────────────────────────────────────
    sec("Output Folder")

    outdir_entry = ttk.Entry(
        left_inner, textvariable=outdir_var,
        state="readonly", style="secondary.TEntry",
    )
    outdir_entry.pack(fill=X, pady=(0, 4))

    def _browse_outdir():
        d = filedialog.askdirectory(
            title="Select Output Folder",
            initialdir=outdir_var.get() or os.path.expanduser("~"),
        )
        if not d:
            return
        outdir_var.set(os.path.normpath(d))

    ttk.Button(
        left_inner,
        text="📁  Browse",
        bootstyle="primary-outline",
        command=_browse_outdir,
    ).pack(fill=X, pady=(0, 8))

    # ── 3. Parameters ─────────────────────────────────────────────────────────
    sec("Parameters")
    ttk.Separator(left_inner, orient=HORIZONTAL).pack(fill=X, pady=(0, 6))

    def _param_row(label_text, var, width=12):
        row = ttk.Frame(left_inner)
        row.pack(fill=X, pady=(0, 5))
        ttk.Label(
            row, text=label_text,
            font=("Segoe UI", 9), foreground="#aaaaaa", width=22, anchor=W,
        ).pack(side=LEFT)
        ttk.Entry(row, textvariable=var, width=width).pack(side=LEFT, fill=X, expand=YES)

    _param_row("Scale (µm / pixel):",  scale_var)
    _param_row("Threshold (0–255):",   thresh_var)
    _param_row("Smoothing window:",    smooth_var)
    _param_row("Overlap (px):",        overlap_var)

    # orientation combobox
    orient_row = ttk.Frame(left_inner)
    orient_row.pack(fill=X, pady=(0, 5))
    ttk.Label(
        orient_row, text="Orientation:",
        font=("Segoe UI", 9), foreground="#aaaaaa", width=22, anchor=W,
    ).pack(side=LEFT)
    ttk.Combobox(
        orient_row,
        textvariable=orient_var,
        values=["vertical", "horizontal"],
        state="readonly",
        width=12,
    ).pack(side=LEFT)

    # unit radiobuttons
    unit_row = ttk.Frame(left_inner)
    unit_row.pack(fill=X, pady=(0, 8))
    ttk.Label(
        unit_row, text="Output unit:",
        font=("Segoe UI", 9), foreground="#aaaaaa", width=22, anchor=W,
    ).pack(side=LEFT)
    ttk.Radiobutton(unit_row, text="µm", variable=unit_var,
                    value="um",  bootstyle="info").pack(side=LEFT, padx=(0, 8))
    ttk.Radiobutton(unit_row, text="mm", variable=unit_var,
                    value="mm",  bootstyle="info").pack(side=LEFT)

    ttk.Separator(left_inner, orient=HORIZONTAL).pack(fill=X, pady=(4, 10))

    # ── 4. Action buttons ─────────────────────────────────────────────────────
    analyze_btn = ttk.Button(
        left_inner,
        text="🔬  Analyze & Preview",
        bootstyle="success",
        state="disabled",
        padding=(10, 8),
    )
    analyze_btn.pack(fill=X, pady=(0, 6))
    _analyze_btn_cell[0] = analyze_btn

    save_btn = ttk.Button(
        left_inner,
        text="💾  Save Output",
        bootstyle="secondary",
        state="disabled",
        padding=(8, 6),
    )
    save_btn.pack(fill=X, pady=(0, 6))
    _save_btn_cell[0] = save_btn

    ttk.Button(
        left_inner,
        text="📂  Open Output Folder",
        bootstyle="secondary",
        padding=(8, 6),
        command=lambda: _open_folder(outdir_var.get()),
    ).pack(fill=X, pady=(0, 6))

    # ── 5. Progress bar ───────────────────────────────────────────────────────
    progress_bar = ttk.Progressbar(
        left_inner, bootstyle="info-striped", mode="indeterminate",
    )
    progress_bar.pack(fill=X, pady=(4, 4))
    _progress_cell[0] = progress_bar

    # ── 6. Status label ───────────────────────────────────────────────────────
    ttk.Separator(left_inner, orient=HORIZONTAL).pack(fill=X, pady=(6, 6))
    status_label = ttk.Label(
        left_inner,
        text="Ready — select images to begin.",
        foreground="#888888",
        font=("Segoe UI", 9),
        anchor=CENTER,
        wraplength=260,
    )
    status_label.pack(fill=X, pady=(0, 4))
    _status_cell[0] = status_label

    left_inner.update_idletasks()
    left_canvas_widget.configure(scrollregion=left_canvas_widget.bbox("all"))

    # ═════════════════════════════════════════════════════════════════════════
    #  RIGHT PANEL  —  Matplotlib figure with two subplots
    # ═════════════════════════════════════════════════════════════════════════
    right_frame  = ttk.Frame(main_pane, padding=(10, 15, 15, 15))
    canvas_frame = ttk.Frame(right_frame, relief="solid", borderwidth=1,
                             bootstyle="dark")
    canvas_frame.pack(fill=BOTH, expand=YES)

    fig = Figure(figsize=(10, 8), facecolor="#1e1e2e")
    ax_qa   = fig.add_subplot(2, 1, 1)
    ax_plot = fig.add_subplot(2, 1, 2)
    _ax_qa_cell[0]   = ax_qa
    _ax_plot_cell[0] = ax_plot
    _fig_cell[0]     = fig

    for ax in (ax_qa, ax_plot):
        ax.set_facecolor("#1e1e2e")
        ax.tick_params(colors="#555577")
        for sp in ax.spines.values():
            sp.set_edgecolor("#333355")

    ax_qa.set_title(
        "QA Overlay — load images and run analysis",
        color="#555577", fontsize=12,
    )
    ax_plot.set_title(
        "Width vs. Position — run analysis to populate",
        color="#555577", fontsize=12,
    )
    fig.tight_layout(pad=2.5)

    canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
    _canvas_cell[0] = canvas

    toolbar_frame = ttk.Frame(canvas_frame)
    toolbar_frame.pack(fill=X, side=BOTTOM)
    NavigationToolbar2Tk(canvas, toolbar_frame).update()

    # ── Add panels to pane ────────────────────────────────────────────────────
    main_pane.add(left_frame,  weight=1)
    main_pane.add(right_frame, weight=4)

    # ═════════════════════════════════════════════════════════════════════════
    #  LOGIC  —  button enable/disable
    # ═════════════════════════════════════════════════════════════════════════

    def _update_analyze_btn():
        analyze_btn.config(
            state="normal" if _selected_images else "disabled"
        )

    # ═════════════════════════════════════════════════════════════════════════
    #  LOGIC  —  Analyze & Preview
    # ═════════════════════════════════════════════════════════════════════════

    def _on_analyze():
        if not _selected_images:
            _set_status(_status_cell[0], "No images selected.", "red")
            return

        scale = _try_float(scale_var.get(), 1.0)
        if scale <= 0:
            _set_status(_status_cell[0], "Scale must be > 0.", "red")
            return

        analyze_btn.config(state="disabled")
        save_btn.config(state="disabled")
        _set_status(_status_cell[0], "Analyzing…", "#f0c040")
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

    def _analysis_worker(images, scale, threshold, orientation,
                         smooth_window, overlap_px, unit, outdir):
        try:
            from line_width_engine import LineWidthAnalyzer
            analyzer = LineWidthAnalyzer(
                images        = images,
                scale         = scale,
                threshold     = threshold,
                orientation   = orientation,
                smooth_window = smooth_window,
                overlap_px    = overlap_px,
                unit          = unit,
                outdir        = outdir,
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
        _set_status(
            _status_cell[0],
            f"Done.  Mean = {st['mean']:.3f} {analyzer.unit}  "
            f"CV = {st['cv_pct']:.2f}%  n = {st['n_points']} pts",
            "#44dd88",
        )

    def _analysis_error(msg):
        _progress_cell[0].stop()
        _progress_cell[0]["value"] = 0
        analyze_btn.config(state="normal")
        _set_status(_status_cell[0], f"Error: {msg}", "red")

    # ═════════════════════════════════════════════════════════════════════════
    #  LOGIC  —  update the two matplotlib subplots
    # ═════════════════════════════════════════════════════════════════════════

    def _update_plots(results: dict):
        import numpy as np
        from matplotlib.figure import Figure

        fig_obj   = _fig_cell[0]
        canvas_obj = _canvas_cell[0]

        # ── Top subplot: QA overlay ───────────────────────────────────────────
        ax_qa_obj = _ax_qa_cell[0]
        ax_qa_obj.clear()
        ax_qa_obj.set_facecolor("#1e1e2e")

        qa_img = results.get("qa_image")
        if qa_img is not None:
            ax_qa_obj.imshow(qa_img, aspect="auto")
            ax_qa_obj.set_title(
                "QA Overlay — red dots mark detected line edges",
                color="#eeeeff", fontsize=10,
            )
        else:
            ax_qa_obj.set_title("QA Overlay — no image available",
                                color="#555577", fontsize=10)
        ax_qa_obj.axis("off")

        # ── Bottom subplot: width vs position from engine figure ──────────────
        # We re-create the axes content from the engine's Figure rather than
        # embedding the engine Figure directly (keeps one canvas clean).
        ax_plot_obj = _ax_plot_cell[0]
        ax_plot_obj.clear()
        ax_plot_obj.set_facecolor("#1e1e2e")

        engine_fig: Figure = results.get("fig_plot")
        if engine_fig is not None:
            # Copy each artist from the engine subplot into our subplot
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
                    ax_plot_obj.scatter(
                        xs, ys, color=color, zorder=5,
                        label=coll.get_label(),
                    )
            for line in src_ax.get_lines():
                if line.get_linestyle() in ("--", ":") and len(line.get_ydata()) >= 1:
                    pass   # already copied above

            ax_plot_obj.set_xlabel(
                src_ax.get_xlabel(), color="#cccccc", fontsize=10)
            ax_plot_obj.set_ylabel(
                src_ax.get_ylabel(), color="#cccccc", fontsize=10)
            ax_plot_obj.set_title(
                src_ax.get_title(), color="#eeeeff", fontsize=10, fontweight="bold")
            ax_plot_obj.tick_params(colors="#cccccc")
            ax_plot_obj.grid(True, color="#444466", linewidth=0.4,
                             linestyle=":", alpha=0.7)
            for sp in ax_plot_obj.spines.values():
                sp.set_edgecolor("#666688")
            ax_plot_obj.legend(
                loc="upper right", fontsize=8,
                facecolor="#2a2a3e", edgecolor="#666688", labelcolor="#cccccc",
            )

        fig_obj.tight_layout(pad=2.5)
        canvas_obj.draw()

    # ═════════════════════════════════════════════════════════════════════════
    #  LOGIC  —  Save Output
    # ═════════════════════════════════════════════════════════════════════════

    def _on_save():
        if not _last_results:
            _set_status(_status_cell[0], "Nothing to save — run analysis first.", "red")
            return
        analyzer = _analyzer_ref[0]
        if analyzer is None:
            return

        save_btn.config(state="disabled")
        _set_status(_status_cell[0], "Saving…", "#f0c040")

        threading.Thread(
            target=_save_worker,
            args=(analyzer, dict(_last_results), outdir_var.get()),
            daemon=True,
        ).start()

    def _save_worker(analyzer, results, outdir):
        try:
            # Update engine's outdir in case user changed it
            analyzer.outdir = outdir
            saved = analyzer.save_results(results, outdir)
            root.after(0, _save_done, saved, outdir)
        except Exception as exc:
            root.after(0, _save_error, str(exc))

    def _save_done(saved: list, outdir: str):
        save_btn.config(state="normal")
        _set_status(
            _status_cell[0],
            f"Saved {len(saved)} file(s) to: {outdir}",
            "#44dd88",
        )
        messagebox.showinfo(
            "Saved",
            f"Output written to:\n{outdir}\n\n"
            + "\n".join(os.path.basename(p) for p in saved),
        )

    def _save_error(msg: str):
        save_btn.config(state="normal")
        _set_status(_status_cell[0], f"Save error: {msg}", "red")

    # ── Wire commands ─────────────────────────────────────────────────────────
    analyze_btn.config(command=_on_analyze)
    save_btn.config(command=_on_save)

    return root


# ──────────────────────────────────────────────────────────────────────────────
#  Stand-alone entry point (for testing this module directly)
# ──────────────────────────────────────────────────────────────────────────────

def main():
    build_image_analysis_gui().mainloop()


if __name__ == "__main__":
    main()