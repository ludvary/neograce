"""
model.py - the data model of NeoGrace.

Think of this file as a set of plain C++ structs:

    Project            the whole page
      Graph[]          one or more plots on the page
        Axis xaxis, yaxis
        Legend legend
        DataSet[]      the curves in that graph
          Symbol, Line, ErrorBar   how the curve looks
          x, y, dy                 the numbers (numpy arrays)

There is no Qt in this file. Everything here is just data plus a few
helper functions (autoscaling, saving, undo snapshots).

Coordinates follow Grace: "view" coordinates, where the shorter side
of the page has length 1 and (0, 0) is the bottom-left corner.
"""
import copy
import json
import math

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Grace's default 16-colour table. Index 0 is white, 1 is black, and so on.
GRACE_COLORS = [
    ("white", "#ffffff"), ("black", "#000000"), ("red", "#ff0000"), ("green", "#00ff00"),
    ("blue", "#0000ff"), ("yellow", "#ffff00"), ("brown", "#bc8f8f"), ("grey", "#dcdcdc"),
    ("violet", "#9400d3"), ("cyan", "#00ffff"), ("magenta", "#ff00ff"), ("orange", "#ffa500"),
    ("indigo", "#7221bc"), ("maroon", "#670748"), ("turquoise", "#40e0d0"), ("green4", "#008b00"),
]

# The index in these lists is what gets stored in the model (same numbers as Grace uses).
SYMBOL_NAMES = ["None", "Circle", "Square", "Diamond", "Triangle up", "Triangle left",
                "Triangle down", "Triangle right", "Plus", "X", "Star"]
LINE_TYPES = ["None", "Straight", "Left stairs", "Right stairs", "Segments"]
LINE_STYLES = ["None", "Solid", "Dotted", "Dashed", "Long dashed", "Dot-dashed"]
FILL_PATTERNS = ["None", "Solid"]
TICK_FORMATS = ["general", "decimal", "exponential", "power", "scientific", "engineering"]
TICK_FORMAT_NAMES = ["General", "Decimal", "Exponential", "Power", "Scientific", "Engineering"]
TICK_DIRS = ["in", "out", "both"]
AXIS_SCALES = ["linear", "log", "reciprocal", "logit"]
AXIS_SCALE_NAMES = ["Linear", "Logarithmic", "Reciprocal", "Logit"]
SIDES = ["normal", "opposite", "both"]          # which side of the frame something is drawn on
SIDE_NAMES = ["Normal", "Opposite", "Both"]
CUSTOM_TICK_MODES = ["none", "ticks", "both"]   # custom tick positions only, or positions and labels
CUSTOM_TICK_MODE_NAMES = ["None (automatic ticks)", "Ticks only (labels show the value)", "Ticks and labels"]

# Grace set types, and which DataSet members hold the columns after x and y
SET_TYPES = ["xy", "xydx", "xydy", "xydxdx", "xydydy", "xydxdy", "xydxdxdydy"]
SET_TYPE_COLUMNS = {
    "xy": [],
    "xydx": ["dx"],
    "xydy": ["dy"],
    "xydxdx": ["dx", "dx_low"],
    "xydydy": ["dy", "dy_low"],
    "xydxdy": ["dx", "dy"],
    "xydxdxdydy": ["dx", "dx_low", "dy", "dy_low"],
}

# Fill under a curve
FILL_TYPES = ["None", "As polygon", "To baseline"]
BASELINES = ["Zero", "Set minimum", "Set maximum", "Graph minimum", "Graph maximum", "Set average"]

# Annotated values: what to print next to each point
AVALUE_TYPES = ["None", "X", "Y", "X, Y"]

ERRORBAR_PLACES = ["both", "normal", "opposite"]     # both sides / only + side / only - side

# How text is typeset (Project.text_mode):
#   "grace" - Grace codes only (\S, \x, ...), no LaTeX
#   "auto"  - strings with $...$ are typeset by LaTeX, the rest with Grace codes
#   "all"   - every string, including tick labels, is typeset by LaTeX
TEXT_MODES = ["grace", "auto", "all"]
TEXT_MODE_NAMES = ["Grace codes only", "LaTeX for strings containing $…$", "LaTeX for all text (incl. tick labels)"]

