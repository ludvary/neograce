"""
dialogs_plot.py - the "Plot" menu dialogs: how sets, axes, graphs and the page look.
Also the "Arrange graphs" dialog.
"""
import copy

from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .dialogs_base import GraceDialog, SetList, make_combo
from .model import (AXIS_SCALE_NAMES, AXIS_SCALES, CUSTOM_TICK_MODE_NAMES, CUSTOM_TICK_MODES, SIDE_NAMES, SIDES,
                    TICK_FORMAT_NAMES, TEXT_MODE_NAMES, TEXT_MODES, AVALUE_TYPES, BASELINES, ERRORBAR_PLACES, FILL_PATTERNS, FILL_TYPES, LINE_STYLES, LINE_TYPES,
                    PAGE_SIZES, SYMBOL_NAMES, TICK_DIRS, TICK_FORMATS, Graph)
from .widgets import ColorCombo, FloatEdit, FontCombo, OpacitySlider, SliderSpin


PLACEMENT_TIP = ("Tip: click the label on the page, then drag it or use the arrow keys\n"
                 "(Shift = 10×, Alt = ÷5) and [ ] to rotate (Shift = 15°, Alt = 0.1°).")


def offset_spin():
    """A number box for fine offsets in view units (0.001 = 0.1 % of the short page side)."""
    spin = QDoubleSpinBox()
    spin.setRange(-2.0, 2.0)
    spin.setSingleStep(0.001)
    spin.setDecimals(4)
    return spin


def angle_spin():
    spin = QDoubleSpinBox()
    spin.setRange(-360.0, 360.0)
    spin.setSingleStep(0.5)
    spin.setDecimals(1)
    spin.setSuffix("°")
    return spin


def pair_row(first, second):
    row = QHBoxLayout()
    row.addWidget(first)
    row.addWidget(second)
    return row


