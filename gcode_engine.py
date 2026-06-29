"""
gcode_engine.py
━━━━━━━━━━━━━━━
Core G-code parsing, arc geometry, and PNG rendering engine.

This module is intentionally import-free of any GUI or CLI code.
It is imported by both:
  - main.py                (CLI entry point)
  - gcode_converter_gui.py (GUI front-end)

Public API
----------
  convert_gcode_to_png(gcode_path: str, output_folder: str) -> str
      The single function the GUI calls. Returns "SUCCESS" or an error string.

Internal pipeline (also importable individually for testing):
  preprocess(raw_text)             -> list[str]
  parse_gcode(lines)               -> (travel_segs, print_segs, z_anns, state)
  visualise(travel, print, z, ...) -> None  (saves PNG, no plt.show())
"""

import os
import re
import math
import textwrap

import numpy as np

# ── Matplotlib: force the non-interactive PNG backend BEFORE pyplot is imported.
# This is mandatory when running inside a GUI app or a --windowed .exe, because
# the default backend tries to create its own display window, which either
# crashes or deadlocks when a tkinter window already owns the event loop.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

ARC_SEGMENTS = 72       # linear segments used to approximate one arc
INCH_TO_MM   = 25.4     # 1 inch = 25.4 mm

# Matches a G-code word such as "X-12.5", "F100", "R0.25", "$Var"
_WORD_RE = re.compile(
    r'(?P<letter>[A-Z])'
    r'\s*'
    r'(?P<value>'
    r'[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?'  # numeric literal
    r'|'
    r'[&$][A-Za-z_]\w*'                   # variable reference with $ or &
    r')',
    re.IGNORECASE,
)


# Matches a full variable declaration: "var $NAME = VALUE"
_VAR_DECL_RE = re.compile(
    r'var\s+'                              # keyword
    r'[&$]?(?P<name>[A-Za-z_]\w*)'         # optional $ or &, then name
    r'(?:\s+as\s+\w+)?'                    # optional "as <type>"
    r'\s*=\s*'                             # optional whitespace around =
    r'(?P<value>[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)',
    re.IGNORECASE,
)


