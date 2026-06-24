#!/usr/bin/env python3
"""
aerotech_gcode_viewer.py
━━━━━━━━━━━━━━━━━━━━━━━
Parses Aerotech Automation1 G-code files and renders an interactive 2-D
nozzle-path preview using Matplotlib.

Supported G-code dialect (Aerotech / RS-274 subset):
  G0  X Y Z          – Rapid move   (travel, shown as thin gray dashed line)
  G1  X Y Z F        – Linear feed  (print,  shown as solid blue line)
  G2  X Y [Z] R|I J  – CW  arc feed (print,  same blue)
  G3  X Y [Z] R|I J  – CCW arc feed (print,  same blue)
  G70               – Imperial (inch) units
  G71               – Metric  (mm)   units  [default]
  G75               – Feedrate in mm/min (imperial: in/min)
  G76               – Feedrate in mm/sec (imperial: in/sec)  [default]
  G90               – Absolute positioning  [default]
  G91               – Incremental positioning
  var $NAME = VALUE  – Declare/assign a floating-point variable
  $NAME              – Variable substitution inside any coordinate/feedrate
  // …              – Comment (entire line ignored)

Silently ignored (no path contribution):
  PositionOffsetSet(…)
  DigitalOutputSet(…)
  Dwell(…)
  Blank lines / pure-whitespace lines

Every other unrecognised token prints a warning and is skipped.

Author  : Generated with full documentation for instructional use
Requires: Python ≥ 3.8, numpy, matplotlib
"""

# ─────────────────────────────────────────────
#  HOW TO RUN
#  ----------
#  1.  pip install numpy matplotlib
#
#  2a. Provide a file path as the first CLI argument:
#        python aerotech_gcode_viewer.py my_program.gcode
#
#  2b. Or just run the script and enter the path (or paste G-code) when prompted:
#        python aerotech_gcode_viewer.py
#
#  2c. Drag-and-drop the .gcode file onto the script icon (the OS will pass
#      the file path as sys.argv[1]).
#
#  The script will open a Matplotlib window showing the nozzle path.
# ─────────────────────────────────────────────

import sys
import os
import re
import math
import textwrap
from typing import Optional

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D


# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

ARC_SEGMENTS   = 72      # Number of linear segments used to approximate one arc
INCH_TO_MM     = 25.4    # Conversion factor: 1 inch = 25.4 mm

# Regex fragments used during parsing
# Matches a G-code letter followed by an optional sign and a number
# e.g. "X-12.5", "F100", "R0.25", "I-5"
_WORD_RE = re.compile(
    r'(?P<letter>[A-Z])'           # single upper-case letter
    r'\s*'                         # optional whitespace (dialect is whitespace-insensitive)
    r'(?P<value>[+-]?\d+\.?\d*'   # integer or decimal …
    r'(?:[eE][+-]?\d+)?'           # … optional exponent (watch out: 'E' is also an axis!)
    r'|\$[A-Za-z_]\w*)',           # … OR a variable name like $Xlength
    re.IGNORECASE
)

# Matches a whole "var $NAME = VALUE" declaration line
# The spec uses both "var $Name = …" and "var Name = …" in practice,
# so we accept an optional leading "$".
_VAR_DECL_RE = re.compile(
    r'var\s+\$?(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)',
    re.IGNORECASE
)

# Known no-op function calls that should be silently skipped
_NOOP_PATTERNS = re.compile(
    r'^(PositionOffsetSet|DigitalOutputSet|Dwell|Enable|Disable|Home)\s*\(',
    re.IGNORECASE
)

# ══════════════════════════════════════════════════════════════════════════════
#  PARSER STATE
# ══════════════════════════════════════════════════════════════════════════════

