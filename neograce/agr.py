"""
agr.py - reading and writing Grace (.agr) project files.

An .agr file is plain text. Lines starting with "@" are commands, for example
    @    s0 symbol color 2
    @    xaxis  label "Time (s)"
and lines with numbers are data, ended by a line with "&".

READING: every command line is split into lower-case words (commas and brackets
removed) plus the text between quotes, and then checked with plain if/elif.
Commands we don't use are simply ignored.

WRITING: we write the commands Grace needs to show the same plot. Opacity,
which Grace doesn't have, is stored in a "#neograce {...}" comment line at the
end. Grace ignores comments; NeoGrace reads it back.
"""
import json
import math

import numpy as np

from .model import GRACE_COLORS, DataSet, DrawObject, Graph, Project, Region, default_set_color
from .textfmt import GRACE_FONTS

# Grace tick label format names -> ours
# Grace region type names -> ours
REGION_TYPES_IN = {"polyi": "inside", "polyo": "outside", "above": "above", "below": "below",
                   "left": "left", "right": "right"}
REGION_TYPES_OUT = {"inside": "polyi", "outside": "polyo", "above": "above", "below": "below",
                    "left": "left", "right": "right"}

# Grace drawing object names -> ours
OBJECT_KINDS_IN = {"string": "text", "line": "line", "box": "box", "ellipse": "ellipse"}
OBJECT_KINDS_OUT = {"text": "string", "line": "line", "box": "box", "ellipse": "ellipse"}

FORMAT_NAMES = {"general": "general", "decimal": "decimal", "exponential": "exponential",
                "power": "power", "scientific": "scientific", "engineering": "engineering",
                "computing": "general"}