# ===========================================================================
# Set appearance
# ===========================================================================
class SetAppearanceDialog(GraceDialog):
    title = "Set Appearance"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Select set:"))
        self.set_list = SetList(main, True)
        self.set_list.itemSelectionChanged.connect(self.load)
        self.vbox.addWidget(self.set_list)
        tabs = QTabWidget()
        self.vbox.addWidget(tabs)

        # ---- "Main" tab
        page = QWidget()
        grid = QGridLayout(page)

        symbol_box = QGroupBox("Symbol properties")
        form = QFormLayout(symbol_box)
        self.symbol_type = make_combo(SYMBOL_NAMES)
        self.symbol_size = SliderSpin(0, 10, 0.05, 2)
        self.symbol_color = ColorCombo()
        self.symbol_alpha = OpacitySlider()
        form.addRow("Type:", self.symbol_type)
        form.addRow("Size:", self.symbol_size)
        form.addRow("Color:", self.symbol_color)
        form.addRow("Opacity:", self.symbol_alpha)

        line_box = QGroupBox("Line properties")
        form = QFormLayout(line_box)
        self.line_type = make_combo(LINE_TYPES)
        self.line_style = make_combo(LINE_STYLES)
        self.line_width = SliderSpin(0, 10, 0.1, 1)
        self.line_color = ColorCombo()
        self.line_alpha = OpacitySlider()
        form.addRow("Type:", self.line_type)
        form.addRow("Style:", self.line_style)
        form.addRow("Width:", self.line_width)
        form.addRow("Color:", self.line_color)
        form.addRow("Opacity:", self.line_alpha)

        legend_box = QGroupBox("Legend")
        form = QFormLayout(legend_box)
        self.legend = QLineEdit()
        form.addRow("String:", self.legend)

        display_box = QGroupBox("Display options")
        row = QHBoxLayout(display_box)
        self.hidden = QCheckBox("Hidden")
        row.addWidget(self.hidden)
        row.addStretch(1)

        grid.addWidget(symbol_box, 0, 0)
        grid.addWidget(line_box, 0, 1)
        grid.addWidget(legend_box, 1, 0, 1, 2)
        grid.addWidget(display_box, 2, 0, 1, 2)
        tabs.addTab(page, "Main")

        # ---- "Symbols" tab
        page = QWidget()
        form = QFormLayout(page)
        self.fill = make_combo(FILL_PATTERNS)
        self.fill_color = ColorCombo()
        self.fill_alpha = OpacitySlider()
        self.symbol_linewidth = SliderSpin(0, 10, 0.1, 1)
        self.symbol_skip = QSpinBox()
        self.symbol_skip.setRange(0, 100000)
        same_color = QPushButton("Fill colour = symbol colour")
        same_color.clicked.connect(self.copy_symbol_color_to_fill)
        form.addRow("Fill pattern:", self.fill)
        form.addRow("Fill color:", self.fill_color)
        form.addRow("", same_color)
        form.addRow("Fill opacity:", self.fill_alpha)
        form.addRow("Outline width:", self.symbol_linewidth)
        form.addRow("Symbols to skip:", self.symbol_skip)
        tabs.addTab(page, "Symbols")

        # ---- "Error bars" tab
        page = QWidget()
        form = QFormLayout(page)
        self.errorbar_show = QCheckBox("Draw error bars (sets with dy)")
        self.errorbar_color = ColorCombo()
        self.errorbar_alpha = OpacitySlider()
        self.errorbar_width = SliderSpin(0, 10, 0.1, 1)
        self.errorbar_cap = SliderSpin(0, 5, 0.05, 2)
        self.errorbar_place = make_combo(["Both sides", "Only + side", "Only − side"])
        form.addRow(self.errorbar_show)
        form.addRow("Placement:", self.errorbar_place)
        form.addRow("Color:", self.errorbar_color)
        form.addRow("Opacity:", self.errorbar_alpha)
        form.addRow("Line width:", self.errorbar_width)
        form.addRow("Cap size:", self.errorbar_cap)
        tabs.addTab(page, "Error bars")

        # ---- "Fill" tab
        page = QWidget()
        form = QFormLayout(page)
        self.fill_type = make_combo(FILL_TYPES)
        self.fill_baseline = make_combo(BASELINES)
        self.area_color = ColorCombo()
        self.area_alpha = OpacitySlider()
        form.addRow("Fill:", self.fill_type)
        form.addRow("Baseline:", self.fill_baseline)
        form.addRow("Color:", self.area_color)
        form.addRow("Opacity:", self.area_alpha)
        form.addRow(QLabel("\"To baseline\" fills between the curve and the baseline;\n"
                           "\"As polygon\" closes the curve back to its first point."))
        tabs.addTab(page, "Fill")

        # ---- "Annotated values" tab
        page = QWidget()
        form = QFormLayout(page)
        self.avalue_type = make_combo(AVALUE_TYPES)
        self.avalue_size = SliderSpin(0.1, 5, 0.05, 2)
        self.avalue_color = ColorCombo()
        self.avalue_font = FontCombo()
        self.avalue_format = make_combo(["General", "Decimal", "Exponential", "Power"])
        self.avalue_prec = QSpinBox()
        self.avalue_prec.setRange(0, 12)
        self.avalue_prepend = QLineEdit()
        self.avalue_append = QLineEdit()
        self.avalue_angle = QSpinBox()
        self.avalue_angle.setRange(-360, 360)
        self.avalue_dx = QDoubleSpinBox()
        self.avalue_dy = QDoubleSpinBox()
        for spin in (self.avalue_dx, self.avalue_dy):
            spin.setRange(-1, 1)
            spin.setDecimals(3)
            spin.setSingleStep(0.005)
        form.addRow("Show:", self.avalue_type)
        form.addRow("Char size:", self.avalue_size)
        form.addRow("Color:", self.avalue_color)
        form.addRow("Font:", self.avalue_font)
        form.addRow("Format:", self.avalue_format)
        form.addRow("Precision:", self.avalue_prec)
        form.addRow("Prepend:", self.avalue_prepend)
        form.addRow("Append:", self.avalue_append)
        form.addRow("Rotation:", self.avalue_angle)
        form.addRow("Offset X (view):", self.avalue_dx)
        form.addRow("Offset Y (view):", self.avalue_dy)
        tabs.addTab(page, "Annotated values")

        self.add_buttons(["Apply", "Accept", "Close"])

    def copy_symbol_color_to_fill(self):
        self.fill_color.setColor(self.symbol_color.color())

    def refresh(self):
        project = self.project()
        self.setWindowTitle("Set Appearance (G%d)" % project.current)
        self.set_list.populate(project.current, project.cg())
        self.load()

    def select_set(self, set_index):
        self.refresh()
        self.set_list.select(set_index)
        self.load()

    def load(self):
        """Show the properties of the first selected set."""
        g = self.project().cg()
        selected = self.set_list.selected()
        if len(selected) == 0 or selected[0] >= len(g.sets):
            return
        ds = g.sets[selected[0]]
        self.symbol_type.setCurrentIndex(ds.symbol.shape)
        self.symbol_size.setValue(ds.symbol.size)
        self.symbol_color.setColor(ds.symbol.color)
        self.symbol_alpha.setValue(ds.symbol.alpha)
        self.fill.setCurrentIndex(ds.symbol.fill)
        self.fill_color.setColor(ds.symbol.fill_color)
        self.fill_alpha.setValue(ds.symbol.fill_alpha)
        self.symbol_linewidth.setValue(ds.symbol.linewidth)
        self.symbol_skip.setValue(ds.symbol.skip)
        self.line_type.setCurrentIndex(ds.line.type)
        self.line_style.setCurrentIndex(ds.line.style)
        self.line_width.setValue(ds.line.width)
        self.line_color.setColor(ds.line.color)
        self.line_alpha.setValue(ds.line.alpha)
        self.errorbar_show.setChecked(ds.errorbar.show)
        self.errorbar_color.setColor(ds.errorbar.color)
        self.errorbar_alpha.setValue(ds.errorbar.alpha)
        self.errorbar_width.setValue(ds.errorbar.width)
        self.errorbar_cap.setValue(ds.errorbar.cap)
        if ds.errorbar.place in ERRORBAR_PLACES:
            self.errorbar_place.setCurrentIndex(ERRORBAR_PLACES.index(ds.errorbar.place))
        self.fill_type.setCurrentIndex(ds.fill.type)
        self.fill_baseline.setCurrentIndex(ds.fill.baseline)
        self.area_color.setColor(ds.fill.color)
        self.area_alpha.setValue(ds.fill.alpha)
        av = ds.avalue
        self.avalue_type.setCurrentIndex(av.type)
        self.avalue_size.setValue(av.size)
        self.avalue_color.setColor(av.color)
        self.avalue_font.set_font_spec(av.font)
        if av.format in TICK_FORMATS:
            self.avalue_format.setCurrentIndex(TICK_FORMATS.index(av.format))
        self.avalue_prec.setValue(av.prec)
        self.avalue_prepend.setText(av.prepend)
        self.avalue_append.setText(av.append)
        self.avalue_angle.setValue(int(round(av.angle)))
        self.avalue_dx.setValue(av.offset_x)
        self.avalue_dy.setValue(av.offset_y)
        self.legend.setText(ds.legend)
        self.legend.setEnabled(len(selected) == 1)    # one legend text can't apply to many sets
        self.hidden.setChecked(ds.hidden)

    def apply(self):
        """Apply the widgets to ALL selected sets."""
        g = self.project().cg()
        selected = self.set_list.selected()
        for si in selected:
            if si >= len(g.sets):
                continue
            ds = g.sets[si]
            ds.symbol.shape = self.symbol_type.currentIndex()
            ds.symbol.size = self.symbol_size.value()
            ds.symbol.color = self.symbol_color.color()
            ds.symbol.alpha = self.symbol_alpha.value()
            ds.symbol.fill = self.fill.currentIndex()
            ds.symbol.fill_color = self.fill_color.color()
            ds.symbol.fill_alpha = self.fill_alpha.value()
            ds.symbol.linewidth = self.symbol_linewidth.value()
            ds.symbol.skip = self.symbol_skip.value()
            ds.line.type = self.line_type.currentIndex()
            ds.line.style = self.line_style.currentIndex()
            ds.line.width = self.line_width.value()
            ds.line.color = self.line_color.color()
            ds.line.alpha = self.line_alpha.value()
            ds.errorbar.show = self.errorbar_show.isChecked()
            ds.errorbar.color = self.errorbar_color.color()
            ds.errorbar.alpha = self.errorbar_alpha.value()
            ds.errorbar.width = self.errorbar_width.value()
            ds.errorbar.cap = self.errorbar_cap.value()
            ds.errorbar.place = ERRORBAR_PLACES[self.errorbar_place.currentIndex()]
            ds.fill.type = self.fill_type.currentIndex()
            ds.fill.baseline = self.fill_baseline.currentIndex()
            ds.fill.color = self.area_color.color()
            ds.fill.alpha = self.area_alpha.value()
            av = ds.avalue
            av.type = self.avalue_type.currentIndex()
            av.size = self.avalue_size.value()
            av.color = self.avalue_color.color()
            av.font = self.avalue_font.font_spec()
            av.format = TICK_FORMATS[self.avalue_format.currentIndex()]
            av.prec = self.avalue_prec.value()
            av.prepend = self.avalue_prepend.text()
            av.append = self.avalue_append.text()
            av.angle = float(self.avalue_angle.value())
            av.offset_x = self.avalue_dx.value()
            av.offset_y = self.avalue_dy.value()
            ds.hidden = self.hidden.isChecked()
            if len(selected) == 1:
                ds.legend = self.legend.text()
        self.main.changed()


# ===========================================================================
# Axis properties  (laid out like xmgrace's axis dialog)
# ===========================================================================
APPLY_TO = ["Current axis", "All axes, current graph", "Current axis, all graphs", "All axes, all graphs"]

# Axis settings that describe the data range; only copied to axes of the same direction
RANGE_FIELDS = ["min", "max", "scale", "invert", "label", "auto_ticks", "major", "custom_ticks",
                "custom_tick_list", "ticklabel_formula"]


def group(title, layout):
    """A titled box (QGroupBox) holding a layout."""
    box = QGroupBox(title)
    box.setLayout(layout)
    return box