# Drawing objects and regions
OBJECT_KINDS = ["text", "line", "box", "ellipse"]
ARROW_TYPES = ["None", "At start", "At end", "Both ends"]
REGION_TYPES = ["inside", "outside", "above", "below", "left", "right"]
REGION_TYPE_NAMES = ["Inside polygon", "Outside polygon", "Above line", "Below line",
                     "Left of line", "Right of line"]

# Page sizes in points (1 point = 1/72 inch)
PAGE_SIZES = {
    "Letter landscape": (792.0, 612.0),
    "Letter portrait": (612.0, 792.0),
    "A4 landscape": (842.0, 595.0),
    "A4 portrait": (595.0, 842.0),
}


def default_set_color(set_index):
    """Grace gives set 0 black, set 1 red, set 2 green, ... (colour table entries 1 to 15)."""
    table_index = set_index % 15 + 1
    return GRACE_COLORS[table_index][1]


# ---------------------------------------------------------------------------
# "Nice" numbers for automatic axis ranges and tick spacing
# ---------------------------------------------------------------------------

def nice_number(value):
    """Round a positive number to 1, 2 or 5 times a power of ten (e.g. 0.37 -> 0.5)."""
    if value <= 0 or not math.isfinite(value):
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10.0 ** exponent)     # between 1 and 10
    if fraction < 1.5:
        nice = 1.0
    elif fraction < 3.0:
        nice = 2.0
    elif fraction < 7.0:
        nice = 5.0
    else:
        nice = 10.0
    return nice * (10.0 ** exponent)


def auto_major(lo, hi, nticks=6):
    """A pleasant major tick spacing that gives roughly `nticks` ticks between lo and hi."""
    span = abs(hi - lo)
    if span == 0 or not math.isfinite(span):
        return 1.0
    return nice_number(span / (nticks - 1))


def nice_range(lo, hi, nticks=6):
    """Widen [lo, hi] outward to multiples of a nice tick step. Returns (lo, hi, step)."""
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        if lo != 0:
            delta = abs(lo) * 0.1
        else:
            delta = 1.0
        lo = lo - delta
        hi = hi + delta
    step = auto_major(lo, hi, nticks)
    new_lo = math.floor(lo / step + 1e-9) * step
    new_hi = math.ceil(hi / step - 1e-9) * step
    return new_lo, new_hi, step


# ---------------------------------------------------------------------------
# Style structs
# ---------------------------------------------------------------------------

class Symbol:
    """How the markers of a data set look."""

    def __init__(self):
        self.shape = 0              # index into SYMBOL_NAMES (0 = no symbol)
        self.size = 1.0
        self.color = "#000000"      # outline colour
        self.alpha = 1.0            # outline opacity, 0..1
        self.fill = 0               # 0 = hollow, 1 = filled
        self.fill_color = "#000000"
        self.fill_alpha = 1.0
        self.linewidth = 1.0
        self.skip = 0               # draw only every (skip+1)-th symbol


class Line:
    """How the connecting line of a data set looks."""

    def __init__(self):
        self.type = 1               # index into LINE_TYPES (1 = straight)
        self.style = 1              # index into LINE_STYLES (1 = solid)
        self.width = 1.0
        self.color = "#000000"
        self.alpha = 1.0


class ErrorBar:
    """How the error bars (dx and/or dy) look."""

    def __init__(self):
        self.show = True
        self.color = "#000000"
        self.alpha = 1.0
        self.width = 1.0
        self.cap = 1.0              # size of the little end caps
        self.place = "both"         # "both", "normal" (only the + side) or "opposite" (only -)


class Fill:
    """Filling the area under (or inside) a curve."""

    def __init__(self):
        self.type = 0               # index into FILL_TYPES: 0 none, 1 polygon, 2 to baseline
        self.baseline = 0           # index into BASELINES (used when type is 2)
        self.color = "#000000"
        self.alpha = 0.3


class AValue:
    """Annotated values: numbers printed next to each point."""

    def __init__(self):
        self.type = 0               # index into AVALUE_TYPES: 0 none, 1 X, 2 Y, 3 X,Y
        self.size = 0.8             # char size
        self.font = ""
        self.color = "#000000"
        self.angle = 0.0
        self.format = "general"     # one of TICK_FORMATS
        self.prec = 3
        self.prepend = ""
        self.append = ""
        self.offset_x = 0.0         # offset from the point, in view units
        self.offset_y = 0.01


