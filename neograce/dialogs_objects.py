"""
dialogs_objects.py - drawing objects (Window > Drawing objects) and regions (Edit > Regions).

Drawing objects are texts, lines/arrows, boxes and ellipses on the page.
New objects are placed with the mouse: click a "New" button, then click (text)
or drag (line, box, ellipse) on the page. Objects can be dragged around, and
double-clicking one opens this dialog with it selected.

Regions are areas of a graph (a polygon, or one side of a line). They are drawn
dashed on screen only, and are used to pick points: kill or extract the points
inside, or restrict fits and transformations to them (see RegionChooser).
"""
import copy

import numpy as np
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox, QWidget)

from .dialogs_base import GraceDialog, SetList, make_combo
from .model import ARROW_TYPES, LINE_STYLES, REGION_TYPE_NAMES, REGION_TYPES, Region, region_mask
from .render import view_to_world, world_to_view
from .widgets import ColorCombo, FloatEdit, FontCombo, OpacitySlider, SliderSpin

# The "New" buttons: (button text, canvas mode)
NEW_OBJECT_BUTTONS = [("Text", "place_text"), ("Line", "place_line"), ("Arrow", "place_arrow"),
                      ("Box", "place_box"), ("Ellipse", "place_ellipse")]


def describe_object(index, obj):
    text = "O%d  %s" % (index, obj.kind)
    if obj.kind == "line" and obj.arrow != 0:
        text = "O%d  arrow" % index
    if obj.kind == "text":
        text = text + "  \"" + obj.text + "\""
    if obj.coords == "world":
        text = text + "  (G%d data)" % obj.graph
    if obj.hidden:
        text = text + "  [hidden]"
    return text