# Function calls that have no effect on the tool path — silently skipped
_NOOP_RE = re.compile(
    r'^(PositionOffsetSet|DigitalOutputSet|Dwell|Enable|Disable|Home)\s*\(',
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
#  MACHINE STATE
# ══════════════════════════════════════════════════════════════════════════════

class MachineState:
    """
    Holds every modal setting that persists between G-code lines:
    positioning mode, units, feedrate mode, current position, and variables.
    """

    def __init__(self):
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0

        self.absolute:     bool  = True   # G90=True / G91=False
        self.unit_mm:      bool  = True   # G71=True / G70=False
        self.feed_per_sec: bool  = True   # G76=True / G75=False
        self.feedrate:     float = 1.0    # stored in mm/s always
        self.motion_mode:  int   = 0      # last seen G0/1/2/3

        self.variables: dict = {}         # $NAME -> float

    # ── unit helpers ──────────────────────────────────────────────────────────

    def to_mm(self, value: float) -> float:
        """Convert raw input value to mm using the current unit setting."""
        return value if self.unit_mm else value * INCH_TO_MM

    def resolve_target(self, axis: str, raw: float) -> float:
        """
        Return the absolute mm position for *axis* given the raw G-code value.
        Handles G90 (absolute) and G91 (incremental) transparently.
        """
        mm = self.to_mm(raw)
        return mm if self.absolute else getattr(self, axis) + mm

   def resolve_variable(self, token: str) -> float:
    if token.startswith('$') or token.startswith('&'):
        name = token[1:]
        if name not in self.variables:
            raise ValueError(
                f"Variable '{token}' used before declaration."
            )
        return self.variables[name]
    return float(token)



# ══════════════════════════════════════════════════════════════════════════════
#  ARC GEOMETRY
# ══════════════════════════════════════════════════════════════════════════════

def arc_points_ij(
    sx: float, sy: float,
    ex: float, ey: float,
    i:  float, j:  float,
    clockwise: bool,
    n_seg: int = ARC_SEGMENTS,
) -> list:
    """
    Interpolate a circular arc defined by the IJ (center-offset) method.
    Returns a list of (x, y) tuples from start to end.
    """
    cx, cy = sx + i, sy + j
    radius  = math.hypot(i, j)
    if radius < 1e-12:
        return [(sx, sy), (ex, ey)]

    theta_start = math.atan2(sy - cy, sx - cx)
    theta_end   = math.atan2(ey - cy, ex - cx)

    if clockwise:
        sweep = theta_end - theta_start
        if sweep > 0:
            sweep -= 2 * math.pi
    else:
        sweep = theta_end - theta_start
        if sweep < 0:
            sweep += 2 * math.pi

    # Full-circle: start == end means 360°, not 0°
    if abs(ex - sx) < 1e-9 and abs(ey - sy) < 1e-9:
        sweep = -2 * math.pi if clockwise else 2 * math.pi

    return [
        (cx + radius * math.cos(theta_start + k / n_seg * sweep),
         cy + radius * math.sin(theta_start + k / n_seg * sweep))
        for k in range(n_seg + 1)
    ]


def arc_points_r(
    sx: float, sy: float,
    ex: float, ey: float,
    radius: float,
    clockwise: bool,
    n_seg: int = ARC_SEGMENTS,
) -> list:
    """
    Interpolate a circular arc defined by the R (radius) method.
    R > 0 → short arc (≤ 180°); R < 0 → long arc (> 180°).
    Delegates to arc_points_ij() after computing the center.
    """
    r_abs      = abs(radius)
    mx, my     = (sx + ex) / 2, (sy + ey) / 2
    d          = math.hypot(ex - sx, ey - sy)
    half_chord = d / 2

    if half_chord > r_abs + 1e-9:
        r_abs = half_chord + 1e-9   # clamp to minimum viable radius

    h = math.sqrt(max(0.0, r_abs ** 2 - half_chord ** 2))

    if d < 1e-12:
        return [(sx, sy), (ex, ey)]

    perp_x, perp_y = -(ey - sy) / d, (ex - sx) / d
    c1x, c1y = mx + h * perp_x, my + h * perp_y
    c2x, c2y = mx - h * perp_x, my - h * perp_y

    def cross(ccx, ccy):
        return (ex - sx) * (ccy - sy) - (ey - sy) * (ccx - sx)

    use_c1 = (cross(c1x, c1y) < 0) == clockwise if radius > 0 \
              else (cross(c1x, c1y) > 0) == clockwise

    cx, cy = (c1x, c1y) if use_c1 else (c2x, c2y)
    return arc_points_ij(sx, sy, ex, ey, cx - sx, cy - sy, clockwise, n_seg)


# ══════════════════════════════════════════════════════════════════════════════
#  PRE-PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def preprocess(raw_text: str) -> list:
    """
    Strip // comments and blank lines.
    Returns a list of cleaned non-empty line strings ready for tokenisation.
    """
    lines = []
    for raw in raw_text.splitlines():
        pos = raw.find('//')
        if pos != -1:
            raw = raw[:pos]
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


# ══════════════════════════════════════════════════════════════════════════════
#  TOKENISER
# ══════════════════════════════════════════════════════════════════════════════

def tokenise_line(line: str, state: MachineState) -> dict:
    """
    Parse one G-code line into a {letter: value} dictionary.
    G-code numbers are stored as int; all other values as float.
    Variable references ($NAME) are resolved against state.variables.
    """
    words = {}
    for m in _WORD_RE.finditer(line):
        letter = m.group('letter').upper()
        raw    = m.group('value')
        value  = state.resolve_variable(raw)

        if letter == 'G':
            words[letter] = int(value)
            words.setdefault('G_list', []).append(int(value))
        elif letter == 'M':
            words[letter] = int(value)
        else:
            words[letter] = value
    return words


# ══════════════════════════════════════════════════════════════════════════════
#  PARSER / INTERPRETER
# ══════════════════════════════════════════════════════════════════════════════

def parse_gcode(lines: list) -> tuple:
    """
    Walk the preprocessed G-code lines and produce path segment lists.

    Returns
    -------
    travel_segments : list of polylines for G0 rapid moves
    print_segments  : list of polylines for G1/G2/G3 feed moves
    z_annotations   : list of (x, y, z, label) tuples for Z-change markers
    state           : final MachineState (contains unit_mm, variables, etc.)
    """
    state = MachineState()

    travel_segments: list = []
    print_segments:  list = []
    z_annotations:   list = []

    _seg_type: list = [None]   # mutable cell: 'travel' | 'print' | None
    _seg_pts:  list = []

    # ── segment helpers ───────────────────────────────────────────────────────

    def flush():
        if len(_seg_pts) >= 2:
            target = travel_segments if _seg_type[0] == 'travel' else print_segments
            target.append(list(_seg_pts))
        _seg_pts.clear()
        _seg_type[0] = None

    def add_point(x: float, y: float, kind: str):
        if _seg_type[0] != kind:
            last = _seg_pts[-1] if _seg_pts else None
            flush()
            _seg_type[0] = kind
            if last:
                _seg_pts.append(last)   # overlap for visual continuity
        _seg_pts.append((x, y))

    # ── main loop ─────────────────────────────────────────────────────────────

    for lineno, line in enumerate(lines, start=1):

        if _NOOP_RE.match(line):
            continue

        var_m = _VAR_DECL_RE.match(line)
        if var_m:
            state.variables[var_m.group('name')] = float(var_m.group('value'))
            continue

        try:
            words = tokenise_line(line, state)
        except ValueError as exc:
            raise ValueError(f"Line {lineno}: {exc}\n  → {line!r}") from exc

        if not words:
            continue

        g_list = words.get('G_list', [])

        # Apply modal-only G-codes (unit/mode switches) immediately
        for g in g_list:
            if   g == 70: state.unit_mm      = False
            elif g == 71: state.unit_mm      = True
            elif g == 75: state.feed_per_sec = False
            elif g == 76: state.feed_per_sec = True
            elif g == 90: state.absolute     = True
            elif g == 91: state.absolute     = False

        # Update feedrate if F word present
        if 'F' in words:
            f_mm = state.to_mm(words['F'])
            state.feedrate = f_mm if state.feed_per_sec else f_mm / 60.0

        # Determine which motion command governs this line
        motion_g = next((g for g in g_list if g in (0, 1, 2, 3)), None)
        if motion_g is None and any(k in words for k in ('X', 'Y', 'Z')):
            motion_g = state.motion_mode    # inherit modal mode
        if motion_g is None:
            continue                        # purely modal line, nothing to draw

        state.motion_mode = motion_g

        # Resolve target coordinates
        px, py, pz = state.x, state.y, state.z
        nx = state.resolve_target('x', words['X']) if 'X' in words else px
        ny = state.resolve_target('y', words['Y']) if 'Y' in words else py
        nz = state.resolve_target('z', words['Z']) if 'Z' in words else pz

        if abs(nz - pz) > 1e-9:
            z_annotations.append(((px + nx) / 2, (py + ny) / 2, nz, f"Z={nz:.3f}"))

        # Execute motion
        if motion_g == 0:
            add_point(px, py, 'travel')
            add_point(nx, ny, 'travel')

        elif motion_g == 1:
            add_point(px, py, 'print')
            add_point(nx, ny, 'print')

        elif motion_g in (2, 3):
            cw = (motion_g == 2)
            if 'R' in words:
                pts = arc_points_r(px, py, nx, ny, state.to_mm(words['R']), cw)
            elif 'I' in words or 'J' in words:
                pts = arc_points_ij(
                    px, py, nx, ny,
                    state.to_mm(words.get('I', 0.0)),
                    state.to_mm(words.get('J', 0.0)),
                    cw,
                )
            else:
                pts = [(px, py), (nx, ny)]
            for pt in pts:
                add_point(pt[0], pt[1], 'print')

        state.x, state.y, state.z = nx, ny, nz

    flush()
    return travel_segments, print_segments, z_annotations, state


# ══════════════════════════════════════════════════════════════════════════════
#  RENDERER
# ══════════════════════════════════════════════════════════════════════════════

def visualise(
    travel_segments: list,
    print_segments:  list,
    z_annotations:   list,
    title:           str = "Aerotech Nozzle Path Preview",
    unit_label:      str = "mm",
    output_path:     str = "gcode_nozzle_path.png",
) -> None:
    """
    Render the nozzle path and save it as a PNG at *output_path*.

    Deliberately has NO plt.show() call — this function is designed to work
    inside a GUI application and in --windowed executables without a display.
    plt.close(fig) is called at the end to free memory between conversions.
    """
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')

    # ── Travel moves (G0) — thin gray dashed lines ────────────────────────────
    for seg in travel_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        ax.plot(xs, ys, color='#888888', linewidth=0.8,
                linestyle='--', alpha=0.6, zorder=2)

    # ── Print moves (G1/G2/G3) — plasma gradient by print order ──────────────
    all_pts: list = []
    boundaries: list = []
    for seg in print_segments:
        start = len(all_pts)
        all_pts.extend(seg)
        boundaries.append((start, len(all_pts)))

    n_total = len(all_pts)
    cmap    = plt.get_cmap('plasma')

    for start, end in boundaries:
        seg_pts = all_pts[start:end]
        if len(seg_pts) < 2:
            continue
        for k in range(len(seg_pts) - 1):
            p0, p1 = seg_pts[k], seg_pts[k + 1]
            t      = (start + k) / max(n_total - 1, 1)
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]],
                    color=cmap(t), linewidth=1.5,
                    solid_capstyle='round', zorder=3)

    # ── Start / end markers ───────────────────────────────────────────────────
    if all_pts:
        ax.plot(*all_pts[0],  'o', color='#00ff88', markersize=8, zorder=5)
        ax.plot(*all_pts[-1], 's', color='#ff4444', markersize=8, zorder=5)

    # ── Z annotations ─────────────────────────────────────────────────────────
    seen_z: set = set()
    for ann_x, ann_y, ann_z, label in z_annotations:
        key = round(ann_z, 4)
        if key not in seen_z:
            ax.annotate(label, xy=(ann_x, ann_y), fontsize=6, color='#ffdd88',
                        bbox=dict(boxstyle='round,pad=0.2',
                                  fc='#333355', alpha=0.7), zorder=6)
            seen_z.add(key)

    # ── Axes / grid / labels ──────────────────────────────────────────────────
    ax.set_aspect('equal', adjustable='datalim')
    ax.grid(True, color='#444466', linewidth=0.4, linestyle=':', alpha=0.7)
    ax.tick_params(colors='#cccccc')
    for spine in ax.spines.values():
        spine.set_edgecolor('#666688')
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=11)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=11)
    ax.set_title(title, color='#eeeeff', fontsize=14, fontweight='bold', pad=12)

    # ── Legend ────────────────────────────────────────────────────────────────
    ax.legend(
        handles=[
            Line2D([0], [0], color='#888888', linewidth=1.2, linestyle='--',
                   label='Travel (G0)'),
            Line2D([0], [0], color=cmap(0.0), linewidth=2, label='Print start'),
            Line2D([0], [0], color=cmap(0.5), linewidth=2, label='Print mid'),
            Line2D([0], [0], color=cmap(1.0), linewidth=2, label='Print end'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#00ff88',
                   markersize=8, label='First print point'),
            Line2D([0], [0], marker='s', color='w', markerfacecolor='#ff4444',
                   markersize=8, label='Last  print point'),
        ],
        loc='upper right', facecolor='#2a2a3e',
        edgecolor='#666688', labelcolor='#cccccc', fontsize=8,
    )

    # ── Stats text box ────────────────────────────────────────────────────────
    n_travel = sum(len(s) - 1 for s in travel_segments)
    n_print  = sum(len(s) - 1 for s in print_segments)
    length   = sum(
        math.hypot(seg[k+1][0] - seg[k][0], seg[k+1][1] - seg[k][1])
        for seg in print_segments
        for k in range(len(seg) - 1)
    )
    ax.text(
        0.01, 0.01,
        f"Travel segments : {len(travel_segments)}\n"
        f"Travel sub-moves: {n_travel}\n"
        f"Print  segments : {len(print_segments)}\n"
        f"Print  sub-moves: {n_print}\n"
        f"Total print path: {length:.2f} {unit_label}",
        transform=ax.transAxes, fontsize=7.5, color='#aaaacc',
        verticalalignment='bottom',
        bbox=dict(boxstyle='round', facecolor='#2a2a3e',
                  alpha=0.8, edgecolor='#666688'),
    )

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)      # ← mandatory: frees Matplotlib memory; no plt.show()


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API  — called by gcode_converter_gui.py
# ══════════════════════════════════════════════════════════════════════════════