class DataSet:
    """One curve: the numbers plus how to draw them.

    Error arrays are None when the set doesn't have them:
        dy      vertical error (upper error if dy_low is also given)
        dy_low  lower vertical error (None = same as dy, i.e. symmetric)
        dx      horizontal error (right error if dx_low is also given)
        dx_low  left horizontal error (None = same as dx)
    """

    def __init__(self, x=None, y=None, dy=None):
        if x is None:
            x = np.zeros(0)
        if y is None:
            y = np.zeros(0)
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.dy = None
        if dy is not None:
            self.dy = np.asarray(dy, dtype=float)
        self.dy_low = None
        self.dx = None
        self.dx_low = None
        self.legend = ""
        self.comment = ""           # free text, e.g. the file the data came from
        self.hidden = False
        self.symbol = Symbol()
        self.line = Line()
        self.errorbar = ErrorBar()
        self.fill = Fill()
        self.avalue = AValue()

    def set_type(self):
        """The Grace set type, e.g. "xydy", from which error arrays are present."""
        text = "xy"
        if self.dx is not None:
            text = text + "dx"
            if self.dx_low is not None:
                text = text + "dx"
        if self.dy is not None:
            text = text + "dy"
            if self.dy_low is not None:
                text = text + "dy"
        if text not in SET_TYPES:
            # Grace has no "xydxdxdy" or "xydxdydy": write the symmetric version
            if self.dx is not None and self.dy is not None:
                text = "xydxdy"
        return text

    def columns(self):
        """All data columns in Grace's order for this set type, e.g. [x, y, dx, dy]."""
        result = [self.x, self.y]
        for name in SET_TYPE_COLUMNS[self.set_type()]:
            result.append(getattr(self, name))
        return result

    def set_errors(self, set_type, error_columns):
        """Store error columns read from a file. error_columns are the columns after x and y."""
        self.dx = None
        self.dx_low = None
        self.dy = None
        self.dy_low = None
        names = SET_TYPE_COLUMNS.get(set_type, [])
        for k in range(len(names)):
            if k < len(error_columns):
                setattr(self, names[k], error_columns[k])       # e.g. self.dy = error_columns[0]

    def error_extent(self, which):
        """(values - lower error, values + upper error) along "x" or "y", or None without errors."""
        n = len(self)
        if which == "x":
            values = self.x[:n]
            plus = self.dx
            minus = self.dx_low
        else:
            values = self.y[:n]
            plus = self.dy
            minus = self.dy_low
        if plus is None or len(plus) < n:
            return None
        if minus is None or len(minus) < n:
            minus = plus
        return values - minus[:n], values + plus[:n]

    def __len__(self):
        """Number of points (len(dataset) works like .size() in C++)."""
        return int(min(len(self.x), len(self.y)))

    def copy(self):
        return copy.deepcopy(self)


