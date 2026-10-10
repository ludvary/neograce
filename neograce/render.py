"""
render.py - draws a Project with a QPainter.

The same Renderer.paint() call draws to the screen, to PNG/JPEG images,
to PDF and to SVG. That is why exported files always look like the screen.

How a data value becomes a pixel position (done in two steps):

    1. value -> t        to_t():  a fraction 0..1 along the axis
                                  (this is where log scale and "invert" are handled)
    2. t -> pixel        GraphMap: left + t * width   (y is flipped: bottom - t * height)
"""
import copy
import math
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPageLayout, QPageSize, QPainter,
                           QPainterPath, QPdfWriter, QPen, QTransform)

from . import latex
from .model import auto_major
from .textfmt import draw_text, set_text_mode, text_mode, text_size
from .transforms import ExprError, evaluate

# Grace sizes are relative numbers. These say what "1.0" means, in points.
PT_TEXT = 15.0       # char size 1.0
PT_SYMBOL = 10.0     # symbol size 1.0 (diameter)
PT_TICK = 9.0        # tick length 1.0
LINE_PT = 1.0        # line width 1.0
MINUS = "\u2212"     # a real minus sign looks better than a hyphen

# Dash patterns for LINE_STYLES 2..5, in units of the pen width
DASHES = {2: [1.0, 2.5], 3: [5.0, 3.0], 4: [9.0, 3.0], 5: [6.0, 2.5, 1.0, 2.5]}


def make_color(hex_color, alpha=1.0):
    if not hex_color:
        hex_color = "#000000"
    color = QColor(hex_color)
    alpha = max(0.0, min(1.0, float(alpha)))
    color.setAlphaF(alpha)
    return color


# ---------------------------------------------------------------------------
# Axis transforms
# ---------------------------------------------------------------------------

def forward(values, scale):
    """Data value(s) -> the "straightened" coordinate in which the axis is uniform.

    linear: v       log: log10(v)       reciprocal: 1/v       logit: ln(v / (1 - v))
    Values that can't be shown (e.g. v <= 0 on a log axis) become NaN.
    """
    v = np.asarray(values, dtype=float)
    with np.errstate(all="ignore"):           # silence warnings for invalid values
        if scale == "log":
            positive = v > 0
            return np.where(positive, np.log10(np.where(positive, v, 1.0)), np.nan)
        if scale == "reciprocal":
            nonzero = v != 0
            return np.where(nonzero, 1.0 / np.where(nonzero, v, 1.0), np.nan)
        if scale == "logit":
            inside = (v > 0) & (v < 1)
            safe = np.where(inside, v, 0.5)
            return np.where(inside, np.log(safe / (1.0 - safe)), np.nan)
    return v


def backward(u, scale):
    """The inverse of forward()."""
    u = np.asarray(u, dtype=float)
    with np.errstate(all="ignore"):
        if scale == "log":
            return 10.0 ** u
        if scale == "reciprocal":
            return 1.0 / u
        if scale == "logit":
            return 1.0 / (1.0 + np.exp(-u))
    return u


def valid_range(axis):
    """The axis range, repaired if it doesn't fit the scale (e.g. zero on a log axis)."""
    lo = float(axis.min)
    hi = float(axis.max)
    if axis.scale == "log":
        if hi <= 0:
            hi = 1.0
        if lo <= 0:
            lo = hi / 1000.0
    elif axis.scale == "reciprocal":
        if lo <= 0 and hi <= 0:
            lo = 0.1
            hi = 1.0
        elif lo <= 0:
            lo = hi / 1000.0
    elif axis.scale == "logit":
        lo = min(max(lo, 1e-6), 1 - 1e-6)
        hi = min(max(hi, 1e-6), 1 - 1e-6)
        if hi <= lo:
            lo = 0.01
            hi = 0.99
    return lo, hi


def axis_bounds(axis):
    """The axis range in the straightened coordinate (see forward)."""
    lo, hi = valid_range(axis)
    lo = float(forward(lo, axis.scale))
    hi = float(forward(hi, axis.scale))
    if hi == lo:
        hi = lo + 1.0
    return lo, hi


def to_t(values, axis):
    """World value(s) -> fraction 0..1 along the axis. Works on single numbers and arrays."""
    lo, hi = axis_bounds(axis)
    t = (forward(values, axis.scale) - lo) / (hi - lo)
    if axis.invert:
        t = 1.0 - t
    return t


def from_t(t, axis):
    """Fraction 0..1 along the axis -> world value (the inverse of to_t)."""
    t = np.asarray(t, dtype=float)
    if axis.invert:
        t = 1.0 - t
    lo, hi = axis_bounds(axis)
    return backward(lo + t * (hi - lo), axis.scale)


def set_range_t(axis, t0, t1):
    """Set the axis range to the part between fractions t0 and t1 of the current range.

    Example: set_range_t(axis, 0.25, 0.75) zooms in on the middle half.
    """
    a = float(from_t(t0, axis))
    b = float(from_t(t1, axis))
    axis.min = min(a, b)
    axis.max = max(a, b)


def view_to_world(graph, vx, vy):
    """Page (view) coordinates -> data coordinates of a graph. No drawing needed, just math."""
    vp = graph.viewport
    tx = (vx - vp[0]) / (vp[2] - vp[0])
    ty = (vy - vp[1]) / (vp[3] - vp[1])
    return float(from_t(tx, graph.xaxis)), float(from_t(ty, graph.yaxis))


def world_to_view(graph, wx, wy):
    vp = graph.viewport
    tx = float(to_t(wx, graph.xaxis))
    ty = float(to_t(wy, graph.yaxis))
    return vp[0] + tx * (vp[2] - vp[0]), vp[1] + ty * (vp[3] - vp[1])


class GraphMap:
    """Converts between world coordinates of one graph and pixel coordinates."""

    def __init__(self, graph, frame):
        self.graph = graph
        self.frame = QRectF(frame)       # the graph's frame in pixels

    def x(self, values):
        return self.frame.left() + to_t(values, self.graph.xaxis) * self.frame.width()

    def y(self, values):
        return self.frame.bottom() - to_t(values, self.graph.yaxis) * self.frame.height()

    def to_world(self, px, py):
        tx = (px - self.frame.left()) / self.frame.width()
        ty = (self.frame.bottom() - py) / self.frame.height()
        return float(from_t(tx, self.graph.xaxis)), float(from_t(ty, self.graph.yaxis))


# ---------------------------------------------------------------------------
# Tick positions and labels
# ---------------------------------------------------------------------------

def compute_ticks(axis):
    """Where the ticks go. Returns (major values, minor values, major step).

    With custom ticks ("Special" tab) the positions come from axis.custom_tick_list.
    """
    if axis.custom_ticks != "none" and len(axis.custom_tick_list) > 0:
        majors = []
        minors = []
        for entry in axis.custom_tick_list:
            if entry[2] == "minor":
                minors.append(float(entry[0]))
            else:
                majors.append(float(entry[0]))
        step = 1.0
        if len(majors) > 1:
            step = abs(majors[1] - majors[0])
        return majors, minors, step
    return automatic_ticks(axis)