def convert_gcode_to_png(gcode_path: str, output_folder: str) -> str:
    """
    Full pipeline: read → preprocess → parse → render → save PNG.

    Parameters
    ----------
    gcode_path    : Absolute path to the input .gcode / .nc / .gco file.
    output_folder : Absolute path to the folder where the PNG will be written.

    Returns
    -------
    "SUCCESS"              – PNG written successfully.
    "Error: <message>"     – Something went wrong; the message is GUI-ready.

    This function never prints to stdout or raises exceptions —
    all output is returned as a string so the GUI can display it.
    """
    try:
        if not os.path.isfile(gcode_path):
            return f"Error: File not found: {gcode_path!r}"

        if not os.path.isdir(output_folder):
            return f"Error: Output folder does not exist: {output_folder!r}"

        with open(gcode_path, 'r', encoding='utf-8', errors='replace') as fh:
            raw = fh.read()

        source_label = os.path.basename(gcode_path)
        stem         = os.path.splitext(source_label)[0]
        output_path  = os.path.join(output_folder, stem + ".png")

        lines = preprocess(raw)
        travel_segs, print_segs, z_anns, state = parse_gcode(lines)

        visualise(
            travel_segs, print_segs, z_anns,
            title=f"Aerotech Nozzle Path – {source_label}",
            unit_label="mm" if state.unit_mm else "in",
            output_path=output_path,
        )

        return "SUCCESS"

    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"