class AxisDialog(GraceDialog):
    title = "Axis Properties"

    def __init__(self, main):
        super().__init__(main)
        top = QHBoxLayout()
        top.addWidget(QLabel("Edit:"))
        self.which = make_combo(["X axis", "Y axis", "Alternate X axis (top)", "Alternate Y axis (right)"])
        self.which.currentIndexChanged.connect(self.load)
        top.addWidget(self.which)
        self.enabled = QCheckBox("Active")
        top.addWidget(self.enabled)
        top.addStretch(1)
        self.vbox.addLayout(top)

        grid = QGridLayout()
        self.start = FloatEdit()
        self.stop = FloatEdit()
        self.scale = make_combo(AXIS_SCALE_NAMES)
        self.invert = QCheckBox("Invert axis")
        grid.addWidget(QLabel("Start:"), 0, 0)
        grid.addWidget(self.start, 0, 1)
        grid.addWidget(QLabel("Stop:"), 0, 2)
        grid.addWidget(self.stop, 0, 3)
        grid.addWidget(QLabel("Scale:"), 1, 0)
        grid.addWidget(self.scale, 1, 1)
        grid.addWidget(self.invert, 1, 3)
        self.vbox.addLayout(grid)
        self.range_note = QLabel("An alternate axis uses the range and scale of its main axis.")
        self.vbox.addWidget(self.range_note)

        tabs = QTabWidget()
        self.tabs = tabs
        self.vbox.addWidget(tabs)
        tabs.addTab(self.build_main_tab(), "Main")
        tabs.addTab(self.build_label_tab(), "Axis label && bar")
        tabs.addTab(self.build_ticklabel_tab(), "Tick labels")
        tabs.addTab(self.build_tickmark_tab(), "Tick marks")
        tabs.addTab(self.build_special_tab(), "Special")

        row = QHBoxLayout()
        row.addWidget(QLabel("Apply to:"))
        self.apply_to = make_combo(APPLY_TO)
        row.addWidget(self.apply_to)
        row.addStretch(1)
        self.vbox.addLayout(row)
        self.add_buttons(["Apply", "Accept", "Close"])

    # ----------------------------------------------------------- tabs
    def build_main_tab(self):
        page = QWidget()
        column = QVBoxLayout(page)

        form = QFormLayout()
        self.label = QLineEdit()
        form.addRow("Label string:", self.label)
        column.addWidget(group("Axis label", form))

        form = QFormLayout()
        self.major = FloatEdit()
        self.auto = QCheckBox("Auto")
        self.auto.toggled.connect(self.on_auto_toggled)
        self.minor = QSpinBox()
        self.minor.setRange(0, 50)
        self.format = make_combo(TICK_FORMAT_NAMES)
        self.precision = QSpinBox()
        self.precision.setRange(0, 12)
        form.addRow("Major spacing:", pair_row(self.major, self.auto))
        form.addRow("Minor ticks:", self.minor)
        form.addRow("Format:", pair_row(self.format, self.precision))
        column.addWidget(group("Tick properties", form))

        grid = QGridLayout()
        self.show_ticklabels = QCheckBox("Display tick labels")
        self.bar_on = QCheckBox("Display axis bar")
        self.ticks_on = QCheckBox("Display tick marks")
        grid.addWidget(self.show_ticklabels, 0, 0)
        grid.addWidget(self.bar_on, 0, 1)
        grid.addWidget(self.ticks_on, 1, 0)
        column.addWidget(group("Display options", grid))

        form = QFormLayout()
        self.zero_axis = QCheckBox("Zero axis (draw at zero of the other axis)")
        self.offset_normal = offset_spin()
        self.offset_opposite = offset_spin()
        form.addRow(self.zero_axis)
        form.addRow("Offsets, normal / opposite:", pair_row(self.offset_normal, self.offset_opposite))
        column.addWidget(group("Axis placement", form))

        form = QFormLayout()
        self.ticklabel_font = FontCombo()
        self.ticklabel_color = ColorCombo()
        form.addRow("Font:", self.ticklabel_font)
        form.addRow("Color:", self.ticklabel_color)
        column.addWidget(group("Tick label properties", form))
        column.addStretch(1)
        return page

    def build_label_tab(self):
        page = QWidget()
        column = QVBoxLayout(page)

        form = QFormLayout()
        self.label_font = FontCombo()
        self.label_color = ColorCombo()
        self.label_size = SliderSpin(0.1, 5, 0.05, 2)
        self.label_layout = make_combo(["Parallel to axis", "Perpendicular to axis", "Custom angle"])
        self.label_layout.currentIndexChanged.connect(self.on_label_layout)
        self.label_angle = angle_spin()
        self.label_side = make_combo(SIDE_NAMES)
        self.label_dx = offset_spin()
        self.label_dy = offset_spin()
        form.addRow("Font:", self.label_font)
        form.addRow("Color:", self.label_color)
        form.addRow("Char size:", self.label_size)
        form.addRow("Layout:", self.label_layout)
        form.addRow("Angle:", self.label_angle)
        form.addRow("Side:", self.label_side)
        form.addRow("Offset x, y:", pair_row(self.label_dx, self.label_dy))
        column.addWidget(group("Label properties", form))

        form = QFormLayout()
        self.bar_color = ColorCombo()
        self.bar_width = SliderSpin(0, 10, 0.1, 1)
        self.bar_style = make_combo(LINE_STYLES)
        self.frame_width = SliderSpin(0, 10, 0.1, 1)
        form.addRow("Color:", self.bar_color)
        form.addRow("Width:", self.bar_width)
        form.addRow("Line style:", self.bar_style)
        form.addRow("Frame line width (graph):", self.frame_width)
        column.addWidget(group("Bar properties", form))
        column.addWidget(QLabel(PLACEMENT_TIP))
        column.addStretch(1)
        return page

    def build_ticklabel_tab(self):
        page = QWidget()
        column = QVBoxLayout(page)

        form = QFormLayout()
        self.ticklabel_size = SliderSpin(0.1, 5, 0.05, 2)
        self.ticklabel_angle = angle_spin()
        form.addRow("Char size:", self.ticklabel_size)
        form.addRow("Angle:", self.ticklabel_angle)
        column.addWidget(group("Labels", form))

        form = QFormLayout()
        self.ticklabel_side = make_combo(SIDE_NAMES)
        self.ticklabel_stagger = QSpinBox()
        self.ticklabel_stagger.setRange(0, 9)
        self.ticklabel_every = QSpinBox()
        self.ticklabel_every.setRange(1, 100)
        self.start_auto = make_combo(["Axis start", "Specified:"])
        self.start_value = FloatEdit("0")
        self.stop_auto = make_combo(["Axis end", "Specified:"])
        self.stop_value = FloatEdit("0")
        self.ticklabel_dx = offset_spin()
        self.ticklabel_dy = offset_spin()
        form.addRow("Side:", self.ticklabel_side)
        form.addRow("Stagger:", self.ticklabel_stagger)
        form.addRow("Label every Nth tick:", self.ticklabel_every)
        form.addRow("Start labels at:", pair_row(self.start_auto, self.start_value))
        form.addRow("Stop labels at:", pair_row(self.stop_auto, self.stop_value))
        form.addRow("Offset x, y:", pair_row(self.ticklabel_dx, self.ticklabel_dy))
        column.addWidget(group("Placement", form))

        form = QFormLayout()
        self.formula = QLineEdit()
        self.formula.setPlaceholderText("e.g. 1240/x  (label shows a function of the tick value)")
        self.prepend = QLineEdit()
        self.append = QLineEdit()
        form.addRow("Axis transform:", self.formula)
        form.addRow("Prepend:", self.prepend)
        form.addRow("Append:", self.append)
        column.addWidget(group("Extra", form))
        column.addStretch(1)
        return page

    def build_tickmark_tab(self):
        page = QWidget()
        column = QVBoxLayout(page)

        form = QFormLayout()
        self.tick_dir = make_combo(["In", "Out", "Both"])
        self.tick_side = make_combo(SIDE_NAMES)
        self.place_rounded = QCheckBox("Place at rounded positions")
        self.divisions = QSpinBox()
        self.divisions.setRange(2, 50)
        form.addRow("Pointing:", self.tick_dir)
        form.addRow("Draw on:", self.tick_side)
        form.addRow(self.place_rounded)
        form.addRow("Autotick divisions:", self.divisions)
        column.addWidget(group("Placement", form))

        row = QHBoxLayout()
        self.grid_major = QCheckBox("Draw grid lines")
        self.major_len = SliderSpin(0, 5, 0.05, 2)
        self.major_color = ColorCombo()
        self.major_width = SliderSpin(0, 10, 0.1, 1)
        self.major_style = make_combo(LINE_STYLES)
        form = QFormLayout()
        form.addRow(self.grid_major)
        form.addRow("Tick length:", self.major_len)
        form.addRow("Color:", self.major_color)
        form.addRow("Line width:", self.major_width)
        form.addRow("Line style:", self.major_style)
        row.addWidget(group("Major ticks", form))

        self.grid_minor = QCheckBox("Draw grid lines")
        self.minor_len = SliderSpin(0, 5, 0.05, 2)
        self.minor_color = ColorCombo()
        self.minor_width = SliderSpin(0, 10, 0.1, 1)
        self.minor_style = make_combo(LINE_STYLES)
        form = QFormLayout()
        form.addRow(self.grid_minor)
        form.addRow("Tick length:", self.minor_len)
        form.addRow("Color:", self.minor_color)
        form.addRow("Line width:", self.minor_width)
        form.addRow("Line style:", self.minor_style)
        row.addWidget(group("Minor ticks", form))
        column.addLayout(row)

        form = QFormLayout()
        self.grid_color = ColorCombo()
        form.addRow("Grid line color:", self.grid_color)
        column.addLayout(form)
        column.addStretch(1)
        return page

    def build_special_tab(self):
        page = QWidget()
        column = QVBoxLayout(page)
        form = QFormLayout()
        self.custom_mode = make_combo(CUSTOM_TICK_MODE_NAMES)
        form.addRow("Custom ticks:", self.custom_mode)
        column.addLayout(form)
        self.custom_table = QTableWidget(0, 3)
        self.custom_table.setHorizontalHeaderLabels(["Location", "Label (LaTeX or Grace codes)", "Type"])
        self.custom_table.horizontalHeader().setStretchLastSection(False)
        self.custom_table.setColumnWidth(0, 110)
        self.custom_table.setColumnWidth(1, 260)
        column.addWidget(self.custom_table)
        row = QHBoxLayout()
        add_button = QPushButton("Add tick")
        add_button.clicked.connect(self.on_add_custom_tick)
        delete_button = QPushButton("Delete selected")
        delete_button.clicked.connect(self.delete_custom_rows)
        fill_button = QPushButton("Fill from current ticks")
        fill_button.clicked.connect(self.fill_custom_from_current)
        row.addWidget(add_button)
        row.addWidget(delete_button)
        row.addWidget(fill_button)
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(QLabel("Example: locations 1.5708, 3.1416 with labels $\\pi/2$, $\\pi$."))
        return page

    # ----------------------------------------------------------- small helpers
    def on_auto_toggled(self, checked):
        self.major.setEnabled(not checked)

    def on_label_layout(self, index):
        self.label_angle.setEnabled(index == 2)

    def axis(self):
        g = self.project().cg()
        return self.axis_of(g, self.which.currentIndex())

    def axis_of(self, g, index):
        if index == 0:
            return g.xaxis
        if index == 1:
            return g.yaxis
        if index == 2:
            return g.alt_xaxis
        return g.alt_yaxis

    def main_axis(self):
        """The axis whose range is shown: the axis itself, or the main axis of an alternate axis."""
        g = self.project().cg()
        if self.which.currentIndex() % 2 == 0:
            return g.xaxis
        return g.yaxis

    def is_alternate(self):
        return self.which.currentIndex() >= 2

    def is_vertical(self):
        return self.which.currentIndex() % 2 == 1

    def select_axis(self, index):
        self.which.setCurrentIndex(index)
        self.load()

    def refresh(self):
        self.setWindowTitle("Axis Properties (G%d)" % self.project().current)
        self.load()

    def on_add_custom_tick(self):
        self.add_custom_row(0.0, "", "major")

    def add_custom_row(self, value, label, kind):
        row = self.custom_table.rowCount()
        self.custom_table.insertRow(row)
        self.custom_table.setItem(row, 0, QTableWidgetItem("%.10g" % float(value)))
        self.custom_table.setItem(row, 1, QTableWidgetItem(label))
        kind_combo = make_combo(["major", "minor"])
        if kind == "minor":
            kind_combo.setCurrentIndex(1)
        self.custom_table.setCellWidget(row, 2, kind_combo)

    def delete_custom_rows(self):
        rows = []
        for index in self.custom_table.selectedIndexes():
            if index.row() not in rows:
                rows.append(index.row())
        rows.sort(reverse=True)
        for row in rows:
            self.custom_table.removeRow(row)

    def fill_custom_from_current(self):
        """Start from the ticks the axis has right now (handy for relabelling them)."""
        from .render import axis_with_range_of, automatic_ticks, format_tick
        axis = axis_with_range_of(self.axis(), self.main_axis())
        majors, minors, step = automatic_ticks(axis)
        self.custom_table.setRowCount(0)
        for value in majors:
            self.add_custom_row(value, format_tick(value, axis, step).replace("\u2212", "-"), "major")
        for value in minors:
            self.add_custom_row(value, "", "minor")

    def read_custom_table(self):
        """Rows of the custom tick table as [value, label, kind]. Raises ValueError on bad numbers."""
        entries = []
        for row in range(self.custom_table.rowCount()):
            value_item = self.custom_table.item(row, 0)
            if value_item is None or value_item.text().strip() == "":
                continue
            value = float(value_item.text())
            label_item = self.custom_table.item(row, 1)
            label = ""
            if label_item is not None:
                label = label_item.text()
            kind = self.custom_table.cellWidget(row, 2).currentText()
            entries.append([value, label, kind])
        entries.sort()
        return entries

    # ----------------------------------------------------------- model -> widgets
    def load(self):
        axis = self.axis()
        g = self.project().cg()
        main_axis = self.main_axis()
        alternate = self.is_alternate()
        self.enabled.setChecked(axis.enabled)
        self.range_note.setVisible(alternate)
        for widget in (self.start, self.stop, self.scale, self.invert):
            widget.setEnabled(not alternate)
        self.start.setValue(main_axis.min)
        self.stop.setValue(main_axis.max)
        self.scale.setCurrentIndex(AXIS_SCALES.index(main_axis.scale))
        self.invert.setChecked(main_axis.invert)

        # Main
        self.label.setText(axis.label)
        self.major.setValue(axis.major)
        self.auto.setChecked(axis.auto_ticks)
        self.major.setEnabled(not axis.auto_ticks)
        self.minor.setValue(axis.minor)
        if axis.ticklabel_format in TICK_FORMATS:
            self.format.setCurrentIndex(TICK_FORMATS.index(axis.ticklabel_format))
        self.precision.setValue(axis.ticklabel_prec)
        self.show_ticklabels.setChecked(axis.show_ticklabels)
        self.bar_on.setChecked(axis.bar_on)
        self.ticks_on.setChecked(axis.ticks_on)
        self.zero_axis.setChecked(axis.zero_axis)
        self.offset_normal.setValue(axis.offset_normal)
        self.offset_opposite.setValue(axis.offset_opposite)
        self.ticklabel_font.set_font_spec(axis.ticklabel_font)
        self.ticklabel_color.setColor(axis.ticklabel_color)

        # Axis label & bar
        self.label_font.set_font_spec(axis.label_font)
        self.label_color.setColor(axis.label_color)
        self.label_size.setValue(axis.label_size)
        if self.is_vertical():
            parallel = 90.0
            perpendicular = 0.0
        else:
            parallel = 0.0
            perpendicular = 90.0
        if axis.label_angle_auto:
            self.label_layout.setCurrentIndex(0)
            self.label_angle.setValue(parallel)
        elif axis.label_angle == perpendicular:
            self.label_layout.setCurrentIndex(1)
            self.label_angle.setValue(axis.label_angle)
        else:
            self.label_layout.setCurrentIndex(2)
            self.label_angle.setValue(axis.label_angle)
        self.label_angle.setEnabled(self.label_layout.currentIndex() == 2)
        self.label_side.setCurrentIndex(SIDES.index(axis.label_side))
        self.label_dx.setValue(axis.label_dx)
        self.label_dy.setValue(axis.label_dy)
        self.bar_color.setColor(axis.bar_color)
        self.bar_width.setValue(axis.bar_width)
        self.bar_style.setCurrentIndex(axis.bar_style)
        self.frame_width.setValue(g.frame_width)

        # Tick labels
        self.ticklabel_size.setValue(axis.ticklabel_size)
        self.ticklabel_angle.setValue(axis.ticklabel_angle)
        self.ticklabel_side.setCurrentIndex(SIDES.index(axis.ticklabel_side))
        self.ticklabel_stagger.setValue(axis.ticklabel_stagger)
        self.ticklabel_every.setValue(axis.ticklabel_skip + 1)
        if axis.ticklabel_start_auto:
            self.start_auto.setCurrentIndex(0)
        else:
            self.start_auto.setCurrentIndex(1)
        self.start_value.setValue(axis.ticklabel_start)
        if axis.ticklabel_stop_auto:
            self.stop_auto.setCurrentIndex(0)
        else:
            self.stop_auto.setCurrentIndex(1)
        self.stop_value.setValue(axis.ticklabel_stop)
        self.ticklabel_dx.setValue(axis.ticklabel_dx)
        self.ticklabel_dy.setValue(axis.ticklabel_dy)
        self.formula.setText(axis.ticklabel_formula)
        self.prepend.setText(axis.ticklabel_prepend)
        self.append.setText(axis.ticklabel_append)

        # Tick marks
        self.tick_dir.setCurrentIndex(TICK_DIRS.index(axis.tick_dir))
        if axis.ticks_opposite_only:
            self.tick_side.setCurrentIndex(1)
        elif axis.mirror:
            self.tick_side.setCurrentIndex(2)
        else:
            self.tick_side.setCurrentIndex(0)
        self.place_rounded.setChecked(axis.place_rounded)
        self.divisions.setValue(axis.autotick_divisions)
        self.grid_major.setChecked(axis.grid_major)
        self.major_len.setValue(axis.major_len)
        self.major_color.setColor(axis.major_color)
        self.major_width.setValue(axis.major_width)
        self.major_style.setCurrentIndex(axis.major_style)
        self.grid_minor.setChecked(axis.grid_minor)
        self.minor_len.setValue(axis.minor_len)
        self.minor_color.setColor(axis.minor_color)
        self.minor_width.setValue(axis.minor_width)
        self.minor_style.setCurrentIndex(axis.minor_style)
        self.grid_color.setColor(axis.grid_color)

        # Special
        self.custom_mode.setCurrentIndex(CUSTOM_TICK_MODES.index(axis.custom_ticks))
        self.custom_table.setRowCount(0)
        for entry in axis.custom_tick_list:
            self.add_custom_row(entry[0], entry[1], entry[2])

    # ----------------------------------------------------------- widgets -> model
    def apply(self):
        project = self.project()
        g = project.cg()
        axis = self.axis()
        main_axis = self.main_axis()
        try:
            lo = self.start.value()
            hi = self.stop.value()
            if self.auto.isChecked():
                major = axis.major
            else:
                major = self.major.value()
            start_value = self.start_value.value()
            stop_value = self.stop_value.value()
            custom_entries = self.read_custom_table()
        except ValueError:
            return self.warn("Start, Stop, Major spacing, label start/stop and custom tick locations "
                             "must be numbers.")
        scale = AXIS_SCALES[self.scale.currentIndex()]
        if lo == hi:
            return self.warn("Start and Stop must differ.")
        if scale == "log" and min(lo, hi) <= 0:
            return self.warn("A logarithmic axis needs Start and Stop > 0.")
        if scale == "reciprocal" and min(lo, hi) <= 0:
            return self.warn("A reciprocal axis needs Start and Stop > 0.")
        if scale == "logit" and (min(lo, hi) <= 0 or max(lo, hi) >= 1):
            return self.warn("A logit axis needs 0 < Start, Stop < 1.")
        if major <= 0:
            return self.warn("Major spacing must be positive.")

        if not self.is_alternate():
            main_axis.min = min(lo, hi)
            main_axis.max = max(lo, hi)
            main_axis.scale = scale
            main_axis.invert = self.invert.isChecked()

        # Main
        axis.enabled = self.enabled.isChecked()
        axis.label = self.label.text()
        axis.auto_ticks = self.auto.isChecked()
        axis.major = major
        axis.minor = self.minor.value()
        axis.ticklabel_format = TICK_FORMATS[self.format.currentIndex()]
        axis.ticklabel_prec = self.precision.value()
        axis.show_ticklabels = self.show_ticklabels.isChecked()
        axis.bar_on = self.bar_on.isChecked()
        axis.ticks_on = self.ticks_on.isChecked()
        axis.zero_axis = self.zero_axis.isChecked()
        axis.offset_normal = self.offset_normal.value()
        axis.offset_opposite = self.offset_opposite.value()
        axis.ticklabel_font = self.ticklabel_font.font_spec()
        axis.ticklabel_color = self.ticklabel_color.color()

        # Axis label & bar
        axis.label_font = self.label_font.font_spec()
        axis.label_color = self.label_color.color()
        axis.label_size = self.label_size.value()
        layout = self.label_layout.currentIndex()
        if layout == 0:
            axis.label_angle_auto = True
        elif layout == 1:
            axis.label_angle_auto = False
            if self.is_vertical():
                axis.label_angle = 0.0
            else:
                axis.label_angle = 90.0
        else:
            axis.label_angle_auto = False
            axis.label_angle = self.label_angle.value()
        axis.label_side = SIDES[self.label_side.currentIndex()]
        axis.label_dx = self.label_dx.value()
        axis.label_dy = self.label_dy.value()
        axis.bar_color = self.bar_color.color()
        axis.bar_width = self.bar_width.value()
        axis.bar_style = self.bar_style.currentIndex()
        g.frame_width = self.frame_width.value()

        # Tick labels
        axis.ticklabel_size = self.ticklabel_size.value()
        axis.ticklabel_angle = self.ticklabel_angle.value()
        axis.ticklabel_side = SIDES[self.ticklabel_side.currentIndex()]
        axis.ticklabel_stagger = self.ticklabel_stagger.value()
        axis.ticklabel_skip = self.ticklabel_every.value() - 1
        axis.ticklabel_start_auto = self.start_auto.currentIndex() == 0
        axis.ticklabel_start = start_value
        axis.ticklabel_stop_auto = self.stop_auto.currentIndex() == 0
        axis.ticklabel_stop = stop_value
        axis.ticklabel_dx = self.ticklabel_dx.value()
        axis.ticklabel_dy = self.ticklabel_dy.value()
        axis.ticklabel_formula = self.formula.text().strip()
        axis.ticklabel_prepend = self.prepend.text()
        axis.ticklabel_append = self.append.text()

        # Tick marks
        axis.tick_dir = TICK_DIRS[self.tick_dir.currentIndex()]
        side = self.tick_side.currentIndex()
        axis.ticks_opposite_only = side == 1
        axis.mirror = side == 2
        axis.place_rounded = self.place_rounded.isChecked()
        axis.autotick_divisions = self.divisions.value()
        axis.grid_major = self.grid_major.isChecked()
        axis.major_len = self.major_len.value()
        axis.major_color = self.major_color.color()
        axis.major_width = self.major_width.value()
        axis.major_style = self.major_style.currentIndex()
        axis.grid_minor = self.grid_minor.isChecked()
        axis.minor_len = self.minor_len.value()
        axis.minor_color = self.minor_color.color()
        axis.minor_width = self.minor_width.value()
        axis.minor_style = self.minor_style.currentIndex()
        axis.grid_color = self.grid_color.color()

        # Special
        axis.custom_ticks = CUSTOM_TICK_MODES[self.custom_mode.currentIndex()]
        axis.custom_tick_list = custom_entries

        self.copy_to_other_axes(project, g, axis)
        self.main.changed()

    def copy_to_other_axes(self, project, g, axis):
        """The "Apply to" choice: copy this axis' settings to other axes.

        Range-related settings (start, stop, scale, label text, spacing, custom ticks)
        are only copied to axes of the same direction (x to x, y to y).
        """
        choice = self.apply_to.currentIndex()
        if choice == 0:
            return
        current = self.which.currentIndex()
        graphs = [g]
        if choice == 2 or choice == 3:
            graphs = project.graphs
        for graph in graphs:
            for index in range(4):
                if choice == 2 and index != current:
                    continue                        # "Current axis, all graphs"
                target = self.axis_of(graph, index)
                if target is axis:
                    continue
                same_direction = (index % 2) == (current % 2)
                for name in vars(axis):
                    if name in RANGE_FIELDS and not same_direction:
                        continue
                    if name == "enabled" and index != current:
                        continue                    # don't switch alternate axes on by accident
                    setattr(target, name, copy.deepcopy(getattr(axis, name)))


