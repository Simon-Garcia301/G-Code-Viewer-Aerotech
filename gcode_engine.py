"""
gcode_engine.py
━━━━━━━━━━━━━━━
Core G-code parsing, arc geometry, and PNG rendering engine.

Public API
----------
  convert_gcode_to_png(gcode_path, output_folder, bed_w, bed_h) -> str
"""

import os
import re
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

ARC_SEGMENTS = 72
INCH_TO_MM   = 25.4

_WORD_RE = re.compile(
    r'(?P<letter>[A-Z])'
    r'\s*'
    r'(?P<value>'
    r'[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?'   # numeric literal
    r'|'
    r'[&$][A-Za-z_]\w*'                    # variable reference $ or &
    r'|'
    r'\([^)]+\)'                            # parenthesized expression
    r')',
    re.IGNORECASE,
)

_VAR_DECL_RE = re.compile(
    r'var\s+'
    r'[&$]?(?P<name>[A-Za-z_]\w*)'
    r'(?:\s+as\s+\w+)?'
    r'\s*=\s*'
    r'(?P<value>[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)',
    re.IGNORECASE,
)

_NOOP_RE = re.compile(
    r'^(PositionOffsetSet|DigitalOutputSet|Dwell|Enable|Disable|Home)\s*\(',
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
#  MACHINE STATE
# ══════════════════════════════════════════════════════════════════════════════

class MachineState:
    def __init__(self):
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0
        self.absolute:     bool  = True
        self.unit_mm:      bool  = True
        self.feed_per_sec: bool  = True
        self.feedrate:     float = 1.0
        self.motion_mode:  int   = 0
        self.variables:    dict  = {}

    def to_mm(self, value: float) -> float:
        return value if self.unit_mm else value * INCH_TO_MM

    def resolve_target(self, axis: str, raw: float) -> float:
        mm = self.to_mm(raw)
        return mm if self.absolute else getattr(self, axis) + mm

    def resolve_variable(self, token: str) -> float:
        if token.startswith('$') or token.startswith('&'):
            name = token[1:]
            if name not in self.variables:
                raise ValueError(f"Variable '{token}' used before declaration.")
            return self.variables[name]
        return float(token)


# ══════════════════════════════════════════════════════════════════════════════
#  EXPRESSION EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_expression(expr: str, variables: dict) -> float:
    """
    Evaluate a parenthesized arithmetic expression such as ($X_Start + $LineLength).
    Supports +, -, *, /, numeric literals, and $var / &var references.
    """
    # Strip outer parentheses
    inner = expr.strip()
    if inner.startswith('(') and inner.endswith(')'):
        inner = inner[1:-1]

    # Replace every $NAME or &NAME with its numeric value
    def replace_var(m):
        prefix = m.group(1)   # $ or &
        name   = m.group(2)
        if name not in variables:
            raise ValueError(
                f"Variable '{prefix}{name}' used before declaration in expression."
            )
        return str(variables[name])

    inner = re.sub(r'([&$])([A-Za-z_]\w*)', replace_var, inner)

    # After substitution only digits, operators, dots and spaces should remain
    cleaned = re.sub(r'[^0-9+\-*/.(). ]', '', inner)
    if not cleaned.strip():
        raise ValueError(f"Empty expression after cleaning: {expr!r}")

    try:
        result = eval(cleaned, {"__builtins__": None}, {})  # noqa: S307
    except Exception as exc:
        raise ValueError(f"Cannot evaluate expression '{expr}': {exc}") from exc

    return float(result)


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
    cx, cy  = sx + i, sy + j
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
    r_abs      = abs(radius)
    mx, my     = (sx + ex) / 2, (sy + ey) / 2
    d          = math.hypot(ex - sx, ey - sy)
    half_chord = d / 2

    if half_chord > r_abs + 1e-9:
        r_abs = half_chord + 1e-9

    h = math.sqrt(max(0.0, r_abs ** 2 - half_chord ** 2))

    if d < 1e-12:
        return [(sx, sy), (ex, ey)]

    perp_x = -(ey - sy) / d
    perp_y =  (ex - sx) / d
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
    words = {}
    for m in _WORD_RE.finditer(line):
        letter = m.group('letter').upper()
        raw    = m.group('value')

        if raw.startswith('('):
            value = evaluate_expression(raw, state.variables)
        else:
            value = state.resolve_variable(raw)

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
    state = MachineState()

    travel_segments: list = []
    print_segments:  list = []
    z_annotations:   list = []

    _seg_type: list = [None]
    _seg_pts:  list = []

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
                _seg_pts.append(last)
        _seg_pts.append((x, y))

    for lineno, line in enumerate(lines, start=1):

        # Skip whole-line keywords that wrap arguments in parentheses
        if _NOOP_RE.match(line):
            continue

        # Skip bare keywords with no G-code content
        if line.lower() in ('program', 'end'):
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

        for g in g_list:
            if   g == 70: state.unit_mm      = False
            elif g == 71: state.unit_mm      = True
            elif g == 75: state.feed_per_sec = False
            elif g == 76: state.feed_per_sec = True
            elif g == 90: state.absolute     = True
            elif g == 91: state.absolute     = False

        if 'F' in words:
            f_mm = state.to_mm(words['F'])
            state.feedrate = f_mm if state.feed_per_sec else f_mm / 60.0

        motion_g = next((g for g in g_list if g in (0, 1, 2, 3)), None)
        if motion_g is None and any(k in words for k in ('X', 'Y', 'Z')):
            motion_g = state.motion_mode
        if motion_g is None:
            continue

        state.motion_mode = motion_g

        px, py, pz = state.x, state.y, state.z
        nx = state.resolve_target('x', words['X']) if 'X' in words else px
        ny = state.resolve_target('y', words['Y']) if 'Y' in words else py
        nz = state.resolve_target('z', words['Z']) if 'Z' in words else pz

        if abs(nz - pz) > 1e-9:
            z_annotations.append(
                ((px + nx) / 2, (py + ny) / 2, nz, f"Z={nz:.3f}")
            )

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
    title:           str   = "Aerotech Nozzle Path Preview",
    unit_label:      str   = "mm",
    output_path:     str   = "gcode_nozzle_path.png",
    bed_w:           float = None,
    bed_h:           float = None,
) -> None:

    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')

    # ── Travel moves ──────────────────────────────────────────────────────────
    for seg in travel_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        ax.plot(xs, ys, color='#888888', linewidth=0.8,
                linestyle='--', alpha=0.6, zorder=2)

    # ── Print moves — plasma gradient ─────────────────────────────────────────
    all_pts:    list = []
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
            ax.annotate(
                label, xy=(ann_x, ann_y), fontsize=6, color='#ffdd88',
                bbox=dict(boxstyle='round,pad=0.2', fc='#333355', alpha=0.7),
                zorder=6,
            )
            seen_z.add(key)

    # ── Bed boundary ──────────────────────────────────────────────────────────
    legend_extra = []
    if bed_w is not None and bed_h is not None:
        bed_rect = plt.Rectangle(
            (0, 0), bed_w, bed_h,
            linewidth=1.5, edgecolor='#66aaff',
            facecolor='none', linestyle='--', zorder=1,
        )
        ax.add_patch(bed_rect)
        legend_extra.append(
            Line2D([0], [0], color='#66aaff', linewidth=1.5, linestyle='--',
                   label=f'Bed ({bed_w}×{bed_h} {unit_label})')
        )

    # ── Auto-zoom with 5 % padding ────────────────────────────────────────────
    all_xs: list = []
    all_ys: list = []
    for seg in travel_segments + print_segments:
        for pt in seg:
            all_xs.append(pt[0])
            all_ys.append(pt[1])
    if bed_w is not None and bed_h is not None:
        all_xs += [0.0, float(bed_w)]
        all_ys += [0.0, float(bed_h)]

    if all_xs and all_ys:
        x_min, x_max = min(all_xs), max(all_xs)
        y_min, y_max = min(all_ys), max(all_ys)
        x_pad = max((x_max - x_min) * 0.05, 1.0)
        y_pad = max((y_max - y_min) * 0.05, 1.0)
        ax.set_xlim(x_min - x_pad, x_max + x_pad)
        ax.set_ylim(y_min - y_pad, y_max + y_pad)

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
        ] + legend_extra,
        loc='upper right', facecolor='#2a2a3e',
        edgecolor='#666688', labelcolor='#cccccc', fontsize=8,
    )

    # ── Stats text box ────────────────────────────────────────────────────────
    n_travel = sum(len(s) - 1 for s in travel_segments)
    n_print  = sum(len(s) - 1 for s in print_segments)
    length   = sum(
        math.hypot(seg[k + 1][0] - seg[k][0], seg[k + 1][1] - seg[k][1])
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
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def convert_gcode_to_png(
    gcode_path:    str,
    output_folder: str,
    bed_w:         float = None,
    bed_h:         float = None,
) -> str:
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
            bed_w=bed_w,
            bed_h=bed_h,
        )

        return "SUCCESS"

    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"