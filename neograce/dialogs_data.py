"""
dialogs_data.py - the "Data" and "Edit" menu dialogs: editing sets, formulas,
regression, and the xmgrace transformations (running averages, FFT, ...).
"""
import numpy as np
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import transforms
from .dialogs_base import GraceDialog, RegionChooser, SetList, make_combo, set_operation
from .model import SET_TYPE_COLUMNS
from .transforms import FIT_KINDS, ExprError
from .widgets import FloatEdit


# ===========================================================================
# Edit > Data sets
# ===========================================================================
class DataSetsDialog(GraceDialog):
    title = "Data Sets"

    # (button text, operation name passed to set_operation)
    OPERATIONS = [("Duplicate", "duplicate"), ("Kill", "kill"), ("Hide", "hide"), ("Show", "show"),
                  ("Bring to front", "front"), ("Send to back", "back")]

    def __init__(self, main):
        super().__init__(main)
        row = QHBoxLayout()
        self.set_list = SetList(main, True)
        self.set_list.itemDoubleClicked.connect(self.edit_data)
        row.addWidget(self.set_list, 1)

        column = QVBoxLayout()
        edit_button = QPushButton("Edit data…")
        edit_button.clicked.connect(self.edit_data)
        column.addWidget(edit_button)
        for text, operation in self.OPERATIONS:
            button = QPushButton(text)
            button.setProperty("operation", operation)       # read back in on_operation_button
            button.clicked.connect(self.on_operation_button)
            column.addWidget(button)
        column.addStretch(1)
        row.addLayout(column)
        self.vbox.addLayout(row)
        self.add_buttons(["Close"])
        self.resize(520, 320)

    def on_operation_button(self):
        # self.sender() is the button that was clicked (same as in C++ Qt)
        operation = self.sender().property("operation")
        set_operation(self.main, operation, self.set_list.selected())

    def refresh(self):
        project = self.project()
        self.setWindowTitle("Data Sets (G%d)" % project.current)
        self.set_list.populate(project.current, project.cg())

    def edit_data(self):
        selected = self.set_list.selected()
        if len(selected) > 0:
            editor = SpreadsheetDialog(self.main, self.project().current, selected[0])
            editor.exec()


class SpreadsheetDialog(QDialog):
    """Edit the numbers of one set in a table."""

    def __init__(self, main, graph_index, set_index):
        super().__init__(main)
        self.main = main
        self.ds = main.project.graphs[graph_index].sets[set_index]
        self.setWindowTitle("Edit G%d.S%d" % (graph_index, set_index))
        layout = QVBoxLayout(self)

        ds = self.ds
        n = len(ds)
        self.set_type = ds.set_type()
        columns = []
        for column in ds.columns():
            columns.append(column[:n])
        headers = self.column_headers()
        if n > 50000:
            QMessageBox.information(self, "Edit data", "%d rows; the table may be slow." % n)

        self.table = QTableWidget(n, len(columns))
        self.table.setHorizontalHeaderLabels(headers)
        for j in range(len(columns)):
            for i in range(n):
                self.table.setItem(i, j, QTableWidgetItem("%.10g" % columns[j][i]))
        layout.addWidget(self.table)

        row = QHBoxLayout()
        buttons = [("Add row", self.add_row), ("Delete rows", self.delete_rows),
                   ("Add DY column", self.add_dy_column), ("Apply", self.apply), ("Close", self.close)]
        for text, method in buttons:
            button = QPushButton(text)
            button.clicked.connect(method)
            row.addWidget(button)
        layout.addLayout(row)
        self.resize(420, 520)

    def column_headers(self):
        names = {"dx": "DX", "dx_low": "DX (left)", "dy": "DY", "dy_low": "DY (lower)"}
        headers = ["X", "Y"]
        for name in SET_TYPE_COLUMNS[self.set_type]:
            headers.append(names[name])
        return headers

    def add_row(self):
        self.table.insertRow(self.table.rowCount())

    def delete_rows(self):
        rows = []
        for index in self.table.selectedIndexes():
            if index.row() not in rows:
                rows.append(index.row())
        rows.sort(reverse=True)         # delete from the bottom up so row numbers stay valid
        for r in rows:
            self.table.removeRow(r)

    def add_dy_column(self):
        if self.set_type == "xy":
            self.set_type = "xydy"
        elif self.set_type == "xydx":
            self.set_type = "xydxdy"
        else:
            return                                # already has dy
        column = self.table.columnCount()
        self.table.setColumnCount(column + 1)
        self.table.setHorizontalHeaderLabels(self.column_headers())
        for i in range(self.table.rowCount()):
            self.table.setItem(i, column, QTableWidgetItem("0"))

    def apply(self):
        rows = self.table.rowCount()
        columns = self.table.columnCount()
        values = np.full((rows, columns), np.nan)
        for i in range(rows):
            for j in range(columns):
                item = self.table.item(i, j)
                if item is None or item.text().strip() == "":
                    continue                     # empty cell = NaN
                try:
                    values[i, j] = float(item.text())
                except ValueError:
                    QMessageBox.warning(self, "Edit data", "Row %d, column %d is not a number." % (i + 1, j + 1))
                    return
        self.ds.x = values[:, 0].copy()
        self.ds.y = values[:, 1].copy()
        error_columns = []
        for j in range(2, columns):
            error_columns.append(values[:, j].copy())
        self.ds.set_errors(self.set_type, error_columns)
        self.main.changed()