# ===========================================================================
# Graph appearance
# ===========================================================================
class GraphAppearanceDialog(GraceDialog):
    title = "Graph Appearance"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Select graph:"))
        self.graph_list = QListWidget()
        self.graph_list.setMaximumHeight(90)
        self.graph_list.currentRowChanged.connect(self.load)
        self.vbox.addWidget(self.graph_list)

        row = QHBoxLayout()
        new_button = QPushButton("New")
        new_button.clicked.connect(self.new_graph)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self.duplicate_graph)
        kill_button = QPushButton("Kill")
        kill_button.clicked.connect(self.kill_graph)
        focus_button = QPushButton("Make current")
        focus_button.clicked.connect(self.focus_graph)
        row.addWidget(new_button)
        row.addWidget(duplicate_button)
        row.addWidget(kill_button)
        row.addWidget(focus_button)
        self.vbox.addLayout(row)

        self.tabs = QTabWidget()
        self.vbox.addWidget(self.tabs)

        # ---- "Main" tab
        page = QWidget()
        form = QFormLayout(page)
        self.title_edit = QLineEdit()
        self.subtitle_edit = QLineEdit()
        form.addRow("Title:", self.title_edit)
        form.addRow("Subtitle:", self.subtitle_edit)
        viewport_box = QGroupBox("Viewport")
        viewport_grid = QGridLayout(viewport_box)
        self.viewport_spins = []
        names = ["Xmin", "Ymin", "Xmax", "Ymax"]
        for k in range(4):
            spin = QDoubleSpinBox()
            spin.setRange(-1, 3)
            spin.setSingleStep(0.01)
            spin.setDecimals(3)
            row_number = k // 2
            column = (k % 2) * 2
            viewport_grid.addWidget(QLabel(names[k] + ":"), row_number, column)
            viewport_grid.addWidget(spin, row_number, column + 1)
            self.viewport_spins.append(spin)
        form.addRow(viewport_box)
        self.show_legend = QCheckBox("Display legend")
        self.frame_width = SliderSpin(0, 10, 0.1, 1)
        self.bg_color = ColorCombo()
        self.bg_alpha = OpacitySlider()
        self.hidden = QCheckBox("Hidden")
        form.addRow(self.show_legend)
        form.addRow("Frame line width:", self.frame_width)
        form.addRow("Background:", self.bg_color)
        form.addRow("Background opacity:", self.bg_alpha)
        form.addRow(self.hidden)
        self.tabs.addTab(page, "Main")

        # ---- "Titles" tab
        page = QWidget()
        form = QFormLayout(page)
        self.title_size = SliderSpin(0.1, 5, 0.05, 2)
        self.subtitle_size = SliderSpin(0.1, 5, 0.05, 2)
        self.title_font = FontCombo()
        self.subtitle_font = FontCombo()
        self.title_dx = offset_spin()
        self.title_dy = offset_spin()
        self.title_angle = angle_spin()
        self.subtitle_dx = offset_spin()
        self.subtitle_dy = offset_spin()
        self.subtitle_angle = angle_spin()
        form.addRow("Title size:", self.title_size)
        form.addRow("Title font:", self.title_font)
        form.addRow("Title offset x, y:", pair_row(self.title_dx, self.title_dy))
        form.addRow("Title angle:", self.title_angle)
        form.addRow("Subtitle size:", self.subtitle_size)
        form.addRow("Subtitle font:", self.subtitle_font)
        form.addRow("Subtitle offset x, y:", pair_row(self.subtitle_dx, self.subtitle_dy))
        form.addRow("Subtitle angle:", self.subtitle_angle)
        form.addRow(QLabel(PLACEMENT_TIP))
        self.tabs.addTab(page, "Titles")

        # ---- "Legend box" tab
        page = QWidget()
        form = QFormLayout(page)
        self.legend_x = QDoubleSpinBox()
        self.legend_y = QDoubleSpinBox()
        for spin in (self.legend_x, self.legend_y):
            spin.setRange(-1, 2)
            spin.setSingleStep(0.001)
            spin.setDecimals(4)
        self.legend_row_gap = SliderSpin(0, 3, 0.01, 2)
        self.legend_sample = SliderSpin(0, 8, 0.05, 2)
        self.legend_padding = SliderSpin(0, 3, 0.01, 2)
        self.legend_border_width = SliderSpin(0, 10, 0.1, 1)
        self.legend_invert = QCheckBox("List the sets in reverse order")
        self.legend_size = SliderSpin(0.1, 5, 0.05, 2)
        self.legend_font = FontCombo()
        self.legend_border = QCheckBox("Draw border")
        self.legend_fill = QCheckBox("Fill box")
        self.legend_fill_color = ColorCombo()
        self.legend_fill_alpha = OpacitySlider()
        form.addRow(QLabel("Location of the upper-left corner, relative to the frame (0–1).\n"
                           "You can also drag the legend with the mouse."))
        form.addRow("X:", self.legend_x)
        form.addRow("Y:", self.legend_y)
        form.addRow("Char size:", self.legend_size)
        form.addRow("Font:", self.legend_font)
        form.addRow(self.legend_border)
        form.addRow(self.legend_fill)
        form.addRow("Box fill:", self.legend_fill_color)
        form.addRow("Box opacity:", self.legend_fill_alpha)
        form.addRow("Border width:", self.legend_border_width)
        form.addRow("Row spacing:", self.legend_row_gap)
        form.addRow("Line sample length:", self.legend_sample)
        form.addRow("Inner padding:", self.legend_padding)
        form.addRow(self.legend_invert)
        self.tabs.addTab(page, "Legend box")

        self.add_buttons(["Apply", "Accept", "Close"])

    def selected_graph_index(self):
        row = self.graph_list.currentRow()
        if row >= 0 and row < len(self.project().graphs):
            return row
        return self.project().current

    def refresh(self):
        project = self.project()
        keep = self.graph_list.currentRow()
        if keep < 0:
            keep = project.current
        self.graph_list.blockSignals(True)
        self.graph_list.clear()
        for i in range(len(project.graphs)):
            g = project.graphs[i]
            text = "G%d" % i
            if i == project.current:
                text = text + " (current)"
            text = text + "  [%d sets]" % len(g.sets)
            if g.hidden:
                text = text + "  hidden"
            self.graph_list.addItem(text)
        self.graph_list.setCurrentRow(min(keep, self.graph_list.count() - 1))
        self.graph_list.blockSignals(False)
        self.load()

    def select_graph(self, graph_index, tab_index=0):
        self.graph_list.setCurrentRow(graph_index)
        self.tabs.setCurrentIndex(tab_index)
        self.load()

    def load(self):
        g = self.project().graphs[self.selected_graph_index()]
        self.title_edit.setText(g.title)
        self.subtitle_edit.setText(g.subtitle)
        for k in range(4):
            self.viewport_spins[k].setValue(g.viewport[k])
        self.show_legend.setChecked(g.legend.show)
        self.frame_width.setValue(g.frame_width)
        self.bg_color.setColor(g.bg_color)
        self.bg_alpha.setValue(g.bg_alpha)
        self.hidden.setChecked(g.hidden)
        self.title_size.setValue(g.title_size)
        self.subtitle_size.setValue(g.subtitle_size)
        self.title_font.set_font_spec(g.title_font)
        self.subtitle_font.set_font_spec(g.subtitle_font)
        self.title_dx.setValue(g.title_dx)
        self.title_dy.setValue(g.title_dy)
        self.title_angle.setValue(g.title_angle)
        self.subtitle_dx.setValue(g.subtitle_dx)
        self.subtitle_dy.setValue(g.subtitle_dy)
        self.subtitle_angle.setValue(g.subtitle_angle)
        self.legend_row_gap.setValue(g.legend.row_gap)
        self.legend_sample.setValue(g.legend.sample_length)
        self.legend_padding.setValue(g.legend.padding)
        self.legend_border_width.setValue(g.legend.border_width)
        self.legend_invert.setChecked(g.legend.invert)
        self.legend_x.setValue(g.legend.x)
        self.legend_y.setValue(g.legend.y)
        self.legend_size.setValue(g.legend.char_size)
        self.legend_font.set_font_spec(g.legend.font)
        self.legend_border.setChecked(g.legend.box)
        self.legend_fill.setChecked(g.legend.fill)
        self.legend_fill_color.setColor(g.legend.box_fill)
        self.legend_fill_alpha.setValue(g.legend.box_alpha)

    def apply(self):
        g = self.project().graphs[self.selected_graph_index()]
        viewport = []
        for k in range(4):
            viewport.append(self.viewport_spins[k].value())
        if viewport[2] <= viewport[0] or viewport[3] <= viewport[1]:
            return self.warn("Viewport Xmax/Ymax must be larger than Xmin/Ymin.")
        g.title = self.title_edit.text()
        g.subtitle = self.subtitle_edit.text()
        g.viewport = viewport
        g.legend.show = self.show_legend.isChecked()
        g.frame_width = self.frame_width.value()
        g.bg_color = self.bg_color.color()
        g.bg_alpha = self.bg_alpha.value()
        g.hidden = self.hidden.isChecked()
        g.title_size = self.title_size.value()
        g.subtitle_size = self.subtitle_size.value()
        g.title_font = self.title_font.font_spec()
        g.subtitle_font = self.subtitle_font.font_spec()
        g.title_dx = self.title_dx.value()
        g.title_dy = self.title_dy.value()
        g.title_angle = self.title_angle.value()
        g.subtitle_dx = self.subtitle_dx.value()
        g.subtitle_dy = self.subtitle_dy.value()
        g.subtitle_angle = self.subtitle_angle.value()
        g.legend.row_gap = self.legend_row_gap.value()
        g.legend.sample_length = self.legend_sample.value()
        g.legend.padding = self.legend_padding.value()
        g.legend.border_width = self.legend_border_width.value()
        g.legend.invert = self.legend_invert.isChecked()
        g.legend.x = self.legend_x.value()
        g.legend.y = self.legend_y.value()
        g.legend.char_size = self.legend_size.value()
        g.legend.font = self.legend_font.font_spec()
        g.legend.box = self.legend_border.isChecked()
        g.legend.fill = self.legend_fill.isChecked()
        g.legend.box_fill = self.legend_fill_color.color()
        g.legend.box_alpha = self.legend_fill_alpha.value()
        self.main.changed()

    def new_graph(self):
        project = self.project()
        project.graphs.append(Graph())
        project.current = len(project.graphs) - 1
        self.graph_list.setCurrentRow(-1)
        self.main.changed()

    def duplicate_graph(self):
        project = self.project()
        project.graphs.append(copy.deepcopy(project.graphs[self.selected_graph_index()]))
        self.main.changed()

    def kill_graph(self):
        project = self.project()
        if len(project.graphs) <= 1:
            return self.warn("Can't kill the only graph.")
        del project.graphs[self.selected_graph_index()]
        project.current = min(project.current, len(project.graphs) - 1)
        self.graph_list.setCurrentRow(-1)
        self.main.changed()

    def focus_graph(self):
        self.project().current = self.selected_graph_index()
        self.main.changed(False)