class MachineState:
    """
    Holds the interpreter's current modal state and variable table.

    This mirrors the "modal" concept in RS-274: many G-codes stay active
    until explicitly changed (e.g. G90 stays in effect until G91 is seen).
    """

    def __init__(self):
        # Current position in *internal* units (always mm after conversion)
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0

        # Modal flags
        self.absolute: bool = True     # G90 = True, G91 = False
        self.unit_mm:  bool = True     # G71 = True (mm), G70 = False (inch)
        self.feed_per_sec: bool = True # G76 = True (sec), G75 = False (min)

        # Current feedrate (stored in mm/s; converted on input when needed)
        self.feedrate: float = 1.0

        # User-defined variable table:  name (str) → value (float)
        self.variables: dict = {}

        # Last seen G-code motion mode (0, 1, 2, or 3).
        # Needed for "modal" motion: a bare coordinate line inherits the
        # last motion command.
        self.motion_mode: int = 0

    # ──────────────────────────────────────────────────
    #  Unit helpers
    # ──────────────────────────────────────────────────

    def to_mm(self, value: float) -> float:
        """Convert a raw coordinate from current unit setting to mm."""
        return value if self.unit_mm else value * INCH_TO_MM

    def resolve_target(self, axis_letter: str, raw: float) -> float:
        """
        Convert a raw coordinate/offset value to an *absolute* mm position
        for the given axis, respecting G90/G91 and unit mode.

        axis_letter : 'x', 'y', or 'z'
        raw         : the number read from the G-code word (in current units)
        """
        mm_val = self.to_mm(raw)
        if self.absolute:
            return mm_val                          # G90: value IS the target
        else:
            current = getattr(self, axis_letter)
            return current + mm_val               # G91: value is an increment

    def resolve_variable(self, token: str) -> float:
        """
        If *token* starts with '$', look it up in the variable table.
        Otherwise, parse it as a float literal.

        Raises ValueError if the variable is undeclared.
        """
        if token.startswith('$'):
            name = token[1:]   # strip the '$'
            if name not in self.variables:
                raise ValueError(
                    f"Variable '${name}' is referenced but has not been declared. "
                    f"Make sure 'var ${name} = <value>' appears before its first use."
                )
            return self.variables[name]
        return float(token)


# ══════════════════════════════════════════════════════════════════════════════
#  ARC GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def arc_points_ij(
    sx: float, sy: float,   # start  (absolute mm)
    ex: float, ey: float,   # end    (absolute mm)
    i:  float, j:  float,   # center offsets from start (mm)
    clockwise: bool,
    n_seg: int = ARC_SEGMENTS
) -> list:
    """
    Generate *n_seg* + 1 (x, y) points along a circular arc defined by the
    IJK method (incremental offsets from start to center).

    The Aerotech dialect (like most RS-274 controllers) treats I, J as
    incremental offsets from the start point to the arc center:
        center = (sx + i, sy + j)

    Parameters
    ----------
    sx, sy    : arc start coordinates (mm, absolute)
    ex, ey    : arc end   coordinates (mm, absolute)
    i, j      : X, Y offsets from start to center (mm)
    clockwise : True for G2, False for G3
    n_seg     : number of linear segments to approximate the arc

    Returns
    -------
    List of (x, y) tuples from start → end along the arc.
    """
    # Centre of the circle
    cx = sx + i
    cy = sy + j

    # Radius (derived from distance start→center)
    radius = math.hypot(i, j)
    if radius < 1e-12:
        # Degenerate arc: center equals start – just give a straight line
        return [(sx, sy), (ex, ey)]

    # Starting and ending angles (measured from center)
    theta_start = math.atan2(sy - cy, sx - cx)
    theta_end   = math.atan2(ey - cy, ex - cx)

    # Compute the arc sweep, respecting direction
    if clockwise:
        # G2: sweep must be ≤ 0 (going clockwise = decreasing angle)
        sweep = theta_end - theta_start
        if sweep > 0:
            sweep -= 2 * math.pi
    else:
        # G3: sweep must be ≥ 0 (going counterclockwise = increasing angle)
        sweep = theta_end - theta_start
        if sweep < 0:
            sweep += 2 * math.pi

    # Handle full-circle case: if start == end the sweep would be 0 degrees,
    # but we want 360 degrees.  Detect this by checking if end ≈ start.
    if abs(ex - sx) < 1e-9 and abs(ey - sy) < 1e-9:
        sweep = -2 * math.pi if clockwise else 2 * math.pi

    # Produce interpolated points
    points = []
    for k in range(n_seg + 1):
        frac  = k / n_seg
        theta = theta_start + frac * sweep
        px    = cx + radius * math.cos(theta)
        py    = cy + radius * math.sin(theta)
        points.append((px, py))

    return points