# ===========================================================================
# Drawing objects
# ===========================================================================
class DrawingObjectsDialog(GraceDialog):
    title = "Drawing Objects"

    def __init__(self, main):
        super().__init__(main)
        row = QHBoxLayout()
        row.addWidget(QLabel("New:"))
        for text, mode in NEW_OBJECT_BUTTONS:
            button = QPushButton(text)
            button.setProperty("mode", mode)
            button.clicked.connect(self.on_new_button)
            row.addWidget(button)
        row.addStretch(1)
        self.vbox.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("New objects use:"))
        self.new_coords = make_combo(["Page coordinates (stay put)", "Data coordinates of the clicked graph"])
        self.new_coords.currentIndexChanged.connect(self.on_new_coords_changed)
        row.addWidget(self.new_coords, 1)
        self.vbox.addLayout(row)

        self.object_list = QListWidget()
        self.object_list.setMaximumHeight(140)
        self.object_list.currentRowChanged.connect(self.load)
        self.vbox.addWidget(self.object_list)

        grid = QGridLayout()
        # Left column: text properties. Right column: line and fill properties.
        text_box = QGroupBox("Text")
        form = QFormLayout(text_box)
        self.text = QLineEdit()
        self.char_size = SliderSpin(0.1, 6, 0.05, 2)
        self.font = FontCombo()
        self.angle = QSpinBox()
        self.angle.setRange(-360, 360)
        self.just = make_combo(["Left", "Right", "Centre"])
        form.addRow("String:", self.text)
        form.addRow("Size:", self.char_size)
        form.addRow("Font:", self.font)
        form.addRow("Angle:", self.angle)
        form.addRow("Alignment:", self.just)

        line_box = QGroupBox("Line and fill")
        form = QFormLayout(line_box)
        self.line_width = SliderSpin(0, 10, 0.1, 1)
        self.line_style = make_combo(LINE_STYLES)
        self.arrow = make_combo(ARROW_TYPES)
        self.arrow_size = SliderSpin(0.1, 5, 0.05, 2)
        self.fill = QCheckBox("Fill")
        self.fill_color = ColorCombo()
        self.fill_alpha = OpacitySlider()
        form.addRow("Width:", self.line_width)
        form.addRow("Style:", self.line_style)
        form.addRow("Arrow:", self.arrow)
        form.addRow("Arrow size:", self.arrow_size)
        form.addRow(self.fill)
        form.addRow("Fill color:", self.fill_color)
        form.addRow("Fill opacity:", self.fill_alpha)

        common_box = QGroupBox("Position and colour")
        form = QFormLayout(common_box)
        self.color = ColorCombo()
        self.alpha = OpacitySlider()
        self.coords = make_combo(["Page (view)", "Data (world)"])
        self.graph = QComboBox()
        self.x1 = FloatEdit()
        self.y1 = FloatEdit()
        self.x2 = FloatEdit()
        self.y2 = FloatEdit()
        first_row = QHBoxLayout()
        first_row.addWidget(self.x1)
        first_row.addWidget(self.y1)
        second_row = QHBoxLayout()
        second_row.addWidget(self.x2)
        second_row.addWidget(self.y2)
        self.hidden = QCheckBox("Hidden")
        form.addRow("Color:", self.color)
        form.addRow("Opacity:", self.alpha)
        form.addRow("Coordinates:", self.coords)
        form.addRow("Graph:", self.graph)
        form.addRow("x1, y1:", first_row)
        form.addRow("x2, y2:", second_row)
        form.addRow(self.hidden)

        grid.addWidget(text_box, 0, 0)
        grid.addWidget(line_box, 0, 1)
        grid.addWidget(common_box, 1, 0, 1, 2)
        self.vbox.addLayout(grid)
        self.add_buttons(["Apply", "Duplicate", "Delete", "Close"])
        self.resize(640, 720)

    # ----------------------------------------------------------- new objects
    def on_new_button(self):
        mode = self.sender().property("mode")
        self.main.canvas.set_mode(mode)

    def on_new_coords_changed(self, index):
        if index == 1:
            self.main.canvas.new_object_coords = "world"
        else:
            self.main.canvas.new_object_coords = "view"

    # ----------------------------------------------------------- list and form
    def selected_index(self):
        row = self.object_list.currentRow()
        if row >= 0 and row < len(self.project().objects):
            return row
        return -1

    def select_object(self, index):
        self.refresh()
        self.object_list.setCurrentRow(index)
        self.load()

    def refresh(self):
        project = self.project()
        keep = self.object_list.currentRow()
        self.object_list.blockSignals(True)
        self.object_list.clear()
        for index in range(len(project.objects)):
            self.object_list.addItem(describe_object(index, project.objects[index]))
        if keep >= self.object_list.count():
            keep = self.object_list.count() - 1
        self.object_list.setCurrentRow(keep)
        self.object_list.blockSignals(False)
        self.graph.clear()
        for gi in range(len(project.graphs)):
            self.graph.addItem("G%d" % gi)
        self.load()

    def load(self):
        index = self.selected_index()
        if index < 0:
            return
        obj = self.project().objects[index]
        self.text.setText(obj.text)
        self.char_size.setValue(obj.char_size)
        self.font.set_font_spec(obj.font)
        self.angle.setValue(int(round(obj.angle)))
        self.just.setCurrentIndex(obj.just)
        self.line_width.setValue(obj.line_width)
        self.line_style.setCurrentIndex(obj.line_style)
        self.arrow.setCurrentIndex(obj.arrow)
        self.arrow_size.setValue(obj.arrow_size)
        self.fill.setChecked(obj.fill)
        self.fill_color.setColor(obj.fill_color)
        self.fill_alpha.setValue(obj.fill_alpha)
        self.color.setColor(obj.color)
        self.alpha.setValue(obj.alpha)
        if obj.coords == "world":
            self.coords.setCurrentIndex(1)
        else:
            self.coords.setCurrentIndex(0)
        if obj.graph < self.graph.count():
            self.graph.setCurrentIndex(obj.graph)
        self.x1.setValue(obj.x1)
        self.y1.setValue(obj.y1)
        self.x2.setValue(obj.x2)
        self.y2.setValue(obj.y2)
        self.hidden.setChecked(obj.hidden)

        # Only show the fields that matter for this kind of object
        is_text = obj.kind == "text"
        for widget in (self.text, self.char_size, self.font, self.angle, self.just):
            widget.setEnabled(is_text)
        for widget in (self.line_width, self.line_style):
            widget.setEnabled(not is_text)
        for widget in (self.arrow, self.arrow_size):
            widget.setEnabled(obj.kind == "line")
        for widget in (self.fill, self.fill_color, self.fill_alpha):
            widget.setEnabled(obj.kind == "box" or obj.kind == "ellipse")
        self.x2.setEnabled(not is_text)
        self.y2.setEnabled(not is_text)

    def apply(self):
        index = self.selected_index()
        if index < 0:
            return self.warn("Select an object first.")
        project = self.project()
        obj = project.objects[index]
        try:
            x1 = self.x1.value()
            y1 = self.y1.value()
            x2 = self.x2.value()
            y2 = self.y2.value()
        except ValueError:
            return self.warn("The coordinates must be numbers.")

        if self.coords.currentIndex() == 1:
            new_coords = "world"
        else:
            new_coords = "view"
        new_graph = max(0, self.graph.currentIndex())

        # Switching between page and data coordinates: convert the numbers so the object stays put
        if new_coords != obj.coords or (new_coords == "world" and new_graph != obj.graph):
            if obj.coords == "world":
                old_graph = project.graphs[min(obj.graph, len(project.graphs) - 1)]
                x1, y1 = world_to_view(old_graph, x1, y1)
                x2, y2 = world_to_view(old_graph, x2, y2)
            if new_coords == "world":
                graph = project.graphs[new_graph]
                x1, y1 = view_to_world(graph, x1, y1)
                x2, y2 = view_to_world(graph, x2, y2)

        obj.coords = new_coords
        obj.graph = new_graph
        obj.x1 = x1
        obj.y1 = y1
        obj.x2 = x2
        obj.y2 = y2
        obj.text = self.text.text()
        obj.char_size = self.char_size.value()
        obj.font = self.font.font_spec()
        obj.angle = float(self.angle.value())
        obj.just = self.just.currentIndex()
        obj.line_width = self.line_width.value()
        obj.line_style = self.line_style.currentIndex()
        obj.arrow = self.arrow.currentIndex()
        obj.arrow_size = self.arrow_size.value()
        obj.fill = self.fill.isChecked()
        obj.fill_color = self.fill_color.color()
        obj.fill_alpha = self.fill_alpha.value()
        obj.color = self.color.color()
        obj.alpha = self.alpha.value()
        obj.hidden = self.hidden.isChecked()
        self.main.changed()

    def on_duplicate(self):
        index = self.selected_index()
        if index < 0:
            return
        project = self.project()
        twin = copy.deepcopy(project.objects[index])
        # Shift the copy a little so it doesn't sit exactly on top of the original
        if twin.coords == "view":
            twin.x1 = twin.x1 + 0.02
            twin.y1 = twin.y1 - 0.02
            twin.x2 = twin.x2 + 0.02
            twin.y2 = twin.y2 - 0.02
        project.objects.append(twin)
        self.main.changed()
        self.object_list.setCurrentRow(len(project.objects) - 1)

    def on_delete(self):
        index = self.selected_index()
        if index < 0:
            return
        del self.project().objects[index]
        self.main.changed()