# ===========================================================================
# Edit > Set operations (copy / move sets to another graph)
# ===========================================================================
class SetOperationsDialog(GraceDialog):
    title = "Set Operations"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Source set(s) in the current graph:"))
        self.set_list = SetList(main, True)
        self.vbox.addWidget(self.set_list)
        form = QFormLayout()
        self.operation = make_combo(["Copy", "Move"])
        self.destination = QComboBox()
        form.addRow("Operation:", self.operation)
        form.addRow("To graph:", self.destination)
        self.vbox.addLayout(form)
        self.add_buttons(["Apply", "Close"])

    def refresh(self):
        project = self.project()
        self.set_list.populate(project.current, project.cg())
        self.destination.clear()
        for i in range(len(project.graphs)):
            self.destination.addItem("G%d" % i)

    def apply(self):
        project = self.project()
        source = project.cg()
        target = project.graphs[self.destination.currentIndex()]
        moving = self.operation.currentIndex() == 1
        if target is source and moving:
            return self.warn("Choose a different graph to move sets to.")
        selected = self.set_list.selected()
        for si in selected:
            target.sets.append(source.sets[si].copy())
        if moving:
            remaining = []
            for si in range(len(source.sets)):
                if si not in selected:
                    remaining.append(source.sets[si])
            source.sets = remaining
        self.main.changed()


# ===========================================================================
# Data > Create set from formula
# ===========================================================================
class FormulaDialog(GraceDialog):
    title = "Create Set from Formula"

    def __init__(self, main):
        super().__init__(main)
        form = QFormLayout()
        self.start = FloatEdit("0")
        self.stop = FloatEdit("10")
        self.length = QSpinBox()
        self.length.setRange(2, 10000000)
        self.length.setValue(200)
        self.formula = QLineEdit("y = sin(x)")
        form.addRow("Start:", self.start)
        form.addRow("Stop:", self.stop)
        form.addRow("Length:", self.length)
        form.addRow("Formula:", self.formula)
        form.addRow(QLabel("Use x, index, and functions like sin, exp, sqrt, log; ^ is power."))
        self.vbox.addLayout(form)
        self.add_buttons(["Apply", "Close"])

    def apply(self):
        try:
            x = np.linspace(self.start.value(), self.stop.value(), self.length.value())
            target, values = transforms.evaluate(self.formula.text(), x, np.zeros_like(x))
        except ValueError:
            return self.warn("Start and Stop must be numbers.")
        except ExprError as error:
            return self.warn(str(error))
        if target != "y":
            return self.warn("Use a formula of the form  y = …")
        g = self.project().cg()
        ds = g.add_set(x, values)
        ds.comment = self.formula.text()
        g.autoscale()
        self.main.changed()