def arc_points_r(
    sx: float, sy: float,   # start (mm, absolute)
    ex: float, ey: float,   # end   (mm, absolute)
    radius: float,          # signed radius (positive → short arc ≤180°)
    clockwise: bool,
    n_seg: int = ARC_SEGMENTS
) -> list:
    """
    Generate arc points using the *radius* method (R word).

    The Aerotech/RS-274 convention:
      - R > 0  → arc is ≤ 180°
      - R < 0  → arc is >  180°

    Internally we compute the arc center from the geometry,
    then delegate to arc_points_ij().
    """
    r_abs = abs(radius)

    # Midpoint of the chord
    mx = (sx + ex) / 2.0
    my = (sy + ey) / 2.0

    # Half-chord length
    d = math.hypot(ex - sx, ey - sy)
    half_chord = d / 2.0

    if half_chord > r_abs + 1e-9:
        # Radius too small to connect the two points – clamp to minimum
        print(f"  [WARNING] Arc radius {r_abs:.4f} is smaller than half the "
              f"chord ({half_chord:.4f}). Clamping radius.")
        r_abs = half_chord + 1e-9

    # Distance from midpoint to center
    h = math.sqrt(max(0.0, r_abs**2 - half_chord**2))

    # Unit perpendicular to the chord
    if d < 1e-12:
        return [(sx, sy), (ex, ey)]   # degenerate: start == end
    perp_x = -(ey - sy) / d
    perp_y =  (ex - sx) / d

    # Two candidate centers
    c1x = mx + h * perp_x;  c1y = my + h * perp_y
    c2x = mx - h * perp_x;  c2y = my - h * perp_y

    # Determine which center gives the "correct" arc (<180° or >180°)
    # For a CW arc with R>0 we want the short arc.
    # The cross product of (start→end) × (start→center) tells us which side.
    def cross(cx_c, cy_c):
        return (ex - sx) * (cy_c - sy) - (ey - sy) * (cx_c - sx)

    if radius > 0:
        # Short arc: center is on the right side for CW, left side for CCW
        use_c1 = (cross(c1x, c1y) < 0) == clockwise
    else:
        # Long arc: center is on the opposite side
        use_c1 = (cross(c1x, c1y) > 0) == clockwise

    if use_c1:
        cx, cy = c1x, c1y
    else:
        cx, cy = c2x, c2y

    # Convert to I, J offsets and delegate
    i_off = cx - sx
    j_off = cy - sy
    return arc_points_ij(sx, sy, ex, ey, i_off, j_off, clockwise, n_seg)


# ══════════════════════════════════════════════════════════════════════════════
#  PREPROCESSING: Normalise the raw text into clean lines
# ══════════════════════════════════════════════════════════════════════════════

def preprocess(raw_text: str) -> list:
    """
    Split the raw file text into a list of cleaned-up non-empty line strings.

    Handles:
    1.  Strip inline comments  (everything from '//' to end-of-line).
    2.  The Aerotech dialect is *whitespace-insensitive*: "G0X10Y5" is the
        same as "G0 X10 Y5".  We normalise by inserting a space before each
        G-code letter that directly follows a digit or another letter so the
        later word-level regex has consistent input.
        (We do NOT split the token if the letter is 'E' possibly part of
        exponential notation – handled by the regex careful matching.)
    3.  Semi-collapse multi-command lines such as "G71 G90 G76" into one
        logical unit (they're already handled by scanning all words on a line).
    4.  Return only non-empty lines.

    NOTE: We intentionally do NOT split lines because the Aerotech dialect
    allows multiple modal words on the same line ("G71 G90 G76 F10").
    """
    lines = []
    for raw_line in raw_text.splitlines():
        # 1. Remove inline // comments
        comment_pos = raw_line.find('//')
        if comment_pos != -1:
            raw_line = raw_line[:comment_pos]

        line = raw_line.strip()
        if not line:
            continue          # skip blanks

        lines.append(line)
    return lines


# ══════════════════════════════════════════════════════════════════════════════
#  LINE TOKENISER
# ══════════════════════════════════════════════════════════════════════════════