def automatic_ticks(axis):
    lo, hi = valid_range(axis)
    if hi < lo:
        lo, hi = hi, lo
    if axis.scale == "log":
        return compute_log_ticks(axis, lo, hi)

    step = axis.major
    if axis.auto_ticks or step <= 0 or (hi - lo) / step > 500:
        step = auto_major(lo, hi, max(2, axis.autotick_divisions))

    # Rounded: ticks at multiples of step. Otherwise: ticks start at the axis minimum.
    origin = 0.0
    if not axis.place_rounded:
        origin = lo

    majors = []
    k = math.ceil((lo - origin) / step - 1e-9)       # first tick inside the range
    first_k = k
    while origin + k * step <= hi + 1e-9 * step and len(majors) < 1000:
        value = origin + k * step
        if abs(value) < 1e-12 * step:
            value = 0.0                    # avoid "-0" or 1e-17 instead of 0
        majors.append(value)
        k += 1

    minors = []
    if axis.minor > 0:
        sub = step / (axis.minor + 1)
        for kk in range(first_k - 1, k + 1):
            for j in range(1, axis.minor + 1):
                value = origin + kk * step + j * sub
                if value >= lo - 1e-9 * step and value <= hi + 1e-9 * step:
                    minors.append(value)
    return majors, minors, step


def compute_log_ticks(axis, lo, hi):
    if hi <= 0:
        return [], [], 10.0
    if lo <= 0:
        lo = hi / 1000.0
    k0 = math.floor(math.log10(lo) + 1e-9)
    k1 = math.ceil(math.log10(hi) - 1e-9)

    # Label every decade, or every 2nd/3rd/... if there are too many
    if axis.auto_ticks or axis.major <= 1:
        decades_per_tick = max(1, math.ceil((k1 - k0) / 8))
    else:
        decades_per_tick = max(1, round(math.log10(axis.major)))

    lo_limit = lo * (1 - 1e-9)
    hi_limit = hi * (1 + 1e-9)
    majors = []
    minors = []
    for k in range(k0, k1 + 1):
        value = 10.0 ** k
        if value >= lo_limit and value <= hi_limit:
            if k % decades_per_tick == 0:
                majors.append(value)
            elif decades_per_tick > 1:
                minors.append(value)

    if decades_per_tick == 1 and axis.minor > 0:
        for k in range(k0 - 1, k1 + 1):
            for m in range(2, 10):          # 2, 3, ... 9 times each power of ten
                value = m * 10.0 ** k
                if value >= lo_limit and value <= hi_limit:
                    minors.append(value)
    return majors, minors, 10.0 ** decades_per_tick


def decimals_needed(step):
    """How many decimals are needed to print multiples of `step` exactly (0.25 -> 2)."""
    for d in range(0, 12):
        if abs(round(step, d) - step) <= 1e-9 * abs(step):
            return d
    return 12


def power_format(value, digits=3):
    """2500 -> "2.5×10^3" (written with Grace codes so the exponent is a superscript)."""
    if value == 0:
        return "0"
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10.0 ** exponent
    mantissa_text = "%.*g" % (digits, mantissa)
    if mantissa_text == "1":
        return "10\\S" + str(exponent) + "\\N"
    if mantissa_text == "-1":
        return "-10\\S" + str(exponent) + "\\N"
    return mantissa_text + "\u00d710\\S" + str(exponent) + "\\N"


def scientific_format(value, prec):
    """2500 -> "2.50×10^3" (always mantissa × power of ten)."""
    if value == 0:
        return "0"
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10.0 ** exponent
    return "%.*f\u00d710\\S%d\\N" % (prec, mantissa, exponent)


ENGINEERING_PREFIXES = {-15: "f", -12: "p", -9: "n", -6: "\u00b5", -3: "m", 0: "", 3: "k", 6: "M",
                        9: "G", 12: "T", 15: "P"}


def engineering_format(value, prec):
    """2500 -> "2.5k", 0.0034 -> "3.4m" (SI prefixes, exponent a multiple of 3)."""
    if value == 0:
        return "0"
    exponent = int(math.floor(math.log10(abs(value)) / 3.0)) * 3
    exponent = max(-15, min(15, exponent))
    # mantissa between 1 and 1000, `prec` decimals, without trailing zeros ("500.00" -> "500")
    text = "%.*f" % (prec, value / 10.0 ** exponent)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + ENGINEERING_PREFIXES[exponent]


def format_number(value, fmt, prec):
    """Format one number for annotated values and formula tick labels."""
    if not math.isfinite(value):
        return ""
    if fmt == "decimal":
        text = "%.*f" % (prec, value)
    elif fmt == "exponential":
        text = "%.*e" % (prec, value)
    elif fmt == "power":
        text = power_format(value, prec + 1)
    elif fmt == "scientific":
        text = scientific_format(value, prec)
    elif fmt == "engineering":
        text = engineering_format(value, prec)
    else:
        text = "%.*g" % (max(1, prec), value)
    if text.startswith("-") and text[1:].strip("0.") == "":
        text = text[1:]
    return text.replace("-", MINUS)


def formula_tick_labels(axis, values):
    """Tick labels computed with the axis' ticklabel formula, e.g. "1240/x" (Grace writes $t for x)."""
    formula = axis.ticklabel_formula.replace("$t", "x").replace("$T", "x")
    x = np.array(values, dtype=float)
    try:
        target, results = evaluate("y = " + formula, x, np.zeros_like(x))
    except ExprError:
        return None
    labels = []
    for v in results:
        labels.append(format_number(float(v), axis.ticklabel_format, axis.ticklabel_prec))
    return labels


def number_to_latex(text):
    """A number as made by format_tick (e.g. "2.5×10\\S3\\N" or "−1") written as LaTeX math."""
    result = text.replace(MINUS, "-")
    result = result.replace("\u00d7", "\\times ")
    result = result.replace("\\S", "^{")
    result = result.replace("\\N", "}")
    return "$" + result + "$"


def axis_with_range_of(alt_axis, main_axis):
    """A copy of an alternate axis that uses the range and scale of the main axis."""
    result = copy.copy(alt_axis)
    result.min = main_axis.min
    result.max = main_axis.max
    result.scale = main_axis.scale
    result.invert = main_axis.invert
    return result


def format_tick(value, axis, step):
    fmt = axis.ticklabel_format
    if fmt == "decimal":
        text = "%.*f" % (axis.ticklabel_prec, value)
    elif fmt == "exponential":
        text = "%.*e" % (axis.ticklabel_prec, value)
    elif fmt == "power":
        text = power_format(value, axis.ticklabel_prec + 1)
    elif fmt == "scientific":
        text = scientific_format(value, axis.ticklabel_prec)
    elif fmt == "engineering":
        text = engineering_format(value, axis.ticklabel_prec)
    elif axis.scale == "log":
        text = "%.3g" % value
        if value > 0:
            k = round(math.log10(value))
            if abs(value / 10.0 ** k - 1) < 1e-6:
                text = "10\\S" + str(k) + "\\N"
    else:
        magnitude = abs(value)
        if value != 0 and (magnitude >= 1e6 or magnitude < 1e-4):
            text = power_format(value)
        else:
            text = "%.*f" % (decimals_needed(step), value)

    # "-0.00" -> "0.00"
    if text.startswith("-") and text[1:].strip("0.") == "":
        text = text[1:]
    return text.replace("-", MINUS)