# ===========================================================================
# Data > Transformations > Evaluate expression
# ===========================================================================
class EvaluateDialog(GraceDialog):
    title = "Evaluate Expression"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Source set(s):"))
        self.set_list = SetList(main, True)
        self.vbox.addWidget(self.set_list)
        form = QFormLayout()
        self.formula = QLineEdit("y = y")
        self.destination = make_combo(["Replace source set", "Create new set"])
        self.restriction = RegionChooser()
        form.addRow("Formula:", self.formula)
        form.addRow("Destination:", self.destination)
        form.addRow("Restrict to region:", self.restriction)
        form.addRow(QLabel("Names: x, y, dy, index, n; e.g.  y = (y - 3)^2,  x = x*1e3,  dy = sqrt(y)"))
        self.vbox.addLayout(form)
        self.add_buttons(["Apply", "Close"])

    def refresh(self):
        project = self.project()
        self.set_list.populate(project.current, project.cg())
        self.restriction.refresh(project)

    def apply(self):
        project = self.project()
        g = project.cg()
        for si in self.set_list.selected():
            ds = g.sets[si]
            n = len(ds)
            dy = None
            if ds.dy is not None:
                dy = ds.dy[:n]
            try:
                target, values = transforms.evaluate(self.formula.text(), ds.x[:n], ds.y[:n], dy)
            except ExprError as error:
                return self.warn(str(error))
            mask = self.restriction.mask(project, ds.x[:n], ds.y[:n])

            if self.destination.currentIndex() == 1:
                # New set: only the points in the region (all points without a region)
                if mask is None:
                    mask = np.ones(n, dtype=bool)
                new_dy = None
                if dy is not None:
                    new_dy = dy[mask]
                new_set = g.add_set(ds.x[:n][mask], ds.y[:n][mask], new_dy)
                new_set.comment = "%s on S%d" % (self.formula.text(), si)
                setattr(new_set, target, values[mask])
            else:
                # Replace: change only the points in the region, keep the others
                if mask is not None:
                    old = getattr(ds, target)
                    if old is None:
                        old = np.zeros(n)
                    merged = np.array(old[:n], dtype=float)
                    merged[mask] = values[mask]
                    values = merged
                setattr(ds, target, values)       # the same as ds.y = values (or x, dy)
        self.main.changed()


# ===========================================================================
# Data > Transformations > Regression
# ===========================================================================
class RegressionDialog(GraceDialog):
    title = "Regression"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Apply to set:"))
        self.set_list = SetList(main, False)
        self.vbox.addWidget(self.set_list)
        form = QFormLayout()
        self.kind = make_combo(FIT_KINDS)
        self.degree = QSpinBox()
        self.degree.setRange(1, 12)
        self.degree.setValue(4)
        self.load_as = make_combo(["Smooth fitted curve", "Fitted values", "Residuals"])
        self.restriction = RegionChooser()
        form.addRow("Type of fit:", self.kind)
        form.addRow("Restrict to region:", self.restriction)
        form.addRow("Degree (polynomial):", self.degree)
        form.addRow("Load:", self.load_as)
        self.vbox.addLayout(form)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(140)
        self.vbox.addWidget(QLabel("Results:"))
        self.vbox.addWidget(self.results)
        self.add_buttons(["Apply", "Close"])

    def refresh(self):
        project = self.project()
        self.set_list.populate(project.current, project.cg())
        self.restriction.refresh(project)

    def apply(self):
        project = self.project()
        g = project.cg()
        selected = self.set_list.selected()
        if len(selected) == 0:
            return self.warn("Select a set.")
        si = selected[0]
        ds = g.sets[si]
        n = len(ds)
        x = ds.x[:n]
        y = ds.y[:n]
        mask = self.restriction.mask(project, x, y)
        if mask is not None:
            x = x[mask]
            y = y[mask]
        try:
            f, report = transforms.regression(x, y, self.kind.currentIndex(), self.degree.value())
        except (ExprError, np.linalg.LinAlgError, ValueError, TypeError) as error:
            return self.warn("Fit failed: " + str(error))

        mode = self.load_as.currentIndex()
        with np.errstate(all="ignore"):
            if mode == 0:
                good_x = x[np.isfinite(x)]
                smooth_x = np.linspace(good_x.min(), good_x.max(), 400)
                new_set = g.add_set(smooth_x, f(smooth_x))
            elif mode == 1:
                new_set = g.add_set(x, f(x))
            else:
                new_set = g.add_set(x, y - f(x))
                new_set.symbol.shape = 1
                new_set.line.type = 0
        new_set.comment = "fit of G%d.S%d" % (project.current, si)
        self.results.appendPlainText("--- G%d.S%d ---\n%s\n" % (project.current, si, report))
        self.main.changed()