def tokenise_line(line: str, state: MachineState) -> dict:
    """
    Parse a single G-code line into a dictionary of words.

    Returns a dict like:
        {'G': 1, 'X': 10.0, 'Y': -5.0, 'F': 100.0}

    For variable references ($NAME), the current value is substituted.
    G-code numbers are returned as ints; coordinate/parameter values as floats.

    Raises ValueError on undefined variable references.
    """
    words = {}

    for m in _WORD_RE.finditer(line):
        letter = m.group('letter').upper()
        raw    = m.group('value')

        # Resolve variable if needed
        value_f = state.resolve_variable(raw)

        if letter == 'G':
            # G-codes are integer codes; store as int
            words[letter] = int(value_f)
            # Multiple G-codes on one line (e.g. G71 G90) are handled by
            # processing in order – we collect ALL of them via a list.
            if 'G_list' not in words:
                words['G_list'] = []
            words['G_list'].append(int(value_f))
        elif letter == 'M':
            words[letter] = int(value_f)
        else:
            words[letter] = value_f

    return words


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN PARSER / INTERPRETER
# ══════════════════════════════════════════════════════════════════════════════

def parse_gcode(lines: list) -> tuple:
    """
    Walk through the pre-processed lines and build two lists of path segments:

    travel_segments : [ [(x0,y0),(x1,y1), …], … ]  – G0 rapid moves
    print_segments  : [ [(x0,y0),(x1,y1), …], … ]  – G1/G2/G3 feed moves

    Also records a list of Z-change annotations:
        z_annotations : [ (x, y, z_value, label), … ]

    Returns (travel_segments, print_segments, z_annotations, state)
    """
    state   = MachineState()

    # Each "segment" is a list of (x,y) points.
    # A new segment starts whenever we lift the pen (go from travel→print
    # or print→travel, or after a Z change).
    travel_segments = []
    print_segments  = []
    z_annotations   = []

    # We build the current segment incrementally, then flush it.
    _current_seg   = None   # None | 'travel' | 'print'
    _current_pts   = []

    def flush_segment():
        nonlocal _current_seg, _current_pts
        if len(_current_pts) >= 2:
            if _current_seg == 'travel':
                travel_segments.append(list(_current_pts))
            elif _current_seg == 'print':
                print_segments.append(list(_current_pts))
        _current_pts  = []
        _current_seg  = None

    def append_point(x, y, move_type: str):
        """
        Add (x,y) to the current segment; start a new segment if move type
        changed (travel ↔ print).
        """
        nonlocal _current_seg, _current_pts
        if _current_seg != move_type:
            # Save old endpoint as start of new segment (for continuity)
            last_pt = _current_pts[-1] if _current_pts else None
            flush_segment()
            _current_seg = move_type
            if last_pt:
                _current_pts.append(last_pt)   # overlap for visual continuity
        _current_pts.append((x, y))

    # ──────────────────────────────────────────────────
    #  Process each line
    # ──────────────────────────────────────────────────
    for lineno, line in enumerate(lines, start=1):

        # ── Silently skip known no-op calls ──────────────────────────────────
        if _NOOP_PATTERNS.match(line):
            continue

        # ── Variable declaration: "var $NAME = VALUE" ─────────────────────
        var_m = _VAR_DECL_RE.match(line)
        if var_m:
            name  = var_m.group('name')
            value = float(var_m.group('value'))
            state.variables[name] = value
            continue

        # ── Attempt to tokenise as G-code words ───────────────────────────
        try:
            words = tokenise_line(line, state)
        except ValueError as exc:
            # Undefined variable reference – per spec, raise a clear error.
            raise ValueError(f"Line {lineno}: {exc}\n  Line content: {line!r}")

        if not words:
            # Nothing was recognised on this line
            print(f"  [SKIP line {lineno}] Not recognised: {line!r}")
            continue

        # ── Collect all G-codes on this line ─────────────────────────────
        g_list = words.get('G_list', [])

        # ── Apply modal-only G-codes first (units, mode switches, etc.) ────
        for g in g_list:
            if   g == 70:
                state.unit_mm     = False
                print(f"  [mode] Line {lineno}: G70 → inch units")
            elif g == 71:
                state.unit_mm     = True
                print(f"  [mode] Line {lineno}: G71 → mm units")
            elif g == 75:
                state.feed_per_sec = False
                print(f"  [mode] Line {lineno}: G75 → feed in units/min")
            elif g == 76:
                state.feed_per_sec = True
                print(f"  [mode] Line {lineno}: G76 → feed in units/sec")
            elif g == 90:
                state.absolute    = True
                print(f"  [mode] Line {lineno}: G90 → absolute")
            elif g == 91:
                state.absolute    = False
                print(f"  [mode] Line {lineno}: G91 → incremental")

        # ── Update feedrate if F word is present ─────────────────────────
        if 'F' in words:
            f_raw = words['F']
            f_mm  = state.to_mm(f_raw)
            # Store feedrate in mm/s (convert if G75 / per-minute mode)
            if state.feed_per_sec:
                state.feedrate = f_mm
            else:
                state.feedrate = f_mm / 60.0

        # ── Determine motion command ──────────────────────────────────────
        # Use the last G in g_list that is a motion command, or fall back to
        # the modal motion mode.
        motion_g = None
        for g in g_list:
            if g in (0, 1, 2, 3):
                motion_g = g
        if motion_g is None and ('X' in words or 'Y' in words or 'Z' in words):
            # Bare coordinates on a line → use modal motion mode
            motion_g = state.motion_mode

        if motion_g is None:
            # No motion on this line – purely modal changes, already handled
            continue

        # Update modal motion mode
        state.motion_mode = motion_g

        # ── Read target coordinates ───────────────────────────────────────
        # For G90 (absolute): target IS the coordinate value.
        # For G91 (incremental): target is current + value.
        # Axes not mentioned keep their current value.

        prev_x, prev_y, prev_z = state.x, state.y, state.z

        new_x = state.resolve_target('x', words['X']) if 'X' in words else state.x
        new_y = state.resolve_target('y', words['Y']) if 'Y' in words else state.y
        new_z = state.resolve_target('z', words['Z']) if 'Z' in words else state.z

        # Check for Z change → add annotation
        if abs(new_z - state.z) > 1e-9:
            z_annotations.append((
                (prev_x + new_x) / 2,
                (prev_y + new_y) / 2,
                new_z,
                f"Z={new_z:.3f}"
            ))

        # ── Execute the motion command ────────────────────────────────────

        if motion_g == 0:
            # G0 Rapid move (travel)
            append_point(prev_x, prev_y, 'travel')
            append_point(new_x,  new_y,  'travel')
            state.x, state.y, state.z = new_x, new_y, new_z

        elif motion_g == 1:
            # G1 Linear feed (print)
            append_point(prev_x, prev_y, 'print')
            append_point(new_x,  new_y,  'print')
            state.x, state.y, state.z = new_x, new_y, new_z

        elif motion_g in (2, 3):
            # G2/G3 Arc feed (print)
            clockwise = (motion_g == 2)

            if 'R' in words:
                # ── Radius method ─────────────────────────────────────────
                r = state.to_mm(words['R'])
                pts = arc_points_r(
                    prev_x, prev_y,
                    new_x,  new_y,
                    r, clockwise
                )
            elif 'I' in words or 'J' in words:
                # ── IJK method (incremental offsets to center) ─────────────
                i = state.to_mm(words.get('I', 0.0))
                j = state.to_mm(words.get('J', 0.0))
                pts = arc_points_ij(
                    prev_x, prev_y,
                    new_x,  new_y,
                    i, j, clockwise
                )
            else:
                print(f"  [WARN line {lineno}] G{motion_g} has neither R nor I/J – skipping arc.")
                pts = [(prev_x, prev_y), (new_x, new_y)]

            # Add arc points to the print segment
            for pt in pts:
                append_point(pt[0], pt[1], 'print')

            state.x, state.y, state.z = new_x, new_y, new_z

        else:
            print(f"  [SKIP line {lineno}] Unrecognised motion G{motion_g}: {line!r}")

    # Flush any remaining open segment
    flush_segment()

    return travel_segments, print_segments, z_annotations, state