# ===========================================================================
# Plot (page) appearance
# ===========================================================================
class PlotAppearanceDialog(GraceDialog):
    title = "Plot Appearance"

    def __init__(self, main):
        super().__init__(main)
        form = QFormLayout()
        names = list(PAGE_SIZES)
        names.append("Custom")
        self.size_combo = make_combo(names)
        self.size_combo.currentIndexChanged.connect(self.on_size_preset)
        self.width_spin = QDoubleSpinBox()
        self.height_spin = QDoubleSpinBox()
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(36, 10000)
            spin.setDecimals(1)
            spin.setSuffix(" pt")
        self.page_color = ColorCombo()
        self.font = FontCombo(False)
        form.addRow("Page size:", self.size_combo)
        form.addRow("Width:", self.width_spin)
        form.addRow("Height:", self.height_spin)
        form.addRow("Page background:", self.page_color)
        form.addRow("Default font:", self.font)
        self.text_mode = make_combo(TEXT_MODE_NAMES)
        self.preamble = QPlainTextEdit()
        self.preamble.setPlaceholderText("Extra LaTeX preamble lines, e.g.\n\\usepackage{siunitx}\n\\usepackage{mathpazo}")
        self.preamble.setMaximumHeight(110)
        form.addRow("Text typesetting:", self.text_mode)
        form.addRow("LaTeX preamble:", self.preamble)
        form.addRow(QLabel("With LaTeX, write math between $...$ like in a document: Time $t$ (\\textmu s).\n"
                           "amsmath, amssymb and xcolor are always loaded."))
        self.vbox.addLayout(form)
        self.add_buttons(["Apply", "Accept", "Close"])

    def on_size_preset(self):
        name = self.size_combo.currentText()
        if name in PAGE_SIZES:
            self.width_spin.setValue(PAGE_SIZES[name][0])
            self.height_spin.setValue(PAGE_SIZES[name][1])

    def refresh(self):
        project = self.project()
        preset = "Custom"
        for name in PAGE_SIZES:
            size = PAGE_SIZES[name]
            if abs(size[0] - project.page_w) < 1 and abs(size[1] - project.page_h) < 1:
                preset = name
        self.size_combo.blockSignals(True)
        self.size_combo.setCurrentText(preset)
        self.size_combo.blockSignals(False)
        self.width_spin.setValue(project.page_w)
        self.height_spin.setValue(project.page_h)
        self.page_color.setColor(project.page_color)
        self.font.set_font_spec(project.font_family)
        if project.text_mode in TEXT_MODES:
            self.text_mode.setCurrentIndex(TEXT_MODES.index(project.text_mode))
        self.preamble.setPlainText(project.latex_preamble)

    def apply(self):
        project = self.project()
        project.page_w = self.width_spin.value()
        project.page_h = self.height_spin.value()
        project.page_color = self.page_color.color()
        font = self.font.font_spec()
        if font == "":
            font = "Helvetica"
        project.font_family = font
        project.text_mode = TEXT_MODES[self.text_mode.currentIndex()]
        project.latex_preamble = self.preamble.toPlainText().strip()
        self.main.changed()