SCALE_NAMES_OUT = {"linear": "Normal", "log": "Logarithmic", "reciprocal": "Reciprocal", "logit": "Logit"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def to_float(text, default=0.0):
    try:
        return float(text)
    except ValueError:
        return default


def to_int(text, default=0):
    try:
        return int(float(text))
    except ValueError:
        return default


def split_command(line):
    """'@    xaxis  label "Time (s)"' -> (['xaxis', 'label'], 'Time (s)').

    Returns the words before the first quote (lower case, commas and brackets
    removed) and the first quoted string (or None). Some lines have two quoted
    strings, e.g.  @map font 0 to "Times-Roman", "Times-Roman"; we use the first.
    """
    text = line[1:]                          # drop the "@"
    quoted = None
    first = text.find('"')
    if first >= 0:
        second = text.find('"', first + 1)
        if second > first:
            quoted = text[first + 1:second]
        else:
            quoted = text[first + 1:]
        text = text[:first]
    for ch in ",()":
        text = text.replace(ch, " ")
    words = text.lower().split()
    return words, quoted


def is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def is_on(word):
    return word == "on" or word == "true"


class AgrReader:
    """Holds the state while reading one file (current graph, colour table, ...)."""

    def __init__(self):
        self.project = Project()
        self.project.graphs = []
        self.project.font_family = "Times-Roman"     # Grace's default font 0

        self.colors = {}                  # colour number -> "#rrggbb"
        for i in range(len(GRACE_COLORS)):
            self.colors[i] = GRACE_COLORS[i][1]
        self.fonts = {}                   # font number -> font name
        for i in range(len(GRACE_FONTS)):
            self.fonts[i] = GRACE_FONTS[i]

        self.graphs = {}                  # graph number -> Graph
        self.sets = {}                    # (graph number, set number) -> DataSet
        self.legend_positions = {}        # graph number -> [loctype, x, y]
        self.extra = {}                   # contents of the "#neograce" line

        self.current_graph = 0            # set by "@with g0"
        self.target = (0, 0)              # set by "@target G0.S1"
        self.set_type = "xy"              # set by "@type xydy"
        self.rows = []                    # data rows read since the last "&"
        self.objects = []                 # drawing objects ("@with string", "@with line", ...)
        self.current_object = None
        self.regions = {}                 # region number -> [Region, is on]

    # ---------------------------------------------------------- lookups
    def graph(self, number):
        if number not in self.graphs:
            self.graphs[number] = Graph()
        return self.graphs[number]

    def dataset(self, graph_number, set_number):
        key = (graph_number, set_number)
        if key not in self.sets:
            ds = DataSet()
            color = default_set_color(set_number)
            ds.line.color = color
            ds.symbol.color = color
            ds.symbol.fill_color = color
            ds.errorbar.color = color
            self.sets[key] = ds
        return self.sets[key]

    def color(self, word):
        number = to_int(word)
        if number in self.colors:
            return self.colors[number]
        return "#000000"

    def font(self, word, quoted):
        """Fonts can be given as a number ("4") or as a name in quotes."""
        if quoted:
            return quoted
        number = to_int(word, -1)
        if number in self.fonts:
            return self.fonts[number]
        return "Times-Roman"

    # ---------------------------------------------------------- main loop
    def read(self, path):
        with open(path, "r", errors="replace") as fh:
            lines = fh.read().splitlines()
        for raw in lines:
            line = raw.strip()
            if line == "":
                continue
            if line.startswith("#neograce "):
                try:
                    self.extra = json.loads(line[len("#neograce "):])
                except ValueError:
                    pass
                continue
            if line.startswith("#"):
                continue
            if line.startswith("&"):
                self.finish_data()
                continue
            if line.startswith("@"):
                words, quoted = split_command(line)
                if len(words) > 0:
                    self.command(words, quoted)
                continue
            # A data line
            values = []
            for token in line.split():
                values.append(to_float(token, np.nan))
            if len(values) > 0:
                self.rows.append(values)
        self.finish_data()
        return self.build_project()

    def finish_data(self):
        """Store the data rows collected so far into the target set."""
        if len(self.rows) == 0:
            return
        graph_number = self.target[0]
        set_number = self.target[1]
        self.graph(graph_number)
        ds = self.dataset(graph_number, set_number)

        columns = 0
        for row in self.rows:
            columns = max(columns, len(row))
        a = np.full((len(self.rows), columns), np.nan)
        for i in range(len(self.rows)):
            for j in range(len(self.rows[i])):
                a[i, j] = self.rows[i][j]

        if columns == 1:
            ds.x = np.arange(len(a), dtype=float)
            ds.y = a[:, 0].copy()
        else:
            ds.x = a[:, 0].copy()
            ds.y = a[:, 1].copy()
            # The columns after x and y are error columns; the set type says which
            error_columns = []
            for k in range(2, columns):
                error_columns.append(a[:, k].copy())
            ds.set_errors(self.set_type, error_columns)
        self.rows = []

    # ---------------------------------------------------------- commands
    def command(self, w, quoted):
        first = w[0]
        count = len(w)
        project = self.project

        # ---- commands that are not about a single graph
        if first == "target" and count >= 2:
            self.finish_data()
            # "g0.s1" -> (0, 1)
            parts = w[1].replace("g", "").replace("s", "").split(".")
            self.target = (to_int(parts[0]), to_int(parts[1]))
            return
        if first == "type" and count == 2:
            self.set_type = w[1]
            return
        if first == "with" and count >= 2:
            if w[1] in OBJECT_KINDS_IN:
                # "@with line": the following "@    line ..." commands describe a new object
                self.current_object = DrawObject(OBJECT_KINDS_IN[w[1]])
                self.objects.append(self.current_object)
            else:
                self.current_graph = to_int(w[1][1:])
                self.graph(self.current_graph)
            return
        if first in OBJECT_KINDS_IN:
            if self.current_object is not None:
                self.object_command(self.current_object, w[1:], quoted)
            return
        if first == "link" and count == 4 and w[1].startswith("r"):
            # "@link r0 to g0"
            self.region(to_int(w[1][1:]))[0].graph = to_int(w[3][1:])
            return
        if first.startswith("r") and first[1:].isdigit():
            self.region_command(self.region(to_int(first[1:])), w[1:])
            return
        if first.startswith("g") and first[1:].isdigit():
            number = to_int(first[1:])
            if count == 2 and (w[1] == "on" or w[1] == "off"):
                self.graph(number).hidden = w[1] == "off"
            elif count == 3 and w[1] == "hidden":
                self.graph(number).hidden = w[2] == "true"
            return
        if first == "page" and count == 4 and w[1] == "size":
            project.page_w = to_float(w[2], 792.0)
            project.page_h = to_float(w[3], 612.0)
            return
        if first == "map" and count >= 3:
            if w[1] == "font" and quoted is not None:
                self.fonts[to_int(w[2])] = quoted
            elif w[1] == "color" and count >= 7:
                r = to_int(w[4])
                g = to_int(w[5])
                b = to_int(w[6])
                self.colors[to_int(w[2])] = "#%02x%02x%02x" % (r, g, b)
            return
        if first == "default" and count >= 3 and w[1] == "font":
            project.font_family = self.font(w[2], None)
            return
        if first == "background" and count >= 3 and w[1] == "color":
            project.page_color = self.color(w[2])
            return

        # ---- set properties: "s0 symbol color 2"
        if first.startswith("s") and first[1:].isdigit():
            ds = self.dataset(self.current_graph, to_int(first[1:]))
            self.set_command(ds, w[1:], quoted)
            return

        # ---- everything else belongs to the current graph
        g = self.graph(self.current_graph)
        if first == "world" and count == 5:
            g.xaxis.min = to_float(w[1])
            g.yaxis.min = to_float(w[2])
            g.xaxis.max = to_float(w[3])
            g.yaxis.max = to_float(w[4])
        elif first == "world" and count == 3:
            # old style: "world xmin 0"
            if w[1] == "xmin":
                g.xaxis.min = to_float(w[2])
            elif w[1] == "xmax":
                g.xaxis.max = to_float(w[2])
            elif w[1] == "ymin":
                g.yaxis.min = to_float(w[2])
            elif w[1] == "ymax":
                g.yaxis.max = to_float(w[2])
        elif first == "view" and count == 5:
            g.viewport = [to_float(w[1]), to_float(w[2]), to_float(w[3]), to_float(w[4])]
        elif first == "view" and count == 3:
            names = ["xmin", "ymin", "xmax", "ymax"]
            if w[1] in names:
                g.viewport[names.index(w[1])] = to_float(w[2])
        elif first == "title" or first == "subtitle":
            self.title_command(g, first, w, quoted)
        elif (first == "xaxes" or first == "yaxes") and count == 3:
            if first == "xaxes":
                axis = g.xaxis
            else:
                axis = g.yaxis
            if w[1] == "scale":
                if w[2].startswith("log") and w[2] != "logit":
                    axis.scale = "log"
                elif w[2] == "reciprocal":
                    axis.scale = "reciprocal"
                elif w[2] == "logit":
                    axis.scale = "logit"
                else:
                    axis.scale = "linear"
            elif w[1] == "invert":
                axis.invert = is_on(w[2])
        elif first == "xaxis" or first == "yaxis" or first == "altxaxis" or first == "altyaxis":
            if first == "xaxis":
                axis = g.xaxis
            elif first == "yaxis":
                axis = g.yaxis
            elif first == "altxaxis":
                axis = g.alt_xaxis
            else:
                axis = g.alt_yaxis
            if count == 2 and (w[1] == "on" or w[1] == "off"):
                axis.enabled = w[1] == "on"
            else:
                self.axis_command(axis, w[1:], quoted)
        elif first == "legend":
            self.legend_command(g, w[1:], quoted)
        elif first == "frame" and count == 3:
            if w[1] == "linewidth":
                g.frame_width = to_float(w[2], 1.0)
        elif first == "frame" and count == 4 and w[1] == "background":
            if w[2] == "color":
                g.bg_color = self.color(w[3])
            elif w[2] == "pattern":
                if to_int(w[3]) > 0:
                    g.bg_alpha = 1.0
                else:
                    g.bg_alpha = 0.0

    def title_command(self, g, which, w, quoted):
        count = len(w)
        if count == 1 and quoted is not None:
            setattr(g, which, quoted)                         # g.title = "..."
        elif count == 3 and w[1] == "size":
            setattr(g, which + "_size", to_float(w[2], 1.0))
        elif count >= 2 and w[1] == "font":
            word = ""
            if count >= 3:
                word = w[2]
            setattr(g, which + "_font", self.font(word, quoted))

    def axis_command(self, axis, w, quoted):
        """w is the part after "xaxis", e.g. ['tick', 'major', '50']."""
        count = len(w)
        if count == 0:
            return
        if self.axis_extra_command(axis, w, quoted):
            return
        if w[0] == "label":
            if count == 1 and quoted is not None:
                axis.label = quoted
            elif count == 4 and w[1] == "char" and w[2] == "size":
                axis.label_size = to_float(w[3], 1.0)
            elif count >= 2 and w[1] == "font":
                word = ""
                if count >= 3:
                    word = w[2]
                axis.label_font = self.font(word, quoted)
            elif count == 3 and w[1] == "layout" and w[2] == "perp":
                # perpendicular to the axis: Grace's way of saying "rotate the label"
                axis.label_angle_auto = False
                axis.label_angle = -1.0          # replaced in build_project (depends on x or y)
        elif w[0] == "bar" and count == 3 and w[1] == "linewidth":
            axis.bar_width = to_float(w[2], 1.0)
        elif w[0] == "tick":
            if count == 2 and (w[1] == "in" or w[1] == "out" or w[1] == "both"):
                axis.tick_dir = w[1]
            elif count == 3 and w[1] == "place" and w[2] in ("both", "normal", "opposite"):
                axis.mirror = w[2] == "both"
            elif count == 3 and w[1] == "major":
                axis.major = to_float(w[2], 1.0)
                axis.auto_ticks = False
            elif count == 4 and w[1] == "minor" and w[2] == "ticks":
                axis.minor = to_int(w[3], 1)
            elif count == 4 and (w[1] == "major" or w[1] == "minor"):
                major = w[1] == "major"
                if w[2] == "grid":
                    if major:
                        axis.grid_major = is_on(w[3])
                    else:
                        axis.grid_minor = is_on(w[3])
                elif w[2] == "size":
                    if major:
                        axis.major_len = to_float(w[3], 1.0)
                    else:
                        axis.minor_len = to_float(w[3], 0.5)
                elif w[2] == "linewidth":
                    if major:
                        axis.major_width = to_float(w[3], 1.0)
                    else:
                        axis.minor_width = to_float(w[3], 1.0)
        elif w[0] == "ticklabel":
            if count == 2 and (w[1] == "on" or w[1] == "off"):
                axis.show_ticklabels = w[1] == "on"
            elif count == 4 and w[1] == "char" and w[2] == "size":
                axis.ticklabel_size = to_float(w[3], 1.0)
            elif count >= 2 and w[1] == "font":
                word = ""
                if count >= 3:
                    word = w[2]
                axis.ticklabel_font = self.font(word, quoted)
            elif count == 3 and w[1] == "format":
                if w[2] in FORMAT_NAMES:
                    axis.ticklabel_format = FORMAT_NAMES[w[2]]
                else:
                    axis.ticklabel_format = "general"
            elif count == 3 and w[1] == "prec":
                axis.ticklabel_prec = to_int(w[2], 2)
            elif count == 2 and w[1] == "formula" and quoted is not None:
                axis.ticklabel_formula = quoted
            elif count == 3 and w[1] == "angle":
                axis.ticklabel_angle = to_float(w[2])
            elif count == 3 and w[1] == "skip":
                axis.ticklabel_skip = to_int(w[2])

    def axis_extra_command(self, axis, w, quoted):
        """The rest of xmgrace's axis settings. Returns True if the command was handled."""
        count = len(w)
        first = w[0]
        if first == "type" and count == 3 and w[1] == "zero":
            axis.zero_axis = w[2] == "true"
        elif first == "offset" and count == 3:
            axis.offset_normal = to_float(w[1])
            axis.offset_opposite = to_float(w[2])
        elif first == "bar" and count == 2 and (w[1] == "on" or w[1] == "off"):
            axis.bar_on = w[1] == "on"
        elif first == "bar" and count == 3 and w[1] == "color":
            axis.bar_color = self.color(w[2])
        elif first == "bar" and count == 3 and w[1] == "linestyle":
            axis.bar_style = min(to_int(w[2], 1), 5)
        elif first == "label" and count == 3 and w[1] == "color":
            axis.label_color = self.color(w[2])
        elif first == "label" and count == 3 and w[1] == "place" and w[2] in ("normal", "opposite", "both"):
            axis.label_side = w[2]
        elif first == "tick" and count == 2 and (w[1] == "on" or w[1] == "off"):
            axis.ticks_on = w[1] == "on"
        elif first == "tick" and count == 3 and w[1] == "place" and w[2] == "opposite":
            axis.ticks_opposite_only = True
            axis.mirror = False
        elif first == "tick" and count == 3 and w[1] == "default":
            axis.autotick_divisions = to_int(w[2], 6)
        elif first == "tick" and count == 4 and w[1] == "place" and w[2] == "rounded":
            axis.place_rounded = w[3] == "true"
        elif first == "tick" and count == 4 and (w[1] == "major" or w[1] == "minor") and w[2] == "color":
            if w[1] == "major":
                axis.major_color = self.color(w[3])
            else:
                axis.minor_color = self.color(w[3])
        elif first == "tick" and count == 4 and (w[1] == "major" or w[1] == "minor") and w[2] == "linestyle":
            if w[1] == "major":
                axis.major_style = min(to_int(w[3], 1), 5)
            else:
                axis.minor_style = min(to_int(w[3], 1), 5)
        elif first == "tick" and count == 4 and w[1] == "spec" and w[2] == "type":
            if w[3] in ("none", "ticks", "both"):
                axis.custom_ticks = w[3]
        elif first == "tick" and count == 3 and w[1] == "spec":
            pass                                   # number of custom ticks: the entries follow
        elif first == "tick" and count == 4 and (w[1] == "major" or w[1] == "minor") and is_number(w[2]):
            # custom tick: "tick major 3, 0.5" = tick number 3 is a major tick at 0.5
            self.custom_tick(axis, to_int(w[2]))[0] = to_float(w[3])
            self.custom_tick(axis, to_int(w[2]))[2] = w[1]
        elif first == "ticklabel" and count == 2 and is_number(w[1]) and quoted is not None:
            # custom label: 'ticklabel 3, "π"'
            self.custom_tick(axis, to_int(w[1]))[1] = quoted
        elif first == "ticklabel" and count == 3 and w[1] == "color":
            axis.ticklabel_color = self.color(w[2])
        elif first == "ticklabel" and count == 3 and w[1] == "place" and w[2] in ("normal", "opposite", "both"):
            axis.ticklabel_side = w[2]
        elif first == "ticklabel" and count == 3 and w[1] == "stagger":
            axis.ticklabel_stagger = to_int(w[2])
        elif first == "ticklabel" and count == 4 and (w[1] == "start" or w[1] == "stop") and w[2] == "type":
            if w[1] == "start":
                axis.ticklabel_start_auto = w[3] == "auto"
            else:
                axis.ticklabel_stop_auto = w[3] == "auto"
        elif first == "ticklabel" and count == 3 and (w[1] == "start" or w[1] == "stop") and is_number(w[2]):
            if w[1] == "start":
                axis.ticklabel_start = to_float(w[2])
            else:
                axis.ticklabel_stop = to_float(w[2])
        elif first == "ticklabel" and count == 2 and w[1] == "prepend" and quoted is not None:
            axis.ticklabel_prepend = quoted
        elif first == "ticklabel" and count == 2 and w[1] == "append" and quoted is not None:
            axis.ticklabel_append = quoted
        else:
            return False
        return True

    def custom_tick(self, axis, number):
        """The custom tick entry [value, label, kind] with this number, created if needed."""
        while len(axis.custom_tick_list) <= number:
            axis.custom_tick_list.append([0.0, "", "major"])
        return axis.custom_tick_list[number]

    def legend_command(self, g, w, quoted):
        count = len(w)
        legend = g.legend
        number = self.current_graph
        if number not in self.legend_positions:
            self.legend_positions[number] = ["view", None, None]
        position = self.legend_positions[number]

        if count == 1 and (w[0] == "on" or w[0] == "off"):
            legend.show = w[0] == "on"
        elif count == 2 and w[0] == "loctype":
            position[0] = w[1]
        elif count == 2 and is_number(w[0]) and is_number(w[1]):
            # "legend 0.67, 0.86"  (the comma was removed by split_command)
            position[1] = to_float(w[0])
            position[2] = to_float(w[1])
        elif count == 3 and w[0] == "char" and w[1] == "size":
            legend.char_size = to_float(w[2], 1.0)
        elif count >= 1 and w[0] == "font":
            word = ""
            if count >= 2:
                word = w[1]
            legend.font = self.font(word, quoted)
        elif count == 3 and w[0] == "box" and w[1] == "linestyle":
            legend.box = to_int(w[2]) > 0
        elif count == 4 and w[0] == "box" and w[1] == "fill" and w[2] == "pattern":
            legend.fill = to_int(w[3]) > 0
        elif count == 4 and w[0] == "box" and w[1] == "fill" and w[2] == "color":
            legend.box_fill = self.color(w[3])

    def set_command(self, ds, w, quoted):
        """w is the part after "s0", e.g. ['symbol', 'color', '2']."""
        count = len(w)
        if count == 0:
            return
        what = w[0]
        if what == "legend" and quoted is not None:
            ds.legend = quoted
        elif what == "comment" and quoted is not None:
            ds.comment = quoted
        elif what == "hidden" and count == 2:
            ds.hidden = w[1] == "true"
        elif what == "symbol":
            if count == 2:
                ds.symbol.shape = min(to_int(w[1]), 10)
            elif count == 3 and w[1] == "size":
                ds.symbol.size = to_float(w[2], 1.0)
            elif count == 3 and w[1] == "color":
                ds.symbol.color = self.color(w[2])
            elif count == 3 and w[1] == "linewidth":
                ds.symbol.linewidth = to_float(w[2], 1.0)
            elif count == 3 and w[1] == "skip":
                ds.symbol.skip = to_int(w[2])
            elif count == 4 and w[1] == "fill" and w[2] == "pattern":
                if to_int(w[3]) > 0:
                    ds.symbol.fill = 1
                else:
                    ds.symbol.fill = 0
            elif count == 4 and w[1] == "fill" and w[2] == "color":
                ds.symbol.fill_color = self.color(w[3])
        elif what == "line" and count == 3:
            if w[1] == "type":
                ds.line.type = min(to_int(w[2]), 4)
            elif w[1] == "linestyle":
                style = to_int(w[2], 1)
                if style > 5:
                    style = 3                 # Grace has more dash styles than we do
                ds.line.style = style
            elif w[1] == "linewidth":
                ds.line.width = to_float(w[2], 1.0)
            elif w[1] == "color":
                ds.line.color = self.color(w[2])
        elif what == "errorbar":
            if count == 2 and (w[1] == "on" or w[1] == "off"):
                ds.errorbar.show = w[1] == "on"
            elif count == 3 and w[1] == "color":
                ds.errorbar.color = self.color(w[2])
            elif count == 3 and w[1] == "size":
                ds.errorbar.cap = to_float(w[2], 1.0)
            elif count == 3 and w[1] == "linewidth":
                ds.errorbar.width = to_float(w[2], 1.0)
            elif count == 3 and w[1] == "place" and w[2] in ("both", "normal", "opposite"):
                ds.errorbar.place = w[2]
        elif what == "fill" and count == 3:
            if w[1] == "type":
                ds.fill.type = min(to_int(w[2]), 2)
            elif w[1] == "color":
                ds.fill.color = self.color(w[2])
        elif what == "baseline" and count == 3 and w[1] == "type":
            ds.fill.baseline = min(to_int(w[2]), 5)
        elif what == "avalue":
            self.avalue_command(ds, w[1:], quoted)

    def avalue_command(self, ds, w, quoted):
        """w is the part after "s0 avalue"."""
        av = ds.avalue
        count = len(w)
        if count == 1 and w[0] == "off":
            av.type = 0
        elif count == 1 and w[0] == "on":
            if av.type == 0:
                av.type = 2
        elif count == 2 and w[0] == "type":
            # Grace: 0 none, 1 X, 2 Y, 3 X,Y (4 string and 5 Z are not supported -> Y)
            grace_type = to_int(w[1], 2)
            if grace_type > 3:
                grace_type = 2
            av.grace_type = grace_type          # applied in build_project if avalue is on
        elif count == 3 and w[0] == "char" and w[1] == "size":
            av.size = to_float(w[2], 1.0)
        elif count >= 1 and w[0] == "font":
            word = ""
            if count >= 2:
                word = w[1]
            av.font = self.font(word, quoted)
        elif count == 2 and w[0] == "color":
            av.color = self.color(w[1])
        elif count == 2 and w[0] == "rot":
            av.angle = to_float(w[1])
        elif count == 2 and w[0] == "format":
            if w[1] in FORMAT_NAMES:
                av.format = FORMAT_NAMES[w[1]]
        elif count == 2 and w[0] == "prec":
            av.prec = to_int(w[1], 3)
        elif count == 1 and w[0] == "prepend" and quoted is not None:
            av.prepend = quoted
        elif count == 1 and w[0] == "append" and quoted is not None:
            av.append = quoted
        elif count == 3 and w[0] == "offset":
            av.offset_x = to_float(w[1])
            av.offset_y = to_float(w[2])

    def object_command(self, obj, w, quoted):
        """w is the part after "string" / "line" / "box" / "ellipse"."""
        count = len(w)
        if count == 0:
            return
        numbers = True
        for word in w:
            if not is_number(word):
                numbers = False
        if numbers and count == 2:
            obj.x1 = to_float(w[0])                    # text position
            obj.y1 = to_float(w[1])
        elif numbers and count == 4:
            obj.x1 = to_float(w[0])
            obj.y1 = to_float(w[1])
            obj.x2 = to_float(w[2])
            obj.y2 = to_float(w[3])
        elif count == 1 and (w[0] == "on" or w[0] == "off"):
            obj.hidden = w[0] == "off"
        elif count == 1 and w[0].startswith("g") and w[0][1:].isdigit():
            obj.graph = to_int(w[0][1:])               # "line g0": world coordinates of graph 0
        elif count == 2 and w[0] == "loctype":
            if w[1] == "world":
                obj.coords = "world"
            else:
                obj.coords = "view"
        elif count == 1 and w[0] == "def" and quoted is not None:
            obj.text = quoted
        elif count == 2 and w[0] == "color":
            obj.color = self.color(w[1])
        elif count == 2 and w[0] == "rot":
            obj.angle = to_float(w[1])
        elif count >= 1 and w[0] == "font":
            word = ""
            if count >= 2:
                word = w[1]
            obj.font = self.font(word, quoted)
        elif count == 2 and w[0] == "just":
            obj.just = to_int(w[1]) % 4
            if obj.just == 3:
                obj.just = 0
        elif count == 3 and w[0] == "char" and w[1] == "size":
            obj.char_size = to_float(w[2], 1.0)
        elif count == 2 and w[0] == "linewidth":
            obj.line_width = to_float(w[1], 1.0)
        elif count == 2 and w[0] == "linestyle":
            obj.line_style = min(to_int(w[1], 1), 5)
        elif count == 2 and w[0] == "arrow":
            obj.arrow = min(to_int(w[1]), 3)
        elif count == 3 and w[0] == "arrow" and w[1] == "length":
            obj.arrow_size = to_float(w[2], 1.0)
        elif count == 3 and w[0] == "fill" and w[1] == "color":
            obj.fill_color = self.color(w[2])
        elif count == 3 and w[0] == "fill" and w[1] == "pattern":
            obj.fill = to_int(w[2]) > 0

    def region(self, number):
        """[Region, is_on] for region number, created on first use."""
        if number not in self.regions:
            self.regions[number] = [Region(), False]
        return self.regions[number]

    def region_command(self, entry, w):
        region = entry[0]
        count = len(w)
        if count == 1 and (w[0] == "on" or w[0] == "off"):
            entry[1] = w[0] == "on"
        elif count == 2 and w[0] == "type" and w[1] in REGION_TYPES_IN:
            region.type = REGION_TYPES_IN[w[1]]
        elif count == 5 and w[0] == "line":
            region.points = [[to_float(w[1]), to_float(w[2])], [to_float(w[3]), to_float(w[4])]]
        elif count == 3 and w[0] == "xy":
            region.points.append([to_float(w[1]), to_float(w[2])])
        elif count == 2 and w[0] == "color":
            region.color = self.color(w[1])

    # ---------------------------------------------------------- final assembly
    def build_project(self):
        from .render import to_t          # imported here because render.py needs Qt

        # Put the sets into their graphs in order (skip sets without data)
        set_keys = sorted(self.sets)
        for key in set_keys:
            ds = self.sets[key]
            if len(ds) > 0:
                self.graph(key[0]).sets.append(ds)

        # Grace stores the legend position in view (page) or world coordinates;
        # we store it relative to the graph frame.
        for number in self.legend_positions:
            loctype, lx, ly = self.legend_positions[number]
            if lx is None:
                continue
            g = self.graphs[number]
            if loctype == "world":
                g.legend.x = float(to_t(lx, g.xaxis))
                g.legend.y = float(to_t(ly, g.yaxis))
            else:
                vx0 = g.viewport[0]
                vy0 = g.viewport[1]
                vx1 = g.viewport[2]
                vy1 = g.viewport[3]
                if vx1 > vx0 and vy1 > vy0:
                    g.legend.x = (lx - vx0) / (vx1 - vx0)
                    g.legend.y = (ly - vy0) / (vy1 - vy0)

        # "label layout perp": horizontal y labels, vertical x labels
        for number in self.graphs:
            g = self.graphs[number]
            for axis, perpendicular in ((g.xaxis, 90.0), (g.alt_xaxis, 90.0), (g.yaxis, 0.0), (g.alt_yaxis, 0.0)):
                if not axis.label_angle_auto and axis.label_angle == -1.0:
                    axis.label_angle = perpendicular

        # Annotated values: Grace stores "on/off" and "type" separately
        for key in self.sets:
            av = self.sets[key].avalue
            if av.type != 0 and hasattr(av, "grace_type"):
                av.type = av.grace_type
            if hasattr(av, "grace_type"):
                del av.grace_type

        graph_numbers = sorted(self.graphs)
        for number in graph_numbers:
            self.project.graphs.append(self.graphs[number])
        if len(self.project.graphs) == 0:
            self.project.graphs.append(Graph())

        # Graph numbers in the file may have gaps (g0, g2): convert them to list positions
        for obj in self.objects:
            if obj.graph in graph_numbers:
                obj.graph = graph_numbers.index(obj.graph)
            self.project.objects.append(obj)
        for number in sorted(self.regions):
            region = self.regions[number][0]
            is_on = self.regions[number][1]
            if not is_on:
                continue
            if region.type in ("inside", "outside") and len(region.points) < 3:
                continue
            if region.type not in ("inside", "outside") and len(region.points) < 2:
                continue
            if region.graph in graph_numbers:
                region.graph = graph_numbers.index(region.graph)
            self.project.regions.append(region)

        self.apply_extra(graph_numbers)
        return self.project

    def apply_extra(self, graph_numbers):
        """Apply values from the "#neograce" line, e.g. {"g0.s1": {"symbol.alpha": 0.4}}."""
        for key in self.extra:
            if key == "project":
                values = self.extra[key]
                for path in values:
                    set_by_path(self.project, path, values[path])
                continue
            if key.startswith("o"):
                # drawing object: "o3"
                number = to_int(key[1:], -1)
                if number >= 0 and number < len(self.project.objects):
                    values = self.extra[key]
                    for path in values:
                        set_by_path(self.project.objects[number], path, values[path])
                continue
            # key is "g0" or "g0.s1"
            parts = key.split(".")
            graph_number = to_int(parts[0][1:], -1)
            if graph_number not in graph_numbers:
                continue
            target = self.project.graphs[graph_numbers.index(graph_number)]
            if len(parts) > 1:
                set_index = to_int(parts[1][1:], -1)
                if set_index < 0 or set_index >= len(target.sets):
                    continue
                target = target.sets[set_index]
            values = self.extra[key]
            for path in values:
                set_by_path(target, path, values[path])


def set_by_path(obj, path, value):
    """set_by_path(ds, "symbol.alpha", 0.4) does ds.symbol.alpha = 0.4."""
    names = path.split(".")
    for name in names[:-1]:
        obj = getattr(obj, name, None)
        if obj is None:
            return
    if hasattr(obj, names[-1]):
        setattr(obj, names[-1], value)


def get_by_path(obj, path):
    for name in path.split("."):
        obj = getattr(obj, name)
    return obj


def read_agr(path):
    reader = AgrReader()
    return reader.read(path)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

# Values Grace can't store; they go into the "#neograce" comment line.
EXTRA_SET_VALUES = ["symbol.alpha", "symbol.fill_alpha", "line.alpha", "errorbar.alpha", "fill.alpha"]
EXTRA_GRAPH_VALUES = ["bg_alpha", "legend.box_alpha", "legend.x", "legend.y",
                      "legend.row_gap", "legend.sample_length", "legend.padding", "legend.border_width",
                      "legend.invert", "title_dx", "title_dy", "title_angle",
                      "subtitle_dx", "subtitle_dy", "subtitle_angle"]
# Fine placement of every axis label (Grace has no exact equivalent)
for _axis in ("xaxis", "yaxis", "alt_xaxis", "alt_yaxis"):
    for _field in ("label_dx", "label_dy", "label_angle_auto", "label_angle",
                   "ticklabel_dx", "ticklabel_dy", "ticklabel_angle"):
        EXTRA_GRAPH_VALUES.append(_axis + "." + _field)


def quote(text):
    """Grace strings are in double quotes and can't contain double quotes."""
    return '"' + str(text).replace('"', "''") + '"'


def fixed(value):
    return "%.6f" % float(value)


def on_off(flag):
    if flag:
        return "on"
    return "off"


class AgrWriter:
    def __init__(self, project):
        self.project = project
        # Colour and font tables start with Grace's defaults; new ones get appended
        self.colors = []
        self.color_names = []
        for name, hex_color in GRACE_COLORS:
            self.colors.append(hex_color)
            self.color_names.append(name)
        self.fonts = list(GRACE_FONTS)

    def color_index(self, hex_color):
        if not hex_color:
            hex_color = "#000000"
        hex_color = hex_color.lower()
        for i in range(len(self.colors)):
            if self.colors[i].lower() == hex_color:
                return i
        self.colors.append(hex_color)
        self.color_names.append("color" + str(len(self.colors) - 1))
        return len(self.colors) - 1

    def font_index(self, spec):
        if not spec:
            spec = self.project.font_family
        if not spec:
            spec = "Times-Roman"
        if spec not in self.fonts:
            self.fonts.append(spec)
        return self.fonts.index(spec)

    def write(self, path):
        # The body is built first, because it may add colours/fonts to the tables
        body = []
        extra = {}
        self.write_regions(body)
        self.write_objects(body, extra)
        extra["project"] = {"text_mode": self.project.text_mode, "latex_preamble": self.project.latex_preamble}
        for gi in range(len(self.project.graphs)):
            self.write_graph(body, extra, gi)
        data = self.write_data()
        default_font = self.font_index(self.project.font_family)
        page_color = self.color_index(self.project.page_color)
        head = self.write_header(default_font, page_color)

        with open(path, "w") as fh:
            for line in head:
                fh.write(line + "\n")
            for line in body:
                fh.write(line + "\n")
            for line in data:
                fh.write(line + "\n")
            fh.write("#neograce " + json.dumps(extra, separators=(",", ":")) + "\n")

    def write_header(self, default_font, page_color):
        p = self.project
        lines = ["# Grace project file", "# written by NeoGrace", "#", "@version 50125",
                 "@page size %d, %d" % (round(p.page_w), round(p.page_h)),
                 "@page scroll 5%", "@page inout 5%", "@link page off"]
        for i in range(len(self.fonts)):
            lines.append('@map font %d to "%s", "%s"' % (i, self.fonts[i], self.fonts[i]))
        for i in range(len(self.colors)):
            c = self.colors[i]
            r = int(c[1:3], 16)
            g = int(c[3:5], 16)
            b = int(c[5:7], 16)
            lines.append('@map color %d to (%d, %d, %d), "%s"' % (i, r, g, b, self.color_names[i]))
        lines.append("@reference date 0")
        lines.append("@date wrap off")
        lines.append("@date wrap year 1950")
        lines.append("@default linewidth 1.0")
        lines.append("@default linestyle 1")
        lines.append("@default color 1")
        lines.append("@default pattern 1")
        lines.append("@default font %d" % default_font)
        lines.append("@default char size 1.000000")
        lines.append("@default symbol size 1.000000")
        lines.append('@default sformat "%.8g"')
        lines.append("@background color %d" % page_color)
        lines.append("@page background fill on")
        lines.append("@timestamp off")
        return lines

    def write_graph(self, out, extra, gi):
        from .render import compute_ticks     # imported here because render.py needs Qt
        g = self.project.graphs[gi]
        out.append("@g%d on" % gi)
        if g.hidden:
            out.append("@g%d hidden true" % gi)
        else:
            out.append("@g%d hidden false" % gi)
        out.append("@g%d type XY" % gi)
        out.append("@with g%d" % gi)
        out.append("@    world %.10g, %.10g, %.10g, %.10g" % (g.xaxis.min, g.yaxis.min, g.xaxis.max, g.yaxis.max))
        out.append("@    view %s, %s, %s, %s" % (fixed(g.viewport[0]), fixed(g.viewport[1]),
                                                  fixed(g.viewport[2]), fixed(g.viewport[3])))
        out.append("@    title " + quote(g.title))
        out.append("@    title font %d" % self.font_index(g.title_font))
        out.append("@    title size " + fixed(g.title_size))
        out.append("@    title color 1")
        out.append("@    subtitle " + quote(g.subtitle))
        out.append("@    subtitle font %d" % self.font_index(g.subtitle_font))
        out.append("@    subtitle size " + fixed(g.subtitle_size))
        out.append("@    subtitle color 1")

        for name in ("x", "y"):
            if name == "x":
                axis = g.xaxis
            else:
                axis = g.yaxis
            out.append("@    %saxes scale %s" % (name, SCALE_NAMES_OUT[axis.scale]))
            out.append("@    %saxes invert %s" % (name, on_off(axis.invert)))

        self.write_axis(out, "xaxis", g.xaxis, g.xaxis)
        self.write_axis(out, "yaxis", g.yaxis, g.yaxis)
        self.write_axis(out, "altxaxis", g.alt_xaxis, g.xaxis)
        self.write_axis(out, "altyaxis", g.alt_yaxis, g.yaxis)

        legend = g.legend
        vx0 = g.viewport[0]
        vy0 = g.viewport[1]
        vx1 = g.viewport[2]
        vy1 = g.viewport[3]
        out.append("@    legend " + on_off(legend.show))
        out.append("@    legend loctype view")
        out.append("@    legend %.6f, %.6f" % (vx0 + legend.x * (vx1 - vx0), vy0 + legend.y * (vy1 - vy0)))
        out.append("@    legend box color 1")
        out.append("@    legend box pattern 1")
        out.append("@    legend box linewidth 1.0")
        out.append("@    legend box linestyle %d" % int(legend.box))
        out.append("@    legend box fill color %d" % self.color_index(legend.box_fill))
        out.append("@    legend box fill pattern %d" % int(legend.fill))
        out.append("@    legend font %d" % self.font_index(legend.font))
        out.append("@    legend char size " + fixed(legend.char_size))
        out.append("@    legend color 1")
        out.append("@    frame type 0")
        out.append("@    frame linestyle 1")
        out.append("@    frame linewidth %.1f" % g.frame_width)
        out.append("@    frame color 1")
        out.append("@    frame pattern 1")
        out.append("@    frame background color %d" % self.color_index(g.bg_color))
        if g.bg_alpha > 0:
            out.append("@    frame background pattern 1")
        else:
            out.append("@    frame background pattern 0")

        graph_extra = {}
        for path in EXTRA_GRAPH_VALUES:
            graph_extra[path] = get_by_path(g, path)
        extra["g%d" % gi] = graph_extra

        for si in range(len(g.sets)):
            self.write_set(out, extra, gi, si, g.sets[si])

    def write_axis(self, out, name, axis, main_axis):
        """Write one axis block. Alternate axes use the range of their main axis."""
        from .render import axis_with_range_of, compute_ticks
        p = "@    " + name + "  "
        out.append(p + on_off(axis.enabled))
        if not axis.enabled and name.startswith("alt"):
            return
        step = compute_ticks(axis_with_range_of(axis, main_axis))[2]   # Grace needs an explicit spacing
        out.append(p + "type zero " + str(axis.zero_axis).lower())
        out.append(p + "offset %.6f , %.6f" % (axis.offset_normal, axis.offset_opposite))
        out.append(p + "bar " + on_off(axis.bar_on))
        out.append(p + "bar color %d" % self.color_index(axis.bar_color))
        out.append(p + "bar linestyle %d" % axis.bar_style)
        out.append(p + "bar linewidth %.1f" % axis.bar_width)
        out.append(p + "label " + quote(axis.label))
        out.append(p + "label char size " + fixed(axis.label_size))
        out.append(p + "label font %d" % self.font_index(axis.label_font))
        out.append(p + "label color %d" % self.color_index(axis.label_color))
        if not name.startswith("alt"):
            out.append(p + "label place " + axis.label_side)
        out.append(p + "tick " + on_off(axis.ticks_on))
        out.append(p + "tick major %.10g" % step)
        out.append(p + "tick minor ticks %d" % axis.minor)
        out.append(p + "tick default %d" % axis.autotick_divisions)
        out.append(p + "tick place rounded " + str(axis.place_rounded).lower())
        out.append(p + "tick " + axis.tick_dir)
        out.append(p + "tick major size " + fixed(axis.major_len))
        out.append(p + "tick major color %d" % self.color_index(axis.major_color))
        out.append(p + "tick major linewidth %.1f" % axis.major_width)
        out.append(p + "tick major linestyle %d" % axis.major_style)
        out.append(p + "tick major grid " + on_off(axis.grid_major))
        out.append(p + "tick minor color %d" % self.color_index(axis.minor_color))
        out.append(p + "tick minor linewidth %.1f" % axis.minor_width)
        out.append(p + "tick minor linestyle %d" % axis.minor_style)
        out.append(p + "tick minor grid " + on_off(axis.grid_minor))
        out.append(p + "tick minor size " + fixed(axis.minor_len))
        out.append(p + "ticklabel " + on_off(axis.show_ticklabels))
        out.append(p + "ticklabel format " + axis.ticklabel_format)
        out.append(p + "ticklabel prec %d" % axis.ticklabel_prec)
        out.append(p + "ticklabel formula " + quote(self.grace_formula(axis.ticklabel_formula)))
        out.append(p + "ticklabel angle %d" % round(axis.ticklabel_angle))
        out.append(p + "ticklabel stagger %d" % axis.ticklabel_stagger)
        out.append(p + "ticklabel prepend " + quote(axis.ticklabel_prepend))
        out.append(p + "ticklabel append " + quote(axis.ticklabel_append))
        if axis.ticklabel_start_auto:
            out.append(p + "ticklabel start type auto")
        else:
            out.append(p + "ticklabel start type spec")
        out.append(p + "ticklabel start %.10g" % axis.ticklabel_start)
        if axis.ticklabel_stop_auto:
            out.append(p + "ticklabel stop type auto")
        else:
            out.append(p + "ticklabel stop type spec")
        out.append(p + "ticklabel stop %.10g" % axis.ticklabel_stop)
        out.append(p + "ticklabel skip %d" % axis.ticklabel_skip)
        out.append(p + "ticklabel char size " + fixed(axis.ticklabel_size))
        out.append(p + "ticklabel font %d" % self.font_index(axis.ticklabel_font))
        out.append(p + "ticklabel color %d" % self.color_index(axis.ticklabel_color))
        if name.startswith("alt"):
            out.append(p + "tick place opposite")
            out.append(p + "ticklabel place opposite")
            out.append(p + "label place opposite")
        else:
            if axis.ticks_opposite_only:
                out.append(p + "tick place opposite")
            elif axis.mirror:
                out.append(p + "tick place both")
            else:
                out.append(p + "tick place normal")
            out.append(p + "ticklabel place " + axis.ticklabel_side)
        # Custom ticks ("Special" tab)
        out.append(p + "tick spec type " + axis.custom_ticks)
        if axis.custom_ticks != "none":
            out.append(p + "tick spec %d" % len(axis.custom_tick_list))
            for k in range(len(axis.custom_tick_list)):
                entry = axis.custom_tick_list[k]
                out.append(p + "tick %s %d, %.10g" % (entry[2], k, float(entry[0])))
                if axis.custom_ticks == "both":
                    out.append(p + "ticklabel %d, %s" % (k, quote(entry[1])))

    def grace_formula(self, formula):
        """Our tick label formulas use x; Grace uses $t."""
        result = ""
        i = 0
        while i < len(formula):
            c = formula[i]
            # replace a stand-alone "x" (not part of a name like "exp")
            before_ok = i == 0 or not (formula[i - 1].isalnum() or formula[i - 1] == "_")
            after_ok = i == len(formula) - 1 or not (formula[i + 1].isalnum() or formula[i + 1] == "_")
            if c == "x" and before_ok and after_ok:
                result = result + "$t"
            else:
                result = result + c
            i += 1
        return result

    def write_regions(self, out):
        for number in range(len(self.project.regions)):
            region = self.project.regions[number]
            out.append("@r%d on" % number)
            out.append("@link r%d to g%d" % (number, region.graph))
            out.append("@r%d type %s" % (number, REGION_TYPES_OUT[region.type]))
            out.append("@r%d linestyle 1" % number)
            out.append("@r%d linewidth 1.0" % number)
            out.append("@r%d color %d" % (number, self.color_index(region.color)))
            if region.type == "inside" or region.type == "outside":
                for point in region.points:
                    out.append("@r%d xy %.10g, %.10g" % (number, point[0], point[1]))
            else:
                p = region.points
                out.append("@r%d line %.10g, %.10g, %.10g, %.10g" % (number, p[0][0], p[0][1], p[1][0], p[1][1]))

    def write_objects(self, out, extra):
        for number in range(len(self.project.objects)):
            obj = self.project.objects[number]
            name = OBJECT_KINDS_OUT[obj.kind]
            p = "@    " + name + " "
            out.append("@with " + name)
            out.append(p + on_off(not obj.hidden))
            if obj.coords == "world":
                out.append(p + "loctype world")
                out.append(p + "g%d" % obj.graph)
            else:
                out.append(p + "loctype view")
            if obj.kind == "text":
                out.append(p + "%.10g, %.10g" % (obj.x1, obj.y1))
                out.append(p + "color %d" % self.color_index(obj.color))
                out.append(p + "rot %d" % round(obj.angle))
                out.append(p + "font %d" % self.font_index(obj.font))
                out.append(p + "just %d" % obj.just)
                out.append(p + "char size " + fixed(obj.char_size))
                out.append(p + "def " + quote(obj.text))
            else:
                out.append(p + "%.10g, %.10g, %.10g, %.10g" % (obj.x1, obj.y1, obj.x2, obj.y2))
                out.append(p + "linestyle %d" % obj.line_style)
                out.append(p + "linewidth %.1f" % obj.line_width)
                out.append(p + "color %d" % self.color_index(obj.color))
                if obj.kind == "line":
                    out.append(p + "arrow %d" % obj.arrow)
                    out.append(p + "arrow type 0")
                    out.append(p + "arrow length " + fixed(obj.arrow_size))
                    out.append(p + "arrow layout 1.000000, 1.000000")
                else:
                    out.append(p + "fill color %d" % self.color_index(obj.fill_color))
                    out.append(p + "fill pattern %d" % int(obj.fill))
                out.append("@" + name + " def")
            if obj.alpha != 1.0 or obj.fill_alpha != 1.0:
                extra["o%d" % number] = {"alpha": obj.alpha, "fill_alpha": obj.fill_alpha}

    def write_set(self, out, extra, gi, si, ds):
        p = "@    s%d " % si
        if ds.hidden:
            out.append(p + "hidden true")
        else:
            out.append(p + "hidden false")
        out.append(p + "type " + ds.set_type())
        out.append(p + "symbol %d" % ds.symbol.shape)
        out.append(p + "symbol size " + fixed(ds.symbol.size))
        out.append(p + "symbol color %d" % self.color_index(ds.symbol.color))
        out.append(p + "symbol pattern 1")
        out.append(p + "symbol fill color %d" % self.color_index(ds.symbol.fill_color))
        out.append(p + "symbol fill pattern %d" % ds.symbol.fill)
        out.append(p + "symbol linewidth %.1f" % ds.symbol.linewidth)
        out.append(p + "symbol linestyle 1")
        out.append(p + "symbol skip %d" % ds.symbol.skip)
        out.append(p + "line type %d" % ds.line.type)
        out.append(p + "line linestyle %d" % ds.line.style)
        out.append(p + "line linewidth %.1f" % ds.line.width)
        out.append(p + "line color %d" % self.color_index(ds.line.color))
        out.append(p + "line pattern 1")
        out.append(p + "errorbar " + on_off(ds.errorbar.show))
        out.append(p + "errorbar place " + ds.errorbar.place)
        out.append(p + "errorbar color %d" % self.color_index(ds.errorbar.color))
        out.append(p + "errorbar pattern 1")
        out.append(p + "errorbar size " + fixed(ds.errorbar.cap))
        out.append(p + "errorbar linewidth %.1f" % ds.errorbar.width)
        out.append(p + "errorbar linestyle 1")
        out.append(p + "errorbar riser linewidth %.1f" % ds.errorbar.width)
        out.append(p + "baseline type %d" % ds.fill.baseline)
        out.append(p + "fill type %d" % ds.fill.type)
        out.append(p + "fill rule 0")
        out.append(p + "fill color %d" % self.color_index(ds.fill.color))
        out.append(p + "fill pattern 1")
        av = ds.avalue
        out.append(p + "avalue " + on_off(av.type != 0))
        if av.type != 0:
            out.append(p + "avalue type %d" % av.type)
        else:
            out.append(p + "avalue type 2")
        out.append(p + "avalue char size " + fixed(av.size))
        out.append(p + "avalue font %d" % self.font_index(av.font))
        out.append(p + "avalue color %d" % self.color_index(av.color))
        out.append(p + "avalue rot %d" % round(av.angle))
        out.append(p + "avalue format " + av.format)
        out.append(p + "avalue prec %d" % av.prec)
        out.append(p + "avalue prepend " + quote(av.prepend))
        out.append(p + "avalue append " + quote(av.append))
        out.append(p + "avalue offset %.6f , %.6f" % (av.offset_x, av.offset_y))
        out.append(p + "comment " + quote(ds.comment))
        out.append(p + "legend  " + quote(ds.legend))

        set_extra = {}
        needed = False
        for path in EXTRA_SET_VALUES:
            value = get_by_path(ds, path)
            set_extra[path] = value
            if value != 1.0:
                needed = True
        if needed:
            extra["g%d.s%d" % (gi, si)] = set_extra

    def write_data(self):
        lines = []
        for gi in range(len(self.project.graphs)):
            g = self.project.graphs[gi]
            for si in range(len(g.sets)):
                ds = g.sets[si]
                lines.append("@target G%d.S%d" % (gi, si))
                lines.append("@type " + ds.set_type())
                columns = ds.columns()
                for i in range(len(ds)):
                    words = []
                    for column in columns:
                        v = column[i]
                        if math.isfinite(v):
                            words.append("%.10g" % v)
                        else:
                            words.append("nan")
                    lines.append(" ".join(words))
                lines.append("&")
        return lines


def write_agr(project, path):
    writer = AgrWriter(project)
    writer.write(path)