# ══════════════════════════════════════════════════════════════════════════════
#  VISUALISER
# ══════════════════════════════════════════════════════════════════════════════

def visualise(
    travel_segments: list,
    print_segments:  list,
    z_annotations:   list,
    title:           str = "Aerotech Nozzle Path Preview",
    unit_label:      str = "mm"
):
    """
    Render the nozzle path using Matplotlib.

    travel_segments : list of polylines for G0 moves  → thin gray dashed
    print_segments  : list of polylines for G1/G2/G3  → solid blue, gradient
    z_annotations   : list of (x, y, z, label) tuples
    title           : window / figure title
    unit_label      : 'mm' or 'in'
    """

    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor('#1e1e2e')     # dark background for contrast
    ax.set_facecolor('#1e1e2e')

    # ── Draw travel moves (G0) ────────────────────────────────────────────
    for seg in travel_segments:
        if len(seg) < 2:
            continue
        xs = [p[0] for p in seg]
        ys = [p[1] for p in seg]
        ax.plot(
            xs, ys,
            color='#888888',
            linewidth=0.8,
            linestyle='--',
            alpha=0.6,
            zorder=2
        )

    # ── Draw print moves (G1/G2/G3) with a colour gradient by order ──────
    # Collect ALL print points in order so we can colour them sequentially.
    all_print_pts = []
    seg_boundaries = []   # (start_idx, end_idx) per segment
    for seg in print_segments:
        start = len(all_print_pts)
        all_print_pts.extend(seg)
        seg_boundaries.append((start, len(all_print_pts)))

    n_total = len(all_print_pts)

    # Use a colour map to show print order (early = cool blue, late = warm red)
    cmap = plt.get_cmap('plasma')   # perceptually uniform: dark purple → yellow

    for start, end in seg_boundaries:
        seg_pts = all_print_pts[start:end]
        if len(seg_pts) < 2:
            continue
        # Colour each sub-segment according to its position in the overall print
        for k in range(len(seg_pts) - 1):
            p0 = seg_pts[k]
            p1 = seg_pts[k + 1]
            # Normalised progress (0 = start of print, 1 = end)
            t = (start + k) / max(n_total - 1, 1)
            colour = cmap(t)
            ax.plot(
                [p0[0], p1[0]],
                [p0[1], p1[1]],
                color=colour,
                linewidth=1.5,
                solid_capstyle='round',
                zorder=3
            )

    # ── Mark start and end of print ───────────────────────────────────────
    if all_print_pts:
        sx, sy = all_print_pts[0]
        ex, ey = all_print_pts[-1]
        ax.plot(sx, sy, 'o', color='#00ff88', markersize=8,
                zorder=5, label='Print start')
        ax.plot(ex, ey, 's', color='#ff4444', markersize=8,
                zorder=5, label='Print end')

    # ── Z annotations ─────────────────────────────────────────────────────
    already_labelled = set()
    for ann_x, ann_y, ann_z, ann_label in z_annotations:
        key = round(ann_z, 4)
        if key not in already_labelled:
            ax.annotate(
                ann_label,
                xy=(ann_x, ann_y),
                fontsize=6,
                color='#ffdd88',
                bbox=dict(boxstyle='round,pad=0.2', fc='#333355', alpha=0.7),
                zorder=6
            )
            already_labelled.add(key)

    # ── Axes, grid, labels ────────────────────────────────────────────────
    ax.set_aspect('equal', adjustable='datalim')
    ax.grid(True, color='#444466', linewidth=0.4, linestyle=':', alpha=0.7)
    ax.tick_params(colors='#cccccc')
    for spine in ax.spines.values():
        spine.set_edgecolor('#666688')

    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=11)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=11)
    ax.set_title(title, color='#eeeeff', fontsize=14, fontweight='bold', pad=12)

    # ── Legend ────────────────────────────────────────────────────────────
    legend_elements = [
        Line2D([0], [0], color='#888888', linewidth=1.2, linestyle='--',
               label='Travel move (G0)'),
        Line2D([0], [0], color=cmap(0.0), linewidth=2,
               label='Print start (G1/G2/G3)'),
        Line2D([0], [0], color=cmap(0.5), linewidth=2,
               label='Print mid'),
        Line2D([0], [0], color=cmap(1.0), linewidth=2,
               label='Print end'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#00ff88',
               markersize=8, label='First print point'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#ff4444',
               markersize=8, label='Last  print point'),
    ]
    legend = ax.legend(
        handles=legend_elements,
        loc='upper right',
        facecolor='#2a2a3e',
        edgecolor='#666688',
        labelcolor='#cccccc',
        fontsize=8
    )

    # ── Statistics text box ───────────────────────────────────────────────
    n_travel = sum(len(s) - 1 for s in travel_segments)
    n_print  = sum(len(s) - 1 for s in print_segments)

    # Approximate total print path length
    print_length = 0.0
    for seg in print_segments:
        for k in range(len(seg) - 1):
            dx = seg[k+1][0] - seg[k][0]
            dy = seg[k+1][1] - seg[k][1]
            print_length += math.hypot(dx, dy)

    stats = (
        f"Travel segments : {len(travel_segments)}\n"
        f"Travel sub-moves: {n_travel}\n"
        f"Print  segments : {len(print_segments)}\n"
        f"Print  sub-moves: {n_print}\n"
        f"Total print path: {print_length:.2f} {unit_label}"
    )
    ax.text(
        0.01, 0.01, stats,
        transform=ax.transAxes,
        fontsize=7.5,
        color='#aaaacc',
        verticalalignment='bottom',
        bbox=dict(boxstyle='round', facecolor='#2a2a3e', alpha=0.8, edgecolor='#666688')
    )

    plt.tight_layout()
    plt.show()