# ===========================================================================
# Data > Transformations > (running averages, FFT, histograms, ...)
#
# One class handles all the simpler transformations. `kind` decides which
# options are shown and which function from transforms.py is called.
# ===========================================================================
TRANSFORMS = {
    "running": "Running Averages", "diff": "Differences", "integ": "Integration",
    "interp": "Interpolation / Splines", "fft": "Fourier Transforms", "hist": "Histograms",
    "corr": "Correlation", "sort": "Sort", "geom": "Geometric Transforms", "sample": "Sample Points",
}

RUNNING_KINDS = ["average", "median", "minimum", "maximum", "std. dev."]
DIFFERENCE_KINDS = ["centered", "forward", "backward"]
INTERPOLATION_METHODS = ["cubic spline", "linear"]
FFT_OUTPUTS = ["magnitude", "power", "phase", "real", "imaginary"]
FFT_WINDOWS = ["none", "hann", "hamming", "blackman", "bartlett"]
# Transformations where "replace the source set" makes sense
IN_PLACE_KINDS = ["sort", "geom", "sample", "running", "interp"]


class TransformDialog(GraceDialog):

    def __init__(self, main, kind):
        self.kind = kind
        self.title = TRANSFORMS[kind]
        super().__init__(main)
        self.vbox.addWidget(QLabel("Source set(s):"))
        self.set_list = SetList(main, kind != "corr")
        self.set_list.setMaximumHeight(130)
        self.vbox.addWidget(self.set_list)

        form = QFormLayout()
        if kind == "running":
            self.type_combo = make_combo(["Average", "Median", "Minimum", "Maximum", "Standard deviation"])
            self.window = QSpinBox()
            self.window.setRange(2, 100000)
            self.window.setValue(5)
            form.addRow("Type:", self.type_combo)
            form.addRow("Window length (points):", self.window)
        elif kind == "diff":
            self.type_combo = make_combo(["Centred", "Forward", "Backward"])
            form.addRow("Difference:", self.type_combo)
        elif kind == "integ":
            self.load_integral = QCheckBox("Create a set with the cumulative integral")
            self.load_integral.setChecked(True)
            form.addRow(self.load_integral)
        elif kind == "interp":
            self.method = make_combo(["Cubic spline (natural)", "Linear"])
            self.use_set_range = QCheckBox("Use the set's x range")
            self.use_set_range.setChecked(True)
            self.start = FloatEdit()
            self.stop = FloatEdit()
            self.length = QSpinBox()
            self.length.setRange(2, 1000000)
            self.length.setValue(500)
            form.addRow("Method:", self.method)
            form.addRow(self.use_set_range)
            form.addRow("Start:", self.start)
            form.addRow("Stop:", self.stop)
            form.addRow("Length:", self.length)
        elif kind == "fft":
            self.output = make_combo(["Magnitude", "Power", "Phase", "Real part", "Imaginary part"])
            self.fft_window = make_combo(["None", "Hann", "Hamming", "Blackman", "Bartlett"])
            self.one_sided = QCheckBox("One-sided (positive frequencies)")
            self.one_sided.setChecked(True)
            form.addRow("Output:", self.output)
            form.addRow("Window:", self.fft_window)
            form.addRow(self.one_sided)
            form.addRow(QLabel("Assumes evenly spaced x."))
        elif kind == "hist":
            self.bins = QSpinBox()
            self.bins.setRange(1, 100000)
            self.bins.setValue(30)
            self.lower = FloatEdit()
            self.upper = FloatEdit()
            self.lower.setPlaceholderText("auto")
            self.upper.setPlaceholderText("auto")
            self.normalize = QCheckBox("Normalize (probability density)")
            self.cumulative = QCheckBox("Cumulative")
            form.addRow("Number of bins:", self.bins)
            form.addRow("Lower limit:", self.lower)
            form.addRow("Upper limit:", self.upper)
            form.addRow(self.normalize)
            form.addRow(self.cumulative)
        elif kind == "corr":
            self.other_set = QComboBox()
            self.max_lag = QSpinBox()
            self.max_lag.setRange(1, 10000000)
            self.max_lag.setValue(100)
            self.normalize = QCheckBox("Normalize")
            self.normalize.setChecked(True)
            form.addRow("Correlate with:", self.other_set)
            form.addRow("Maximum lag (points):", self.max_lag)
            form.addRow(self.normalize)
        elif kind == "sort":
            self.sort_by = make_combo(["X", "Y"])
            self.descending = QCheckBox("Descending")
            form.addRow("Sort on:", self.sort_by)
            form.addRow(self.descending)
        elif kind == "geom":
            self.angle = FloatEdit("0")
            self.center_x = FloatEdit("0")
            self.center_y = FloatEdit("0")
            self.scale_x = FloatEdit("1")
            self.scale_y = FloatEdit("1")
            self.shift_x = FloatEdit("0")
            self.shift_y = FloatEdit("0")
            form.addRow("Rotation (degrees):", self.angle)
            form.addRow("Rotation centre X:", self.center_x)
            form.addRow("Rotation centre Y:", self.center_y)
            form.addRow("Scale X:", self.scale_x)
            form.addRow("Scale Y:", self.scale_y)
            form.addRow("Translate X:", self.shift_x)
            form.addRow("Translate Y:", self.shift_y)
        elif kind == "sample":
            self.sample_start = QSpinBox()
            self.sample_start.setRange(0, 10000000)
            self.sample_step = QSpinBox()
            self.sample_step.setRange(1, 10000000)
            self.sample_step.setValue(2)
            form.addRow("Start at point:", self.sample_start)
            form.addRow("Take every Nth:", self.sample_step)

        self.restriction = RegionChooser()
        form.addRow("Restrict to region:", self.restriction)
        self.in_place = QCheckBox("Replace the source set instead of creating a new one")
        if kind in IN_PLACE_KINDS:
            form.addRow(self.in_place)
        self.vbox.addLayout(form)

        self.results = None
        if kind == "integ":
            self.results = QPlainTextEdit()
            self.results.setReadOnly(True)
            self.results.setMaximumHeight(110)
            self.vbox.addWidget(self.results)
        self.add_buttons(["Apply", "Close"])

    def refresh(self):
        project = self.project()
        self.set_list.populate(project.current, project.cg())
        self.restriction.refresh(project)
        if self.kind == "corr":
            keep = self.other_set.currentIndex()
            self.other_set.clear()
            self.other_set.addItem("itself (autocorrelation)")
            g = project.cg()
            for si in range(len(g.sets)):
                self.other_set.addItem("S%d  %s" % (si, g.sets[si].legend))
            self.other_set.setCurrentIndex(max(0, keep))

    def apply(self):
        selected = self.set_list.selected()
        if len(selected) == 0:
            return self.warn("Select a source set.")
        try:
            for si in selected:
                self.transform_one_set(si)
        except (ExprError, ValueError, np.linalg.LinAlgError) as error:
            return self.warn(str(error))
        self.main.changed()

    def transform_one_set(self, si):
        project = self.project()
        g = project.cg()
        ds = g.sets[si]
        n = len(ds)
        x = ds.x[:n]
        y = ds.y[:n]
        dy_all = None
        if ds.dy is not None:
            dy_all = ds.dy[:n]
        # Only use the points inside the chosen region
        mask = self.restriction.mask(project, x, y)
        if mask is not None:
            x = x[mask]
            y = y[mask]
            if dy_all is not None:
                dy_all = dy_all[mask]
        n = len(x)
        new_dy = None
        kind = self.kind

        if kind == "running":
            new_x, new_y = transforms.running(x, y, self.window.value(),
                                              RUNNING_KINDS[self.type_combo.currentIndex()])
        elif kind == "diff":
            new_x, new_y = transforms.differences(x, y, DIFFERENCE_KINDS[self.type_combo.currentIndex()])
        elif kind == "integ":
            new_x, new_y, total = transforms.integrate(x, y)
            self.results.appendPlainText("G%d.S%d: integral = %.10g" % (project.current, si, total))
            if not self.load_integral.isChecked():
                return
        elif kind == "interp":
            if self.use_set_range.isChecked():
                good_x = x[np.isfinite(x)]
                lo = good_x.min()
                hi = good_x.max()
            else:
                lo = self.start.value()
                hi = self.stop.value()
            new_x = np.linspace(lo, hi, self.length.value())
            new_y = transforms.interpolate(x, y, new_x, INTERPOLATION_METHODS[self.method.currentIndex()])
        elif kind == "fft":
            new_x, new_y = transforms.fourier(x, y, FFT_OUTPUTS[self.output.currentIndex()],
                                              FFT_WINDOWS[self.fft_window.currentIndex()],
                                              self.one_sided.isChecked())
        elif kind == "hist":
            lo = None
            hi = None
            if self.lower.text().strip() != "":
                lo = self.lower.value()
            if self.upper.text().strip() != "":
                hi = self.upper.value()
            edges, counts = transforms.histogram(y, self.bins.value(), lo, hi,
                                                 self.normalize.isChecked(), self.cumulative.isChecked())
            # Drawn as "left stairs": one more x than counts, so repeat the first count
            new_x = edges
            new_y = np.concatenate([[counts[0]], counts])
        elif kind == "corr":
            other = self.other_set.currentIndex() - 1          # -1 means "itself"
            y2 = None
            if other >= 0:
                y2 = g.sets[other].y
            new_x, new_y = transforms.correlation(y, y2, self.max_lag.value(), self.normalize.isChecked())
        elif kind == "sort":
            dy = dy_all
            if self.sort_by.currentIndex() == 0:
                by = "x"
            else:
                by = "y"
            new_x, new_y, new_dy = transforms.sort_xy(x, y, dy, by, self.descending.isChecked())
        elif kind == "geom":
            new_x, new_y = transforms.geometric(x, y, self.angle.value(), self.center_x.value(),
                                                self.center_y.value(), self.scale_x.value(),
                                                self.scale_y.value(), self.shift_x.value(), self.shift_y.value())
            if dy_all is not None:
                new_dy = dy_all * abs(self.scale_y.value())
        else:   # sample
            start = self.sample_start.value()
            step = self.sample_step.value()
            new_x, new_y = transforms.sample(x, y, start, step)
            if dy_all is not None:
                new_dy = dy_all[start::step].copy()

        if self.in_place.isChecked() and kind in IN_PLACE_KINDS:
            ds.x = new_x
            ds.y = new_y
            ds.set_errors("xy", [])            # x errors etc. don't survive these transforms
            ds.dy = new_dy
        else:
            new_set = g.add_set(new_x, new_y, new_dy)
            new_set.comment = "%s of S%d" % (self.title.lower(), si)
            if kind == "hist":
                new_set.line.type = 2          # left stairs