# ===========================================================================
# Arrange graphs in a grid
# ===========================================================================
class ArrangeDialog(GraceDialog):
    title = "Arrange Graphs"

    def __init__(self, main):
        super().__init__(main)
        form = QFormLayout()
        self.rows = QSpinBox()
        self.columns = QSpinBox()
        self.rows.setRange(1, 12)
        self.columns.setRange(1, 12)
        form.addRow("Rows:", self.rows)
        form.addRow("Columns:", self.columns)

        self.left = self.make_offset(0.15)
        self.right = self.make_offset(0.15)
        self.top = self.make_offset(0.12)
        self.bottom = self.make_offset(0.15)
        self.hgap = self.make_offset(0.22)
        self.vgap = self.make_offset(0.18)
        form.addRow("Left:", self.left)
        form.addRow("Right:", self.right)
        form.addRow("Top:", self.top)
        form.addRow("Bottom:", self.bottom)
        form.addRow("Horizontal gap:", self.hgap)
        form.addRow("Vertical gap:", self.vgap)
        form.addRow(QLabel("Offsets and gaps are in viewport units (short page side = 1).\n"
                           "Missing graphs are created; extra empty graphs are removed."))
        self.vbox.addLayout(form)
        self.add_buttons(["Apply", "Accept", "Close"])

    def make_offset(self, value):
        spin = QDoubleSpinBox()
        spin.setRange(0, 1)
        spin.setSingleStep(0.01)
        spin.setDecimals(3)
        spin.setValue(value)
        return spin

    def apply(self):
        project = self.project()
        rows = self.rows.value()
        columns = self.columns.value()
        width = (project.view_w() - self.left.value() - self.right.value()
                 - (columns - 1) * self.hgap.value()) / columns
        height = (project.view_h() - self.top.value() - self.bottom.value()
                  - (rows - 1) * self.vgap.value()) / rows
        if width <= 0.02 or height <= 0.02:
            return self.warn("The graphs don't fit; reduce the offsets or gaps.")

        count = rows * columns
        while len(project.graphs) < count:
            project.graphs.append(Graph())
        # Remove extra graphs only if they are empty
        kept = project.graphs[:count]
        for g in project.graphs[count:]:
            if len(g.sets) > 0:
                kept.append(g)
        project.graphs = kept

        for k in range(count):
            row = k // columns
            column = k % columns
            x0 = self.left.value() + column * (width + self.hgap.value())
            y1 = project.view_h() - self.top.value() - row * (height + self.vgap.value())
            project.graphs[k].viewport = [x0, y1 - height, x0 + width, y1]
        project.current = min(project.current, len(project.graphs) - 1)
        self.main.changed()