class Axis:
    def __init__(self):
        self.min = 0.0
        self.max = 1.0
        self.scale = "linear"       # one of AXIS_SCALES
        self.invert = False
        self.auto_ticks = True      # True: choose the tick spacing automatically
        self.major = 0.2            # major tick spacing (used when auto_ticks is False)
        self.minor = 1              # number of minor ticks between two major ticks
        self.label = ""
        self.label_size = 1.0
        self.label_font = ""        # "" means: use the project default font
        self.show_ticklabels = True
        self.ticklabel_size = 1.0
        self.ticklabel_font = ""
        self.ticklabel_format = "general"
        self.ticklabel_prec = 2
        self.tick_dir = "in"        # "in", "out" or "both"
        self.major_len = 1.0
        self.minor_len = 0.5
        self.major_width = 1.0
        self.minor_width = 1.0
        self.bar_width = 1.0        # width of the axis line itself
        self.mirror = True          # also draw ticks on the opposite side of the frame
        self.grid_major = False
        self.grid_minor = False
        self.grid_color = "#c8c8c8"
        self.enabled = True         # alternate axes start disabled (see Graph)
        # Fine placement (offsets are in view units: 0.01 = 1 % of the short page side)
        self.label_dx = 0.0
        self.label_dy = 0.0
        self.label_angle_auto = True     # True: 0 degrees for x labels, 90 for y labels
        self.label_angle = 0.0
        self.ticklabel_angle = 0.0
        self.ticklabel_dx = 0.0
        self.ticklabel_dy = 0.0
        self.ticklabel_skip = 0          # label only every (skip+1)-th major tick

        # Everything else from xmgrace's axis dialog
        self.bar_on = True               # draw the axis line ("Display axis bar")
        self.bar_color = "#000000"
        self.bar_style = 1               # index into LINE_STYLES
        self.ticks_on = True             # "Display tick marks"
        self.ticks_opposite_only = False # tick marks only on the opposite side (Grace "tick place opposite")
        self.zero_axis = False           # draw the axis at zero of the other axis instead of the frame edge
        self.offset_normal = 0.0         # move the axis away from the frame (view units)
        self.offset_opposite = 0.0
        self.label_color = "#000000"
        self.label_side = "normal"       # one of SIDES
        self.ticklabel_color = "#000000"
        self.ticklabel_side = "normal"
        self.ticklabel_stagger = 0       # 1 = every other label one row further out, ...
        self.ticklabel_start_auto = True # label from the axis start, or from ticklabel_start
        self.ticklabel_start = 0.0
        self.ticklabel_stop_auto = True
        self.ticklabel_stop = 0.0
        self.ticklabel_prepend = ""
        self.ticklabel_append = ""
        self.major_color = "#000000"
        self.minor_color = "#000000"
        self.major_style = 1
        self.minor_style = 1
        self.autotick_divisions = 6      # about how many major ticks automatic spacing aims for
        self.place_rounded = True        # ticks at round values (True) or starting at the axis minimum
        self.custom_ticks = "none"       # one of CUSTOM_TICK_MODES
        self.custom_tick_list = []       # list of [value, label, "major" or "minor"]
        # Tick labels computed from the tick value, e.g. "1240/x" ("" = show the value itself)
        self.ticklabel_formula = ""


class Legend:
    def __init__(self):
        self.show = True
        # Upper-left corner of the legend box, as a fraction of the graph frame (0..1).
        self.x = 0.66
        self.y = 0.95
        self.char_size = 1.0
        self.font = ""
        self.box = True             # draw the border
        self.fill = True            # fill the box background
        self.box_fill = "#ffffff"
        self.box_alpha = 1.0
        # Layout, in units of the legend's character height
        self.row_gap = 0.15         # space between entries
        self.sample_length = 2.2    # length of the line sample
        self.padding = 0.4          # space inside the box
        self.border_width = 1.0
        self.invert = False         # list the sets in reverse order