# ══════════════════════════════════════════════════════════════════════════════
#  FILE / INPUT HANDLING
# ══════════════════════════════════════════════════════════════════════════════

_EXAMPLE_GCODE = textwrap.dedent("""\
    // Aerotech Automation1 – Simple rectangle test
    G71       // mm units
    G76       // feedrate in mm/sec
    G90       // absolute positioning
    F10       // feedrate = 10 mm/s
    var $Zprint = 0.4
    G0 X0 Y0 Z5
    G0 X0 Y0 Z$Zprint
    G1 X55 Y0
    G1 X55 Y45
    G1 X0  Y45
    G1 X0  Y0
    G0 X0  Y0 Z5
""")


def get_gcode_text() -> tuple:
    """
    Obtain the G-code source text and an optional file-path label.

    Priority:
      1. sys.argv[1]  – file path passed on the command line / drag-and-drop
      2. interactive  – user is prompted to enter a file path OR paste G-code
      3. built-in     – fall back to _EXAMPLE_GCODE if user just presses Enter

    Returns (gcode_text: str, source_label: str)
    """
    # ── 1. Command-line argument ──────────────────────────────────────────
    if len(sys.argv) > 1:
        path = sys.argv[1].strip().strip('"').strip("'")
        if not os.path.isfile(path):
            print(f"[ERROR] File not found: {path!r}")
            sys.exit(1)
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read(), os.path.basename(path)

    # ── 2. Interactive prompt ─────────────────────────────────────────────
    print("═" * 60)
    print("  Aerotech G-code Nozzle Path Viewer")
    print("═" * 60)
    print("  Provide a file path, or press [Enter] to use the built-in")
    print("  rectangle example.\n")

    user_input = input("  File path (or press Enter for example): ").strip().strip('"').strip("'")

    if user_input:
        if not os.path.isfile(user_input):
            print(f"[ERROR] File not found: {user_input!r}")
            sys.exit(1)
        with open(user_input, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read(), os.path.basename(user_input)

    # ── 3. Built-in example ───────────────────────────────────────────────
    print("\n  No file provided – using built-in rectangle example.\n")
    return _EXAMPLE_GCODE, "Built-in rectangle example"


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("━" * 60)
    print("  Aerotech Automation1 G-Code Nozzle Path Viewer")
    print("━" * 60)

    # ── Obtain source text ────────────────────────────────────────────────
    gcode_text, source_label = get_gcode_text()
    print(f"\n  Source: {source_label}")

    # ── Pre-process ───────────────────────────────────────────────────────
    lines = preprocess(gcode_text)
    print(f"  Lines after preprocessing: {len(lines)}\n")

    # ── Parse ─────────────────────────────────────────────────────────────
    print("  Parsing G-code …")
    try:
        travel_segs, print_segs, z_anns, final_state = parse_gcode(lines)
    except ValueError as exc:
        print(f"\n[FATAL] {exc}")
        sys.exit(1)

    # ── Report ────────────────────────────────────────────────────────────
    unit_label = "mm" if final_state.unit_mm else "in"
    print(f"\n  ✓ Parsing complete.")
    print(f"    Travel segments : {len(travel_segs)}")
    print(f"    Print  segments : {len(print_segs)}")
    print(f"    Z annotations   : {len(z_anns)}")
    print(f"    Final position  : X={final_state.x:.4f}  "
          f"Y={final_state.y:.4f}  Z={final_state.z:.4f}  ({unit_label})")
    print(f"    Unit mode       : {'mm' if final_state.unit_mm else 'inch'}")
    print(f"    Positioning     : {'absolute (G90)' if final_state.absolute else 'incremental (G91)'}")
    print(f"    Variables       : {final_state.variables}")
    print()

    # ── Visualise ─────────────────────────────────────────────────────────
    print("  Opening visualiser …")
    visualise(
        travel_segs,
        print_segs,
        z_anns,
        title=f"Aerotech Nozzle Path Preview – {source_label}",
        unit_label=unit_label
    )


if __name__ == '__main__':
    main()