# ---------------------------------------------------------------------------
# Symbol shapes
# ---------------------------------------------------------------------------

def symbol_path(shape, diameter):
    """A QPainterPath for the symbol, centred on (0, 0). Returns (path, can_be_filled)."""
    r = diameter / 2.0
    path = QPainterPath()
    if shape == 1:                                   # circle
        path.addEllipse(QPointF(0, 0), r, r)
    elif shape == 2:                                 # square
        a = r * 0.8
        path.addRect(QRectF(-a, -a, 2 * a, 2 * a))
    elif shape == 3:                                 # diamond
        path.moveTo(0, -r)
        path.lineTo(r, 0)
        path.lineTo(0, r)
        path.lineTo(-r, 0)
        path.closeSubpath()
    elif shape >= 4 and shape <= 7:                  # triangles: up, left, down, right
        triangle = QPainterPath()
        triangle.moveTo(0, -r)
        triangle.lineTo(0.87 * r, 0.5 * r)
        triangle.lineTo(-0.87 * r, 0.5 * r)
        triangle.closeSubpath()
        if shape == 4:
            angle = 0
        elif shape == 5:
            angle = -90
        elif shape == 6:
            angle = 180
        else:
            angle = 90
        path = QTransform().rotate(angle).map(triangle)
    elif shape == 8:                                 # plus
        path.moveTo(-r, 0)
        path.lineTo(r, 0)
        path.moveTo(0, -r)
        path.lineTo(0, r)
    elif shape == 9:                                 # x
        a = r * 0.75
        path.moveTo(-a, -a)
        path.lineTo(a, a)
        path.moveTo(-a, a)
        path.lineTo(a, -a)
    elif shape == 10:                                # star = plus + x
        a = r * 0.7
        path.moveTo(-r, 0)
        path.lineTo(r, 0)
        path.moveTo(0, -r)
        path.lineTo(0, r)
        path.moveTo(-a, -a)
        path.lineTo(a, a)
        path.moveTo(-a, a)
        path.lineTo(a, -a)
    can_be_filled = shape <= 7
    return path, can_be_filled


class GraphLayout:
    """Where a graph ended up on screen. The canvas uses this for mouse hit-testing."""

    def __init__(self, index, frame, graph_map):
        self.index = index
        self.frame = frame
        self.map = graph_map
        self.legend_rect = None
        self.label_rects = {}    # "xlabel", "ylabel", "altxlabel", "altylabel", "title", "subtitle" -> QRectF


# ---------------------------------------------------------------------------
# The renderer
# ---------------------------------------------------------------------------