class Graph:
    """One plot: frame, axes, legend and data sets."""

    def __init__(self):
        # Position on the page in view coordinates: [xmin, ymin, xmax, ymax]
        self.viewport = [0.15, 0.15, 1.15, 0.85]
        self.title = ""
        self.subtitle = ""
        self.title_size = 1.5
        self.subtitle_size = 1.0
        self.title_font = ""
        self.subtitle_font = ""
        self.title_dx = 0.0         # offsets in view units
        self.title_dy = 0.0
        self.title_angle = 0.0
        self.subtitle_dx = 0.0
        self.subtitle_dy = 0.0
        self.subtitle_angle = 0.0
        self.xaxis = Axis()
        self.yaxis = Axis()
        # Alternate axes: drawn on the top / right side, sharing the range of the main axis
        self.alt_xaxis = Axis()
        self.alt_yaxis = Axis()
        self.alt_xaxis.enabled = False
        self.alt_yaxis.enabled = False
        self.alt_xaxis.mirror = False
        self.alt_yaxis.mirror = False
        self.legend = Legend()
        self.sets = []              # list of DataSet
        self.hidden = False
        self.frame_width = 1.0
        self.bg_color = "#ffffff"
        self.bg_alpha = 0.0         # 0 = transparent background
        self.zoom_stack = []        # used by the PZ / PU buttons; not saved to file

    def add_set(self, x, y, dy=None, legend=""):
        """Create a new data set in this graph with Grace's default colour for its index."""
        ds = DataSet(np.array(x, dtype=float), np.array(y, dtype=float))
        if dy is not None:
            ds.dy = np.array(dy, dtype=float)
        ds.legend = legend
        color = default_set_color(len(self.sets))
        ds.line.color = color
        ds.symbol.color = color
        ds.symbol.fill_color = color
        ds.errorbar.color = color
        self.sets.append(ds)
        return ds

    def data_limits(self, which, sets=None):
        """Smallest and largest data value along "x" or "y". Returns (lo, hi) or None.

        If `sets` is None, all visible sets of this graph are used.
        """
        if which == "x":
            axis = self.xaxis
        else:
            axis = self.yaxis

        if sets is None:
            sets = []
            for ds in self.sets:
                if not ds.hidden:
                    sets.append(ds)

        lo = math.inf
        hi = -math.inf
        for ds in sets:
            n = len(ds)
            if n == 0:
                continue
            if which == "x":
                values = ds.x[:n]
            else:
                values = ds.y[:n]
            # Make room for the error bars too
            extent = ds.error_extent(which)
            if extent is not None:
                values = np.concatenate([values, extent[0], extent[1]])
            values = values[np.isfinite(values)]      # drop NaN / inf
            if axis.scale == "log":
                values = values[values > 0]           # a log axis can't show <= 0
            elif axis.scale == "reciprocal":
                values = values[values > 0]           # 1/x: keep one side of zero
            elif axis.scale == "logit":
                values = values[(values > 0) & (values < 1)]   # logit needs 0 < x < 1
            if values.size > 0:
                lo = min(lo, float(values.min()))
                hi = max(hi, float(values.max()))
        if lo > hi:
            return None
        return lo, hi

    def autoscale(self, which="xy", sets=None):
        """Fit the axis ranges to the data. `which` is "x", "y" or "xy"."""
        for letter in which:
            if letter == "x":
                axis = self.xaxis
            else:
                axis = self.yaxis
            limits = self.data_limits(letter, sets)
            if limits is None:
                continue
            if axis.scale == "log":
                lo = 10.0 ** math.floor(math.log10(limits[0]))
                hi = 10.0 ** math.ceil(math.log10(limits[1]))
                if hi <= lo:
                    hi = lo * 10.0
                axis.major = 10.0
            elif axis.scale == "reciprocal" or axis.scale == "logit":
                # Nice round ends don't work well here: use the data range itself
                lo = limits[0]
                hi = limits[1]
                if hi <= lo:
                    hi = lo + 1.0
            else:
                lo, hi, step = nice_range(limits[0], limits[1])
                axis.major = step
            axis.min = lo
            axis.max = hi
            axis.auto_ticks = True


class DrawObject:
    """A text, line, box or ellipse drawn on the page.

    Coordinates are in view units (the page, shorter side = 1) when coords is "view",
    or in data units of graph number `graph` when coords is "world".
    Text uses (x1, y1); the others use both corners / both end points.
    """

    def __init__(self, kind="text"):
        self.kind = kind            # one of OBJECT_KINDS
        self.coords = "view"        # "view" or "world"
        self.graph = 0
        self.x1 = 0.5
        self.y1 = 0.5
        self.x2 = 0.6
        self.y2 = 0.6
        self.text = ""
        self.char_size = 1.0
        self.font = ""
        self.angle = 0.0
        self.just = 0               # text alignment: 0 left, 1 right, 2 centre (Grace numbers)
        self.color = "#000000"
        self.alpha = 1.0
        self.line_width = 1.0
        self.line_style = 1
        self.fill = False
        self.fill_color = "#ffffff"
        self.fill_alpha = 1.0
        self.arrow = 0              # index into ARROW_TYPES
        self.arrow_size = 1.0
        self.hidden = False


class Region:
    """An area of a graph, used to pick points (kill, extract, restrict fits ...).

    points are in data (world) coordinates of graph number `graph`:
    a polygon for "inside"/"outside", two points of a line for the other types.
    """

    def __init__(self):
        self.type = "inside"        # one of REGION_TYPES
        self.graph = 0
        self.points = []            # list of [x, y]
        self.color = "#000000"


def points_in_polygon(x, y, polygon):
    """For every point (x[i], y[i]): is it inside the polygon? (ray casting, works on arrays)"""
    inside = np.zeros(len(x), dtype=bool)
    count = len(polygon)
    for i in range(count):
        x1 = polygon[i][0]
        y1 = polygon[i][1]
        x2 = polygon[(i + 1) % count][0]
        y2 = polygon[(i + 1) % count][1]
        # Does a horizontal ray to the right of the point cross this edge?
        crosses = (y1 > y) != (y2 > y)
        with np.errstate(all="ignore"):
            x_at_y = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside = inside ^ (crosses & (x < x_at_y))      # ^ = exclusive or: flip on each crossing
    return inside