# ===========================================================================
# Regions
# ===========================================================================
class RegionsDialog(GraceDialog):
    title = "Regions"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Regions (shown dashed on screen, never printed):"))
        self.region_list = QListWidget()
        self.region_list.setMaximumHeight(110)
        self.vbox.addWidget(self.region_list)

        box = QGroupBox("New region in the current graph")
        form = QFormLayout(box)
        self.region_type = make_combo(REGION_TYPE_NAMES)
        define_row = QHBoxLayout()
        mouse_button = QPushButton("Define with mouse")
        mouse_button.clicked.connect(self.define_with_mouse)
        define_row.addWidget(mouse_button)
        define_row.addStretch(1)
        self.points_edit = QLineEdit()
        self.points_edit.setPlaceholderText("or type points:  x1 y1; x2 y2; x3 y3 ...")
        typed_button = QPushButton("Add typed points")
        typed_button.clicked.connect(self.add_typed_region)
        form.addRow("Type:", self.region_type)
        form.addRow(define_row)
        form.addRow(QLabel("Polygon: click the corners, double-click to finish.\nLine types: click two points."))
        form.addRow(self.points_edit)
        form.addRow(typed_button)
        self.vbox.addWidget(box)

        box = QGroupBox("Use the selected region on sets of the current graph")
        layout = QGridLayout(box)
        self.set_list = SetList(main, True)
        self.set_list.setMaximumHeight(120)
        layout.addWidget(self.set_list, 0, 0, 1, 4)
        operations = [("Kill points inside", "kill_inside"), ("Kill points outside", "kill_outside"),
                      ("Copy inside to new set", "extract"), ("Count points", "count")]
        for k in range(len(operations)):
            button = QPushButton(operations[k][0])
            button.setProperty("operation", operations[k][1])
            button.clicked.connect(self.on_operation)
            layout.addWidget(button, 1, k)
        self.result = QLabel("")
        layout.addWidget(self.result, 2, 0, 1, 4)
        self.vbox.addWidget(box)
        self.add_buttons(["Delete region", "Close"])
        self.resize(560, 560)

    def refresh(self):
        project = self.project()
        keep = self.region_list.currentRow()
        self.region_list.clear()
        for k in range(len(project.regions)):
            region = project.regions[k]
            name = REGION_TYPE_NAMES[REGION_TYPES.index(region.type)]
            self.region_list.addItem("R%d  %s  in G%d  (%d points)" % (k, name, region.graph, len(region.points)))
        if keep < 0 and self.region_list.count() > 0:
            keep = 0
        if keep >= self.region_list.count():
            keep = self.region_list.count() - 1
        self.region_list.setCurrentRow(keep)
        self.set_list.populate(project.current, project.cg())

    def define_with_mouse(self):
        self.main.canvas.start_region(REGION_TYPES[self.region_type.currentIndex()])

    def add_region(self, region_type, graph_index, points):
        """Called by the main window when the mouse finished a region, and by add_typed_region."""
        region = Region()
        region.type = region_type
        region.graph = graph_index
        region.points = points
        self.project().regions.append(region)
        self.main.changed()
        self.region_list.setCurrentRow(len(self.project().regions) - 1)

    def add_typed_region(self):
        region_type = REGION_TYPES[self.region_type.currentIndex()]
        points = []
        try:
            for part in self.points_edit.text().split(";"):
                words = part.replace(",", " ").split()
                if len(words) == 0:
                    continue
                if len(words) != 2:
                    return self.warn("Each point needs two numbers: x y")
                points.append([float(words[0]), float(words[1])])
        except ValueError:
            return self.warn("The points must be numbers.")
        if region_type == "inside" or region_type == "outside":
            if len(points) < 3:
                return self.warn("A polygon needs at least 3 points.")
        elif len(points) != 2:
            return self.warn("A line region needs exactly 2 points.")
        self.add_region(region_type, self.project().current, points)

    def on_delete_region(self):
        row = self.region_list.currentRow()
        if row >= 0 and row < len(self.project().regions):
            del self.project().regions[row]
            self.main.changed()

    def on_operation(self):
        operation = self.sender().property("operation")
        project = self.project()
        row = self.region_list.currentRow()
        if row < 0 or row >= len(project.regions):
            return self.warn("Select a region first.")
        region = project.regions[row]
        g = project.cg()
        total = 0
        changed = False
        for si in self.set_list.selected():
            ds = g.sets[si]
            n = len(ds)
            inside = region_mask(region, ds.x[:n], ds.y[:n])
            total = total + int(inside.sum())
            if operation == "kill_inside":
                self.keep_points(ds, np.logical_not(inside))
                changed = True
            elif operation == "kill_outside":
                self.keep_points(ds, inside)
                changed = True
            elif operation == "extract":
                new_set = g.add_set(ds.x[:n][inside], ds.y[:n][inside])
                errors = []
                for name in ("dx", "dx_low", "dy", "dy_low"):
                    column = getattr(ds, name)
                    if column is not None:
                        errors.append(column[:n][inside])
                new_set.set_errors(ds.set_type(), errors)
                new_set.comment = "R%d of S%d" % (row, si)
                changed = True
        self.result.setText("%d point(s) inside R%d." % (total, row))
        if changed:
            self.main.changed()

    def keep_points(self, ds, keep):
        """Keep only the points where keep is True (new arrays, never in place)."""
        n = len(ds)
        ds.x = ds.x[:n][keep]
        ds.y = ds.y[:n][keep]
        for name in ("dx", "dx_low", "dy", "dy_low"):
            column = getattr(ds, name)
            if column is not None:
                setattr(ds, name, column[:n][keep])