class Renderer:
    def __init__(self):
        self.layout = []         # one GraphLayout (or None for hidden graphs) per graph
        self.project = None
        self.rect = QRectF()
        self.view_scale = 1.0    # pixels per view unit
        self.pt = 1.0            # pixels per point
        self.family = "Helvetica"
        self.paper = None        # page colour override (themed on-screen preview only)
        self.ink = None          # replaces black when paper/ink are set
        self.accent = "#2f6bed"
        self.object_rects = []   # pixel rectangle of every drawing object (for mouse picking)

    def paint(self, painter, project, rect, screen=False, transparent=False,
              paper=None, ink=None, accent=None):
        """Draw the whole page into `rect` (pixels of whatever device the painter draws on)."""
        self.project = project
        self.rect = QRectF(rect)
        self.view_scale = rect.width() / project.view_w()
        self.pt = rect.width() / project.page_w
        self.family = project.font_family
        set_text_mode(project.text_mode)
        latex.engine().preamble = project.latex_preamble
        self.paper = paper
        self.ink = ink
        if accent:
            self.accent = accent
        self.layout = []

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if not transparent:
            if self.paper:
                painter.fillRect(rect, make_color(self.paper))
            else:
                painter.fillRect(rect, make_color(project.page_color))

        visible_graphs = 0
        for g in project.graphs:
            if not g.hidden:
                visible_graphs += 1

        for index in range(len(project.graphs)):
            g = project.graphs[index]
            if g.hidden:
                self.layout.append(None)
                continue
            frame = self.view_rect(g.viewport)
            lay = GraphLayout(index, frame, GraphMap(g, frame))
            self.draw_graph(painter, g, lay)
            # Corner marks show which graph is current, if there is more than one
            if screen and index == project.current and visible_graphs > 1:
                self.draw_focus_marks(painter, frame)
            self.layout.append(lay)

        self.draw_objects(painter, project)
        if screen:
            self.draw_regions(painter, project)      # regions are only shown on screen, like Grace
        painter.restore()

    # ----------------------------------------------------------- coordinate helpers
    def view_to_px(self, vx, vy):
        """View coordinates (page, y up) -> pixels (y down)."""
        return self.rect.left() + vx * self.view_scale, self.rect.bottom() - vy * self.view_scale

    def px_to_view(self, px, py):
        return (px - self.rect.left()) / self.view_scale, (self.rect.bottom() - py) / self.view_scale

    def graph_map(self, graph_index):
        """The GraphMap of a graph as drawn, or None if it is hidden or doesn't exist."""
        if graph_index < 0 or graph_index >= len(self.layout):
            return None
        if self.layout[graph_index] is None:
            return None
        return self.layout[graph_index].map

    def view_rect(self, viewport):
        """Graph viewport (view coordinates, y up) -> pixel rectangle (y down)."""
        x0 = viewport[0]
        y0 = viewport[1]
        x1 = viewport[2]
        y1 = viewport[3]
        left = self.rect.left() + min(x0, x1) * self.view_scale
        right = self.rect.left() + max(x0, x1) * self.view_scale
        top = self.rect.bottom() - max(y0, y1) * self.view_scale
        bottom = self.rect.bottom() - min(y0, y1) * self.view_scale
        return QRectF(left, top, right - left, bottom - top)

    # ----------------------------------------------------------- colours, pens, fonts
    def font_or_default(self, spec):
        if spec:
            return spec
        return self.family

    def map_color(self, color):
        """In the themed preview, black becomes the theme's ink and white its paper."""
        if self.ink is None:
            return color
        if not color:
            color = "#000000"
        if color.lower() == "#000000":
            return self.ink
        if color.lower() == "#ffffff":
            return self.paper
        return color

    def make_pen(self, color, alpha=1.0, width=1.0, style=1):
        if style == 0 or width <= 0:
            return QPen(Qt.PenStyle.NoPen)
        pen = QPen(make_color(self.map_color(color), alpha))
        pen.setWidthF(width * LINE_PT * self.pt)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if style in DASHES:
            pen.setDashPattern(DASHES[style])
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        return pen

    def text_color(self):
        return self.map_color("#000000")

    # ----------------------------------------------------------- one graph
    def draw_graph(self, painter, g, lay):
        self.current_layout = lay
        frame = lay.frame
        if frame.width() < 2 or frame.height() < 2:
            return
        if g.bg_alpha > 0:
            painter.fillRect(frame, make_color(self.map_color(g.bg_color), g.bg_alpha))

        xticks = compute_ticks(g.xaxis)
        yticks = compute_ticks(g.yaxis)
        self.draw_grid(painter, g, lay.map, xticks, yticks)

        # Data is clipped to the frame
        painter.save()
        painter.setClipRect(frame)
        for ds in g.sets:
            if not ds.hidden and len(ds) > 0:
                self.draw_set(painter, ds, lay.map)
        painter.restore()

        painter.setPen(self.make_pen("#000000", 1.0, g.frame_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)

        # Main axes (bottom, left). Their mirror ticks are skipped where an alternate axis is drawn.
        top_extent = 0.0
        if g.xaxis.enabled:
            mirror = g.xaxis.mirror and not g.alt_xaxis.enabled
            extents = self.draw_axis(painter, g, lay.map, "x", g.xaxis, False, xticks, mirror)
            top_extent = max(top_extent, extents[1])
        if g.yaxis.enabled:
            mirror = g.yaxis.mirror and not g.alt_yaxis.enabled
            self.draw_axis(painter, g, lay.map, "y", g.yaxis, False, yticks, mirror)

        # Alternate axes (top, right)
        if g.alt_xaxis.enabled:
            alt = axis_with_range_of(g.alt_xaxis, g.xaxis)
            extents = self.draw_axis(painter, g, lay.map, "x", alt, True, compute_ticks(alt), False)
            top_extent = max(top_extent, extents[1])
        if g.alt_yaxis.enabled:
            alt = axis_with_range_of(g.alt_yaxis, g.yaxis)
            self.draw_axis(painter, g, lay.map, "y", alt, True, compute_ticks(alt), False)

        self.draw_titles(painter, g, frame, top_extent)
        lay.legend_rect = self.draw_legend(painter, g, frame)

    def draw_grid(self, painter, g, gmap, xticks, yticks):
        frame = gmap.frame
        for which in ("x", "y"):
            if which == "x":
                axis = g.xaxis
                ticks = xticks
            else:
                axis = g.yaxis
                ticks = yticks

            # Default grey grid becomes a faint version of the ink colour in the themed preview
            color = axis.grid_color
            alpha = 1.0
            if self.ink is not None and color.lower() == "#c8c8c8":
                color = self.ink
                alpha = 0.22

            # (enabled?, tick values, line style, line width): minor dotted, major solid
            passes = [(axis.grid_minor, ticks[1], 2, 0.5), (axis.grid_major, ticks[0], 1, 0.75)]
            for enabled, values, style, width in passes:
                if not enabled:
                    continue
                painter.setPen(self.make_pen(color, alpha, width, style))
                for v in values:
                    if which == "x":
                        px = float(gmap.x(v))
                        painter.drawLine(QPointF(px, frame.top()), QPointF(px, frame.bottom()))
                    else:
                        py = float(gmap.y(v))
                        painter.drawLine(QPointF(frame.left(), py), QPointF(frame.right(), py))

    # ----------------------------------------------------------- one data set
    def draw_set(self, painter, ds, gmap):
        n = len(ds)
        px = gmap.x(ds.x[:n])             # pixel positions of all points (numpy arrays)
        py = gmap.y(ds.y[:n])
        ok = np.isfinite(px) & np.isfinite(py)

        # 1. fill (underneath everything else)
        if ds.fill.type != 0:
            self.draw_fill(painter, ds, gmap, px, py, ok)

        # 2. the connecting line
        if ds.line.type != 0 and ds.line.style != 0:
            painter.setPen(self.make_pen(ds.line.color, ds.line.alpha, ds.line.width, ds.line.style))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self.line_path(px, py, ok, ds.line.type))

        # 3. error bars
        if ds.errorbar.show and (ds.dx is not None or ds.dy is not None):
            self.draw_error_bars(painter, ds, gmap, px, py, ok)

        # 4. symbols, only the ones near the frame
        frame = gmap.frame
        if ds.symbol.shape != 0:
            d = ds.symbol.size * PT_SYMBOL * self.pt
            visible = ok & (px > frame.left() - d) & (px < frame.right() + d)
            visible = visible & (py > frame.top() - d) & (py < frame.bottom() + d)
            step = max(1, ds.symbol.skip + 1)
            xs = []
            ys = []
            for i in range(0, n, step):
                if visible[i]:
                    xs.append(float(px[i]))
                    ys.append(float(py[i]))
            self.draw_symbols(painter, ds.symbol, xs, ys)

        # 5. annotated values
        if ds.avalue.type != 0:
            self.draw_avalues(painter, ds, frame, px, py, ok)

    def baseline_value(self, ds, gmap):
        """The y value the fill goes down (or up) to, for fill type "to baseline"."""
        n = len(ds)
        y = ds.y[:n]
        y = y[np.isfinite(y)]
        kind = ds.fill.baseline
        if kind == 1 and len(y) > 0:
            return float(y.min())
        if kind == 2 and len(y) > 0:
            return float(y.max())
        if kind == 3:
            return min(gmap.graph.yaxis.min, gmap.graph.yaxis.max)
        if kind == 4:
            return max(gmap.graph.yaxis.min, gmap.graph.yaxis.max)
        if kind == 5 and len(y) > 0:
            return float(y.mean())
        return 0.0

    def draw_fill(self, painter, ds, gmap, px, py, ok):
        # Use only the valid points, connected the same way as the line
        good_x = px[ok]
        good_y = py[ok]
        if len(good_x) < 2:
            return
        line_type = ds.line.type
        if line_type == 0 or line_type == 4:
            line_type = 1
        path = self.line_path(good_x, good_y, np.ones(len(good_x), dtype=bool), line_type)

        if ds.fill.type == 2:
            base_px = float(gmap.y(self.baseline_value(ds, gmap)))
            if not math.isfinite(base_px):
                base_px = gmap.frame.bottom()       # e.g. "zero" on a log axis
            path.lineTo(float(good_x[-1]), base_px)
            path.lineTo(float(good_x[0]), base_px)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(make_color(self.map_color(ds.fill.color), ds.fill.alpha)))
        painter.drawPath(path)

    def draw_error_bars(self, painter, ds, gmap, px, py, ok):
        n = len(ds)
        eb = ds.errorbar
        show_plus = eb.place != "opposite"
        show_minus = eb.place != "normal"
        cap = eb.cap * 3.0 * self.pt
        frame = gmap.frame
        path = QPainterPath()

        # Vertical bars
        extent = ds.error_extent("y")
        if extent is not None:
            low_px = gmap.y(extent[0])           # lower end (larger pixel y)
            high_px = gmap.y(extent[1])
            for i in range(n):
                if not ok[i]:
                    continue
                x = float(px[i])
                y = float(py[i])
                if show_plus and math.isfinite(high_px[i]):
                    end = float(high_px[i])
                    path.moveTo(x, y)
                    path.lineTo(x, end)
                    if cap > 0:
                        path.moveTo(x - cap, end)
                        path.lineTo(x + cap, end)
                if show_minus:
                    end = float(low_px[i])
                    has_cap = True
                    if not math.isfinite(end):
                        end = frame.bottom() + 50        # e.g. y - dy <= 0 on a log axis
                        has_cap = False
                    path.moveTo(x, y)
                    path.lineTo(x, end)
                    if cap > 0 and has_cap:
                        path.moveTo(x - cap, end)
                        path.lineTo(x + cap, end)

        # Horizontal bars
        extent = ds.error_extent("x")
        if extent is not None:
            low_px = gmap.x(extent[0])
            high_px = gmap.x(extent[1])
            for i in range(n):
                if not ok[i]:
                    continue
                x = float(px[i])
                y = float(py[i])
                if show_plus and math.isfinite(high_px[i]):
                    end = float(high_px[i])
                    path.moveTo(x, y)
                    path.lineTo(end, y)
                    if cap > 0:
                        path.moveTo(end, y - cap)
                        path.lineTo(end, y + cap)
                if show_minus:
                    end = float(low_px[i])
                    has_cap = True
                    if not math.isfinite(end):
                        end = frame.left() - 50
                        has_cap = False
                    path.moveTo(x, y)
                    path.lineTo(end, y)
                    if cap > 0 and has_cap:
                        path.moveTo(end, y - cap)
                        path.lineTo(end, y + cap)

        painter.setPen(self.make_pen(eb.color, eb.alpha, eb.width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def draw_avalues(self, painter, ds, frame, px, py, ok):
        """Print the X / Y / X,Y value next to each point."""
        av = ds.avalue
        n = len(ds)
        size = av.size * PT_TEXT * self.pt
        shift_x = av.offset_x * self.view_scale
        shift_y = -av.offset_y * self.view_scale        # view y points up, pixels point down
        color = self.map_color(av.color)
        font = self.font_or_default(av.font)
        margin = 20.0
        for i in range(n):
            if not ok[i]:
                continue
            x = float(px[i])
            y = float(py[i])
            if x < frame.left() - margin or x > frame.right() + margin:
                continue
            if y < frame.top() - margin or y > frame.bottom() + margin:
                continue
            x_text = format_number(float(ds.x[i]), av.format, av.prec)
            y_text = format_number(float(ds.y[i]), av.format, av.prec)
            if av.type == 1:
                text = x_text
            elif av.type == 2:
                text = y_text
            else:
                text = x_text + ", " + y_text
            if text_mode() == "all":
                text = number_to_latex(text)
            text = av.prepend + text + av.append
            draw_text(painter, text, x + shift_x, y + shift_y, size, color, font, 0.5, 1.0, av.angle)

    def draw_symbols(self, painter, symbol, xs, ys):
        d = symbol.size * PT_SYMBOL * self.pt
        path, can_be_filled = symbol_path(symbol.shape, d)
        painter.setPen(self.make_pen(symbol.color, symbol.alpha, symbol.linewidth))
        if symbol.fill and can_be_filled:
            painter.setBrush(QBrush(make_color(self.map_color(symbol.fill_color), symbol.fill_alpha)))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        # Each symbol is drawn separately so overlapping transparent symbols get darker
        for i in range(len(xs)):
            painter.drawPath(path.translated(xs[i], ys[i]))

    def line_path(self, px, py, ok, line_type):
        """Build the polyline. NaN points break the line into separate pieces."""
        path = QPainterPath()
        n = len(px)
        if line_type == 4:
            # "Segments": connect points 0-1, 2-3, 4-5, ...
            for i in range(0, n - 1, 2):
                if ok[i] and ok[i + 1]:
                    path.moveTo(float(px[i]), float(py[i]))
                    path.lineTo(float(px[i + 1]), float(py[i + 1]))
            return path

        started = False
        prev_x = 0.0
        prev_y = 0.0
        for i in range(n):
            if not ok[i]:
                started = False
                continue
            x = float(px[i])
            y = float(py[i])
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                if line_type == 2:          # left stairs: go vertical first
                    path.lineTo(prev_x, y)
                elif line_type == 3:        # right stairs: go horizontal first
                    path.lineTo(x, prev_y)
                path.lineTo(x, y)
            prev_x = x
            prev_y = y
        return path

    # ----------------------------------------------------------- axes
    def draw_axis(self, painter, g, gmap, which, axis, flipped, ticks, mirror):
        """Draw one axis on its normal side and, where asked for, on the opposite side.

        which:   "x" or "y"
        flipped: False for the main axes (normal side = bottom / left),
                 True for alternate axes (normal side = top / right)
        mirror:  also draw tick marks on the opposite side
        Returns [extent on the bottom/left side, extent on the top/right side]: how far
        the axis reaches out from the frame (used to keep the title clear of it).
        """
        extents = [0.0, 0.0]
        ticks_normal = not axis.ticks_opposite_only
        ticks_opposite = mirror or axis.ticks_opposite_only
        for side in ("normal", "opposite"):
            if side == "normal":
                draw_ticks = ticks_normal
            else:
                draw_ticks = ticks_opposite
            draw_ticklabels = axis.ticklabel_side == side or axis.ticklabel_side == "both"
            draw_label = axis.label_side == side or axis.label_side == "both"
            draw_bar = side == "normal" or axis.offset_opposite != 0.0
            if not (draw_ticks or draw_ticklabels or draw_label or draw_bar):
                continue
            on_top_or_right = (side == "opposite") != flipped        # != on booleans is "exclusive or"
            extent = self.draw_axis_side(painter, g, gmap, which, axis, ticks, side, on_top_or_right, flipped,
                                         draw_bar, draw_ticks, draw_ticklabels, draw_label)
            if on_top_or_right:
                extents[1] = max(extents[1], extent)
            else:
                extents[0] = max(extents[0], extent)
        return extents

    def draw_axis_side(self, painter, g, gmap, which, axis, ticks, side, on_top_or_right, flipped,
                       draw_bar, draw_ticks, draw_ticklabels, draw_label):
        """Bar, tick marks, tick labels and label of one axis on one side of the frame."""
        frame = gmap.frame
        majors = ticks[0]
        minors = ticks[1]
        step = ticks[2]

        # edge = where the axis line is; out = pixel direction pointing away from the frame
        if which == "x":
            if on_top_or_right:
                frame_edge = frame.top()
                out = -1.0
            else:
                frame_edge = frame.bottom()
                out = 1.0
        else:
            if on_top_or_right:
                frame_edge = frame.right()
                out = 1.0
            else:
                frame_edge = frame.left()
                out = -1.0
        edge = frame_edge
        if side == "normal" and axis.zero_axis:
            # "Zero axis": put the axis where the other coordinate is zero, if that's inside the frame
            if which == "x":
                zero = float(gmap.y(0.0))
                if math.isfinite(zero) and zero >= frame.top() and zero <= frame.bottom():
                    edge = zero
            else:
                zero = float(gmap.x(0.0))
                if math.isfinite(zero) and zero >= frame.left() and zero <= frame.right():
                    edge = zero
        if side == "normal":
            edge = edge + out * axis.offset_normal * self.view_scale
        else:
            edge = edge + out * axis.offset_opposite * self.view_scale

        # The axis bar. Where it is just the frame edge with default looks, the frame already drew it.
        if draw_bar and axis.bar_on:
            plain = (edge == frame_edge and axis.bar_width == g.frame_width
                     and axis.bar_color.lower() == "#000000" and axis.bar_style == 1)
            if not plain:
                painter.setPen(self.make_pen(axis.bar_color, 1.0, axis.bar_width, axis.bar_style))
                if which == "x":
                    painter.drawLine(QPointF(frame.left(), edge), QPointF(frame.right(), edge))
                else:
                    painter.drawLine(QPointF(edge, frame.top()), QPointF(edge, frame.bottom()))

        ticks_in = axis.tick_dir == "in" or axis.tick_dir == "both"
        ticks_out = axis.tick_dir == "out" or axis.tick_dir == "both"
        major_len = axis.major_len * PT_TICK * self.pt
        minor_len = axis.minor_len * PT_TICK * self.pt

        # Tick marks: first the majors, then the minors
        if draw_ticks and axis.ticks_on:
            passes = [(majors, major_len, axis.major_width, axis.major_color, axis.major_style),
                      (minors, minor_len, axis.minor_width, axis.minor_color, axis.minor_style)]
            for values, length, width, color, style in passes:
                painter.setPen(self.make_pen(color, 1.0, width, style))
                inside = 0.0
                outside = 0.0
                if ticks_in:
                    inside = length
                if ticks_out:
                    outside = length
                for v in values:
                    if which == "x":
                        pos = float(gmap.x(v))
                    else:
                        pos = float(gmap.y(v))
                    if math.isfinite(pos):
                        self.draw_tick(painter, which, pos, edge, out, inside, outside)

        # Tick labels
        label_px = axis.ticklabel_size * PT_TEXT * self.pt
        gap = 0.35 * label_px
        offset = gap
        if ticks_out and axis.ticks_on:
            offset = offset + major_len
        farthest = offset          # distance from the frame edge to the far side of the tick labels
        if draw_ticklabels and axis.show_ticklabels:
            farthest = self.draw_tick_labels(painter, gmap, which, axis, majors, step, edge, frame_edge,
                                             out, offset, label_px)
        extent = farthest

        # Axis label
        if draw_label and axis.label:
            px = axis.label_size * PT_TEXT * self.pt
            font = self.font_or_default(axis.label_font)
            color = self.map_color(axis.label_color)
            distance = farthest + gap * 1.2
            if axis.label_angle_auto:
                if which == "x":
                    label_angle = 0.0
                else:
                    label_angle = 90.0
            else:
                label_angle = axis.label_angle
            size = text_size(axis.label, px, font, color)
            radians = math.radians(label_angle)
            # How much room the (rotated) label takes, measured away from the frame
            if which == "x":
                across = abs(size.width() * math.sin(radians)) + abs(size.height() * math.cos(radians))
                center_x = frame.center().x()
                center_y = frame_edge + out * (distance + across / 2)
            else:
                across = abs(size.width() * math.cos(radians)) + abs(size.height() * math.sin(radians))
                center_x = frame_edge + out * (distance + across / 2)
                center_y = frame.center().y()
            center_x = center_x + axis.label_dx * self.view_scale
            center_y = center_y - axis.label_dy * self.view_scale
            box = draw_text(painter, axis.label, center_x, center_y, px, color, font, 0.5, 0.5, label_angle)
            name = which + "label"
            if flipped:
                name = "alt" + name
            if name not in self.current_layout.label_rects:
                self.current_layout.label_rects[name] = box      # for clicking/dragging on the canvas
            extent = distance + across
        return extent

    def draw_tick_labels(self, painter, gmap, which, axis, majors, step, edge, frame_edge, out, offset, label_px):
        """Draw the tick labels of one side. Returns how far they reach from the frame edge."""
        tick_font = self.font_or_default(axis.ticklabel_font)
        color = self.map_color(axis.ticklabel_color)
        shift_x = axis.ticklabel_dx * self.view_scale
        shift_y = -axis.ticklabel_dy * self.view_scale        # view y points up, pixels down
        angle = axis.ticklabel_angle
        farthest = offset + abs(edge - frame_edge)

        # Where the label texts come from: custom labels, a formula, or the value itself
        custom_labels = {}
        if axis.custom_ticks == "both":
            for entry in axis.custom_tick_list:
                if entry[2] != "minor":
                    custom_labels[float(entry[0])] = entry[1]
        formula_labels = None
        if axis.ticklabel_formula.strip() != "":
            formula_labels = formula_tick_labels(axis, majors)

        every = axis.ticklabel_skip + 1
        stagger_rows = axis.ticklabel_stagger + 1
        row_height = label_px * 1.25
        shown = 0
        tolerance = 1e-9 * abs(step)
        for k in range(len(majors)):
            if k % every != 0:
                continue
            v = majors[k]
            if not axis.ticklabel_start_auto and v < axis.ticklabel_start - tolerance:
                continue
            if not axis.ticklabel_stop_auto and v > axis.ticklabel_stop + tolerance:
                continue

            if v in custom_labels:
                text = custom_labels[v]
            else:
                if formula_labels is not None:
                    text = formula_labels[k]
                else:
                    text = format_tick(v, axis, step)
                if text_mode() == "all" and text != "":
                    text = number_to_latex(text)
            text = axis.ticklabel_prepend + text + axis.ticklabel_append

            # Stagger: every other label (or every third, ...) one row further out
            row = shown % stagger_rows
            shown += 1
            distance = offset + row * row_height

            if which == "x":
                anchor_x = float(gmap.x(v))
                anchor_y = edge + out * distance
                if angle == 0:
                    halign = 0.5
                    if out > 0:
                        valign = 0.0       # below the axis: text hangs down from the anchor
                    else:
                        valign = 1.0       # above the axis
                else:
                    # Rotated labels hang from their top corner at the tick and slope away from the frame
                    if out > 0:
                        valign = 0.0
                    else:
                        valign = 1.0
                    if (angle > 0) == (out > 0):
                        halign = 1.0
                    else:
                        halign = 0.0
            else:
                anchor_x = edge + out * distance
                anchor_y = float(gmap.y(v))
                valign = 0.5
                if out < 0:
                    halign = 1.0           # left of the axis: right-aligned
                else:
                    halign = 0.0
            box = draw_text(painter, text, anchor_x + shift_x, anchor_y + shift_y,
                            label_px, color, tick_font, halign, valign, angle)
            if which == "x":
                if out > 0:
                    farthest = max(farthest, box.bottom() - frame_edge)
                else:
                    farthest = max(farthest, frame_edge - box.top())
            else:
                if out < 0:
                    farthest = max(farthest, frame_edge - box.left())
                else:
                    farthest = max(farthest, box.right() - frame_edge)
        return farthest

    def draw_tick(self, painter, which, pos, edge, out, inside, outside):
        """One tick mark at position pos along the axis, on the given frame edge."""
        if which == "x":
            painter.drawLine(QPointF(pos, edge - out * inside), QPointF(pos, edge + out * outside))
        else:
            painter.drawLine(QPointF(edge - out * inside, pos), QPointF(edge + out * outside, pos))

    def draw_titles(self, painter, g, frame, top_extent):
        gap = 0.5 * PT_TEXT * self.pt
        if top_extent > 0:
            gap = top_extent + 0.3 * PT_TEXT * self.pt      # stay clear of the top axis
        y = frame.top() - gap             # bottom of the next line of text, going upwards
        color = self.text_color()
        if g.subtitle:
            px = g.subtitle_size * PT_TEXT * self.pt
            font = self.font_or_default(g.subtitle_font)
            size = text_size(g.subtitle, px, font, color)
            center_x = frame.center().x() + g.subtitle_dx * self.view_scale
            center_y = y - size.height() / 2 - g.subtitle_dy * self.view_scale
            box = draw_text(painter, g.subtitle, center_x, center_y, px, color, font, 0.5, 0.5, g.subtitle_angle)
            self.current_layout.label_rects["subtitle"] = box
            y = y - size.height() - 0.15 * PT_TEXT * self.pt
        if g.title:
            px = g.title_size * PT_TEXT * self.pt
            font = self.font_or_default(g.title_font)
            size = text_size(g.title, px, font, color)
            center_x = frame.center().x() + g.title_dx * self.view_scale
            center_y = y - size.height() / 2 - g.title_dy * self.view_scale
            box = draw_text(painter, g.title, center_x, center_y, px, color, font, 0.5, 0.5, g.title_angle)
            self.current_layout.label_rects["title"] = box

    def draw_legend(self, painter, g, frame):
        """Draw the legend box. Returns its rectangle (for mouse dragging) or None."""
        legend = g.legend
        entries = []
        for ds in g.sets:
            if not ds.hidden and ds.legend.strip() != "":
                entries.append(ds)
        if legend.invert:
            entries.reverse()
        if not legend.show or len(entries) == 0:
            return None

        px = legend.char_size * PT_TEXT * self.pt
        pad = legend.padding * px
        sample = legend.sample_length * px      # length of the line sample
        gap = 0.5 * px
        row_gap = legend.row_gap * px
        font = self.font_or_default(legend.font)
        color = self.text_color()

        # Measure every row first so we know the box size
        text_widths = []
        row_heights = []
        for ds in entries:
            size = text_size(ds.legend, px, font, color)
            text_widths.append(size.width())
            height = size.height()
            if ds.symbol.shape != 0:
                height = max(height, ds.symbol.size * PT_SYMBOL * self.pt)
            row_heights.append(height)

        width = 2 * pad + sample + gap + max(text_widths)
        height = 2 * pad + sum(row_heights) + row_gap * (len(entries) - 1)
        x0 = frame.left() + legend.x * frame.width()
        y0 = frame.top() + (1 - legend.y) * frame.height()
        box = QRectF(x0, y0, width, height)

        if legend.box or legend.fill:
            if legend.box:
                painter.setPen(self.make_pen("#000000", 1.0, legend.border_width))
            else:
                painter.setPen(QPen(Qt.PenStyle.NoPen))
            if legend.fill:
                painter.setBrush(QBrush(make_color(self.map_color(legend.box_fill), legend.box_alpha)))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(box)

        y = y0 + pad
        for i in range(len(entries)):
            ds = entries[i]
            center_y = y + row_heights[i] / 2
            if ds.line.type != 0 and ds.line.style != 0:
                painter.setPen(self.make_pen(ds.line.color, ds.line.alpha, ds.line.width, ds.line.style))
                painter.drawLine(QPointF(x0 + pad, center_y), QPointF(x0 + pad + sample, center_y))
            if ds.symbol.shape != 0:
                self.draw_symbols(painter, ds.symbol, [x0 + pad + sample / 2], [center_y])
            draw_text(painter, ds.legend, x0 + pad + sample + gap, center_y, px, color, font, 0.0, 0.5)
            y = y + row_heights[i] + row_gap
        return box

    # ----------------------------------------------------------- drawing objects
    def object_corners_px(self, obj):
        """The object's two points in pixels: (x1, y1, x2, y2), or None if it can't be placed."""
        if obj.coords == "world":
            gmap = self.graph_map(obj.graph)
            if gmap is None:
                return None
            x1 = float(gmap.x(obj.x1))
            y1 = float(gmap.y(obj.y1))
            x2 = float(gmap.x(obj.x2))
            y2 = float(gmap.y(obj.y2))
            if not (math.isfinite(x1) and math.isfinite(y1) and math.isfinite(x2) and math.isfinite(y2)):
                return None
            return x1, y1, x2, y2
        x1, y1 = self.view_to_px(obj.x1, obj.y1)
        x2, y2 = self.view_to_px(obj.x2, obj.y2)
        return x1, y1, x2, y2

    def draw_objects(self, painter, project):
        self.object_rects = []
        for obj in project.objects:
            rect = None
            if not obj.hidden:
                rect = self.draw_object(painter, obj)
            self.object_rects.append(rect)

    def draw_object(self, painter, obj):
        """Draw one object. Returns its bounding rectangle in pixels (or None)."""
        corners = self.object_corners_px(obj)
        if corners is None:
            return None
        x1 = corners[0]
        y1 = corners[1]
        x2 = corners[2]
        y2 = corners[3]
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, obj.alpha)))
        rect = None

        if obj.kind == "text":
            if obj.just == 1:
                halign = 1.0
            elif obj.just == 2:
                halign = 0.5
            else:
                halign = 0.0
            size = obj.char_size * PT_TEXT * self.pt
            text = obj.text
            if text == "":
                text = " "
            rect = draw_text(painter, text, x1, y1, size, self.map_color(obj.color),
                             self.font_or_default(obj.font), halign, 1.0, obj.angle)

        elif obj.kind == "line":
            pen = self.make_pen(obj.color, 1.0, obj.line_width, obj.line_style)
            painter.setPen(pen)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            length = obj.arrow_size * 8.0 * self.pt
            if obj.arrow == 1 or obj.arrow == 3:
                self.draw_arrowhead(painter, x2, y2, x1, y1, length, obj.color)
            if obj.arrow == 2 or obj.arrow == 3:
                self.draw_arrowhead(painter, x1, y1, x2, y2, length, obj.color)
            rect = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized().adjusted(-4, -4, 4, 4)

        else:
            # box or ellipse
            rect = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()
            painter.setPen(self.make_pen(obj.color, 1.0, obj.line_width, obj.line_style))
            if obj.fill:
                painter.setBrush(QBrush(make_color(self.map_color(obj.fill_color), obj.fill_alpha)))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            if obj.kind == "box":
                painter.drawRect(rect)
            else:
                painter.drawEllipse(rect)

        painter.restore()
        return rect

    def draw_arrowhead(self, painter, from_x, from_y, tip_x, tip_y, length, color):
        """A filled triangle at (tip_x, tip_y), pointing away from (from_x, from_y)."""
        angle = math.atan2(tip_y - from_y, tip_x - from_x)
        spread = math.radians(22)
        left_x = tip_x - length * math.cos(angle - spread)
        left_y = tip_y - length * math.sin(angle - spread)
        right_x = tip_x - length * math.cos(angle + spread)
        right_y = tip_y - length * math.sin(angle + spread)
        path = QPainterPath(QPointF(tip_x, tip_y))
        path.lineTo(left_x, left_y)
        path.lineTo(right_x, right_y)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(make_color(self.map_color(color)))
        painter.drawPath(path)

    # ----------------------------------------------------------- regions (screen only)
    def draw_regions(self, painter, project):
        for index in range(len(project.regions)):
            region = project.regions[index]
            gmap = self.graph_map(region.graph)
            if gmap is None or len(region.points) == 0:
                continue
            points = []
            for point in region.points:
                points.append(QPointF(float(gmap.x(point[0])), float(gmap.y(point[1]))))

            painter.save()
            pen = QPen(QColor(self.accent), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            if region.type == "inside" or region.type == "outside":
                fill = QColor(self.accent)
                fill.setAlphaF(0.08)
                painter.setBrush(fill)
                path = QPainterPath(points[0])
                for k in range(1, len(points)):
                    path.lineTo(points[k])
                path.closeSubpath()
                painter.drawPath(path)
            elif len(points) >= 2:
                # Extend the line across the whole frame
                painter.setClipRect(gmap.frame)
                dx = points[1].x() - points[0].x()
                dy = points[1].y() - points[0].y()
                size = math.hypot(dx, dy)
                if size > 0:
                    far = 10000.0 / size
                    start = QPointF(points[0].x() - dx * far, points[0].y() - dy * far)
                    end = QPointF(points[0].x() + dx * far, points[0].y() + dy * far)
                    painter.drawLine(start, end)
                painter.setClipping(False)
            draw_text(painter, "R%d" % index, points[0].x() + 4, points[0].y() - 4, 12.0, self.accent,
                      "Helvetica", 0.0, 1.0)
            painter.restore()

    def draw_focus_marks(self, painter, frame):
        """Small accent-coloured corner brackets around the current graph (screen only)."""
        painter.save()
        pen = QPen(QColor(self.accent), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        length = max(8.0, 14 * self.pt)
        offset = max(3.0, 5 * self.pt)
        # (corner, x direction into the frame, y direction into the frame)
        corners = [(frame.topLeft(), 1, 1), (frame.topRight(), -1, 1),
                   (frame.bottomLeft(), 1, -1), (frame.bottomRight(), -1, -1)]
        for corner, dx, dy in corners:
            x = corner.x() - dx * offset
            y = corner.y() - dy * offset
            painter.drawLine(QPointF(x, y), QPointF(x + dx * length, y))
            painter.drawLine(QPointF(x, y), QPointF(x, y + dy * length))
        painter.restore()


# ---------------------------------------------------------------------------
# Exporting to files
# ---------------------------------------------------------------------------

EXPORT_FORMATS = ["PDF", "SVG", "PNG", "JPEG", "EPS"]
EXTENSIONS = {"PDF": ".pdf", "SVG": ".svg", "PNG": ".png", "JPEG": ".jpg", "EPS": ".eps"}


def export_project(project, path, fmt, dpi=300, transparent=False):
    """Write the page to a file. Raises RuntimeError if something goes wrong."""
    fmt = fmt.upper()
    prepare_latex(project)
    if fmt == "PNG" or fmt == "JPEG":
        export_image(project, path, fmt, dpi, transparent)
    elif fmt == "PDF":
        write_pdf(project, path, transparent)
    elif fmt == "SVG":
        export_svg(project, path, transparent)
    elif fmt == "EPS":
        export_eps(project, path, transparent)
    else:
        raise RuntimeError("Unknown format " + fmt)


def prepare_latex(project):
    """Make sure every LaTeX string of the page is compiled before drawing a file.

    A quick paint into a small image asks for all strings (which queues the
    missing ones), then we wait for the LaTeX worker to finish.
    """
    if project.text_mode == "grace" or not latex.engine().available():
        return
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    Renderer().paint(painter, project, QRectF(0, 0, 400, 400 * project.page_h / project.page_w))
    painter.end()
    latex.engine().wait()


def export_image(project, path, fmt, dpi, transparent):
    width = max(1, round(project.page_w / 72.0 * dpi))
    height = max(1, round(project.page_h / 72.0 * dpi))
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    if transparent and fmt == "PNG":
        image.fill(Qt.GlobalColor.transparent)
    else:
        transparent = False                 # JPEG can't be transparent
        image.fill(Qt.GlobalColor.white)
    dots_per_meter = round(dpi / 0.0254)
    image.setDotsPerMeterX(dots_per_meter)
    image.setDotsPerMeterY(dots_per_meter)

    painter = QPainter(image)
    Renderer().paint(painter, project, QRectF(0, 0, width, height), transparent=transparent)
    painter.end()

    if fmt == "JPEG":
        image = image.convertToFormat(QImage.Format.Format_RGB32)
        ok = image.save(path, "JPG", 95)
    else:
        ok = image.save(path, "PNG")
    if not ok:
        raise RuntimeError("Could not write " + path)


def write_pdf(project, path, transparent):
    writer = QPdfWriter(path)
    writer.setResolution(600)
    writer.setCreator("NeoGrace")
    w = project.page_w
    h = project.page_h
    # QPageSize is always portrait; landscape pages get the Landscape orientation
    size = QPageSize(QSizeF(min(w, h), max(w, h)), QPageSize.Unit.Point, "Custom",
                     QPageSize.SizeMatchPolicy.ExactMatch)
    if w > h:
        orientation = QPageLayout.Orientation.Landscape
    else:
        orientation = QPageLayout.Orientation.Portrait
    writer.setPageLayout(QPageLayout(size, orientation, QMarginsF(0, 0, 0, 0)))
    painter = QPainter(writer)
    Renderer().paint(painter, project, QRectF(0, 0, writer.width(), writer.height()), transparent=transparent)
    painter.end()


def export_svg(project, path, transparent):
    from PySide6.QtSvg import QSvgGenerator
    generator = QSvgGenerator()
    generator.setFileName(path)
    generator.setSize(QSize(round(project.page_w), round(project.page_h)))
    generator.setViewBox(QRectF(0, 0, project.page_w, project.page_h))
    generator.setResolution(72)
    generator.setTitle("NeoGrace plot")
    painter = QPainter(generator)
    Renderer().paint(painter, project, QRectF(0, 0, project.page_w, project.page_h), transparent=transparent)
    painter.end()


def export_eps(project, path, transparent):
    """Qt can't write EPS, so we write a PDF and convert it with pdftops or ghostscript."""
    tool = shutil.which("pdftops")
    use_pdftops = True
    if tool is None:
        tool = shutil.which("gs")
        use_pdftops = False
    if tool is None:
        raise RuntimeError("EPS export needs 'pdftops' (poppler) or 'gs' (ghostscript) on your PATH.")
    with tempfile.TemporaryDirectory() as folder:
        pdf_path = os.path.join(folder, "plot.pdf")
        write_pdf(project, pdf_path, transparent)
        if use_pdftops:
            command = [tool, "-eps", pdf_path, path]
        else:
            command = [tool, "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=eps2write",
                       "-sOutputFile=" + path, pdf_path]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            message = result.stderr
            if not message:
                message = "EPS conversion failed"
            raise RuntimeError(message)