def region_mask(region, x, y):
    """Boolean array: which points (x[i], y[i]) are in the region."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    points = region.points
    if region.type == "inside" or region.type == "outside":
        if len(points) < 3:
            return np.zeros(len(x), dtype=bool)
        inside = points_in_polygon(x, y, points)
        if region.type == "inside":
            return inside
        return np.logical_not(inside)

    if len(points) < 2:
        return np.zeros(len(x), dtype=bool)
    x1 = points[0][0]
    y1 = points[0][1]
    x2 = points[1][0]
    y2 = points[1][1]
    with np.errstate(all="ignore"):
        if region.type == "above" or region.type == "below":
            if x2 == x1:
                return np.zeros(len(x), dtype=bool)
            line_y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)
            if region.type == "above":
                return y > line_y
            return y < line_y
        # left / right of the line
        if y2 == y1:
            return np.zeros(len(x), dtype=bool)
        line_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        if region.type == "left":
            return x < line_x
        return x > line_x


class Project:
    """The whole document: page settings, graphs, drawing objects and regions."""

    def __init__(self):
        self.page_w = 792.0         # page size in points
        self.page_h = 612.0
        self.page_color = "#ffffff"
        self.font_family = "Helvetica"   # default font for all text
        self.graphs = [Graph()]
        self.current = 0            # index of the graph that has the focus
        self.objects = []           # list of DrawObject
        self.regions = []           # list of Region
        self.text_mode = "auto"     # one of TEXT_MODES
        self.latex_preamble = ""    # extra LaTeX lines, e.g. \usepackage{siunitx}
        self.filename = ""          # not saved to file
        self.modified = False       # not saved to file

    def view_w(self):
        """Page width in view coordinates (the shorter page side is 1)."""
        return self.page_w / min(self.page_w, self.page_h)

    def view_h(self):
        return self.page_h / min(self.page_w, self.page_h)

    def cg(self):
        """The current graph."""
        if len(self.graphs) == 0:
            self.graphs.append(Graph())
        if self.current < 0:
            self.current = 0
        if self.current > len(self.graphs) - 1:
            self.current = len(self.graphs) - 1
        return self.graphs[self.current]

    # ----------------------------------------------------------- saving
    def save(self, path):
        data = {"format": "neograce", "version": 1, "project": object_to_dict(self)}
        with open(path, "w") as fh:
            json.dump(data, fh, indent=1)
        self.filename = path
        self.modified = False

    @staticmethod
    def load(path):
        with open(path) as fh:
            data = json.load(fh)
        if "project" in data:
            data = data["project"]
        project = project_from_dict(data)
        project.filename = path
        return project


# ---------------------------------------------------------------------------
# Saving and loading (.ngr files are JSON)
#
# Every object is turned into a dictionary of its member variables.
# When loading, we start from a default-constructed object and copy over the
# members found in the file. Members missing in an old file simply keep their
# default value, so old files keep working when new members are added.
# ---------------------------------------------------------------------------

# Members that only exist while the program runs and are never written to disk.
RUNTIME_ONLY = ["zoom_stack", "filename", "modified"]

# Member structs that are loaded recursively (a member holding one of these
# is filled from a nested dictionary).
STRUCT_CLASSES = (Symbol, Line, ErrorBar, Fill, AValue, Axis, Legend)

# All model classes (written to file as dictionaries of their members)
MODEL_CLASSES = (Symbol, Line, ErrorBar, Fill, AValue, DataSet, Axis, Legend, Graph,
                 DrawObject, Region, Project)

# DataSet members that hold numpy arrays (or None)
ARRAY_MEMBERS = ["x", "y", "dy", "dy_low", "dx", "dx_low"]


def value_to_json(value):
    """Convert one member value to something json can write."""
    if isinstance(value, np.ndarray):
        result = []
        for v in value.astype(float).tolist():
            if math.isfinite(v):
                result.append(v)
            else:
                result.append(None)      # JSON has no NaN; store null
        return result
    if isinstance(value, MODEL_CLASSES):
        return object_to_dict(value)
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            result.append(value_to_json(item))
        return result
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def object_to_dict(obj):
    result = {}
    for name in vars(obj):              # vars(obj) = the object's member variables
        if name in RUNTIME_ONLY:
            continue
        result[name] = value_to_json(getattr(obj, name))
    return result


def json_to_array(values):
    numbers = []
    for v in values:
        if v is None:
            numbers.append(np.nan)
        else:
            numbers.append(v)
    return np.array(numbers, dtype=float)


def fill_object(obj, data):
    """Copy the plain values from `data` into an existing object (unknown keys are ignored)."""
    if data is None:
        return obj
    for name in data:
        if not hasattr(obj, name) or name in RUNTIME_ONLY:
            continue
        value = data[name]
        current = getattr(obj, name)
        if isinstance(current, STRUCT_CLASSES) and isinstance(value, dict):
            # Nested struct (e.g. ds.symbol): fill a fresh default object of the same class
            fresh = type(current)()
            fill_object(fresh, value)
            setattr(obj, name, fresh)
        else:
            setattr(obj, name, value)
    return obj


def dataset_from_dict(data):
    ds = DataSet()
    fill_object(ds, data)
    for name in ARRAY_MEMBERS:
        values = data.get(name)
        if values is None:
            if name == "x" or name == "y":
                setattr(ds, name, np.zeros(0))
            else:
                setattr(ds, name, None)
        else:
            setattr(ds, name, json_to_array(values))
    return ds


def graph_from_dict(data):
    g = Graph()
    fill_object(g, data)
    g.sets = []
    for set_data in data.get("sets", []):
        g.sets.append(dataset_from_dict(set_data))
    g.zoom_stack = []
    return g


def project_from_dict(data):
    project = Project()
    fill_object(project, data)
    project.graphs = []
    for graph_data in data.get("graphs", []):
        project.graphs.append(graph_from_dict(graph_data))
    if len(project.graphs) == 0:
        project.graphs.append(Graph())
    project.objects = []
    for object_data in data.get("objects", []):
        project.objects.append(fill_object(DrawObject(), object_data))
    project.regions = []
    for region_data in data.get("regions", []):
        project.regions.append(fill_object(Region(), region_data))
    return project


# ---------------------------------------------------------------------------
# Undo snapshots
#
# A snapshot is a deep copy of the project, EXCEPT that the numpy arrays are
# shared instead of copied. That keeps undo cheap even for large data sets.
# It is safe because the code never changes an array in place: it always
# builds a new array and assigns it (ds.y = new_values). If you add features,
# keep following that rule.
# ---------------------------------------------------------------------------

def collect_arrays(obj, found):
    """Fill the dictionary `found` with id(array) -> array for every array inside obj."""
    if isinstance(obj, np.ndarray):
        found[id(obj)] = obj
    elif isinstance(obj, list):
        for item in obj:
            collect_arrays(item, found)
    elif isinstance(obj, (DataSet, Graph)):
        for name in vars(obj):
            collect_arrays(getattr(obj, name), found)


def copy_graphs_sharing_arrays(graphs):
    # deepcopy's "memo" dictionary maps id -> object that is already copied.
    # Pre-filling it with the arrays themselves makes deepcopy reuse them.
    memo = {}
    collect_arrays(graphs, memo)
    return copy.deepcopy(graphs, memo)


def snapshot(project):
    snap = {}
    snap["graphs"] = copy_graphs_sharing_arrays(project.graphs)
    snap["current"] = project.current
    snap["page"] = (project.page_w, project.page_h, project.page_color, project.font_family,
                    project.text_mode, project.latex_preamble)
    snap["objects"] = copy.deepcopy(project.objects)
    snap["regions"] = copy.deepcopy(project.regions)
    return snap


def restore(project, snap):
    project.graphs = copy_graphs_sharing_arrays(snap["graphs"])
    project.current = snap["current"]
    page = snap["page"]
    project.page_w = page[0]
    project.page_h = page[1]
    project.page_color = page[2]
    project.font_family = page[3]
    project.text_mode = page[4]
    project.latex_preamble = page[5]
    project.objects = copy.deepcopy(snap["objects"])
    project.regions = copy.deepcopy(snap["regions"])
