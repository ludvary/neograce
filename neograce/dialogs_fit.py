"""
dialogs_fit.py - Data > Transformations > Non-linear curve fitting.

You type a formula with parameters a0..a9 (or pick a preset), give starting
values, and press Fit. The fit itself is transforms.nonlinear_fit().
After a successful fit the results are copied into the "Initial" column,
so pressing Fit again continues from there (just like xmgrace).
"""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QWidget)

from . import transforms
from .dialogs_base import GraceDialog, RegionChooser, SetList, make_combo
from .transforms import FIT_PRESETS, ExprError
from .widgets import FloatEdit

# Columns of the parameter table
COL_NAME = 0
COL_VALUE = 1
COL_BOUNDED = 2
COL_LOWER = 3
COL_UPPER = 4


class NonlinearFitDialog(GraceDialog):
    title = "Non-linear Curve Fitting"

    def __init__(self, main):
        super().__init__(main)
        self.vbox.addWidget(QLabel("Source set:"))
        self.set_list = SetList(main, False)
        self.set_list.setMaximumHeight(110)
        self.vbox.addWidget(self.set_list)

        form = QFormLayout()
        self.preset = make_combo(list(FIT_PRESETS))
        self.preset.currentIndexChanged.connect(self.on_preset_chosen)
        self.formula = QLineEdit("y = a0*exp(-x/a1) + a2")
        self.formula.textChanged.connect(self.update_parameter_table)
        form.addRow("Preset:", self.preset)
        form.addRow("Formula:", self.formula)
        self.vbox.addLayout(form)

        self.params = QTableWidget(0, 5)
        self.params.setHorizontalHeaderLabels(["Parameter", "Initial / result", "Bounded", "Lower", "Upper"])
        self.params.verticalHeader().setVisible(False)
        self.params.horizontalHeader().setStretchLastSection(True)
        self.params.setMinimumHeight(150)
        self.vbox.addWidget(self.params)

        tabs = QTabWidget()
        self.vbox.addWidget(tabs)

        page = QWidget()
        form = QFormLayout(page)
        self.iterations = QSpinBox()
        self.iterations.setRange(1, 10000)
        self.iterations.setValue(200)
        self.weights = make_combo(["None", "1/y²", "1/dy² (needs xydy set)"])
        self.restrict = QCheckBox("Only fit x in range")
        self.x_min = FloatEdit("0")
        self.x_max = FloatEdit("1")
        range_row = QHBoxLayout()
        range_row.addWidget(self.restrict)
        range_row.addWidget(self.x_min)
        range_row.addWidget(QLabel("to"))
        range_row.addWidget(self.x_max)
        form.addRow("Max iterations:", self.iterations)
        self.restriction = RegionChooser()
        form.addRow("Weights:", self.weights)
        form.addRow(range_row)
        form.addRow("Restrict to region:", self.restriction)
        tabs.addTab(page, "Options")

        page = QWidget()
        form = QFormLayout(page)
        self.load_as = make_combo(["Smooth fitted curve", "Fitted values at data x", "Residuals",
                                   "Nothing (parameters only)"])
        self.curve_points = QSpinBox()
        self.curve_points.setRange(10, 100000)
        self.curve_points.setValue(500)
        self.extend = QCheckBox("Extend curve to the whole x axis range")
        form.addRow("Load:", self.load_as)
        form.addRow("Curve points:", self.curve_points)
        form.addRow(self.extend)
        tabs.addTab(page, "Output")

        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(130)
        self.vbox.addWidget(self.results)
        self.add_buttons(["Fit", "Close"])
        self.update_parameter_table()
        self.resize(560, 760)

    def refresh(self):
        project = self.project()
        self.set_list.populate(project.current, project.cg())
        self.restriction.refresh(project)

    def on_preset_chosen(self):
        name = self.preset.currentText()
        if name != "Custom":
            self.formula.setText(FIT_PRESETS[name])

    def cell_text(self, row, column, default):
        item = self.params.item(row, column)
        if item is None:
            return default
        return item.text()

    def update_parameter_table(self):
        """Make one row per parameter in the formula, keeping values already typed in."""
        # Remember what's in the table now: name -> (value, bounded, lower, upper)
        old = {}
        for row in range(self.params.rowCount()):
            name = self.cell_text(row, COL_NAME, "")
            if name == "":
                continue
            checkbox = self.params.cellWidget(row, COL_BOUNDED)
            old[name] = (self.cell_text(row, COL_VALUE, "1"), checkbox.isChecked(),
                         self.cell_text(row, COL_LOWER, "-1e30"), self.cell_text(row, COL_UPPER, "1e30"))

        numbers = transforms.fit_params(self.formula.text())
        self.params.setRowCount(len(numbers))
        for row in range(len(numbers)):
            name = "a%d" % numbers[row]
            value = "1"
            bounded = False
            lower = "-1e30"
            upper = "1e30"
            if name in old:
                value, bounded, lower, upper = old[name]

            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)          # not editable
            self.params.setItem(row, COL_NAME, name_item)
            self.params.setItem(row, COL_VALUE, QTableWidgetItem(value))
            checkbox = QCheckBox()
            checkbox.setChecked(bounded)
            self.params.setCellWidget(row, COL_BOUNDED, checkbox)
            self.params.setItem(row, COL_LOWER, QTableWidgetItem(lower))
            self.params.setItem(row, COL_UPPER, QTableWidgetItem(upper))
        self.params.resizeColumnsToContents()

    def parameter_number(self, row):
        return int(self.cell_text(row, COL_NAME, "a0")[1:])        # "a3" -> 3

    def on_fit(self):
        project = self.project()
        g = project.cg()
        selected = self.set_list.selected()
        if len(selected) == 0:
            return self.warn("Select a set to fit.")
        si = selected[0]
        ds = g.sets[si]
        n = len(ds)
        x = ds.x[:n]
        y = ds.y[:n]

        # Read starting values and bounds from the table
        guess = {}
        bounds = {}
        try:
            for row in range(self.params.rowCount()):
                k = self.parameter_number(row)
                guess[k] = float(self.cell_text(row, COL_VALUE, "1"))
                if self.params.cellWidget(row, COL_BOUNDED).isChecked():
                    lower = float(self.cell_text(row, COL_LOWER, "-1e30"))
                    upper = float(self.cell_text(row, COL_UPPER, "1e30"))
                    bounds[k] = (lower, upper)
            use = np.ones(n, dtype=bool)                 # which points take part in the fit
            if self.restrict.isChecked():
                use = (x >= self.x_min.value()) & (x <= self.x_max.value())
            region = self.restriction.mask(project, x, y)
            if region is not None:
                use = use & region
        except ValueError:
            return self.warn("Initial values and bounds must be numbers.")

        weights = None
        with np.errstate(all="ignore"):
            if self.weights.currentIndex() == 1:
                weights = 1.0 / y ** 2
            elif self.weights.currentIndex() == 2:
                if ds.dy is None:
                    return self.warn("1/dy² weighting needs a set with dy values.")
                weights = 1.0 / ds.dy[:n] ** 2
        if weights is not None:
            weights = weights[use]

        try:
            params, errors, report, f = transforms.nonlinear_fit(
                self.formula.text(), x[use], y[use], guess, bounds, weights, self.iterations.value())
        except ExprError as error:
            return self.warn(str(error))

        # Put the results back into the table as the next starting values
        for row in range(self.params.rowCount()):
            k = self.parameter_number(row)
            self.params.item(row, COL_VALUE).setText("%.8g" % params[k])
        self.results.appendPlainText("--- fit of G%d.S%d ---\n%s\n" % (project.current, si, report))

        mode = self.load_as.currentIndex()
        if mode == 3:
            return
        with np.errstate(all="ignore"):
            if mode == 0:
                used_x = x[use]
                used_x = used_x[np.isfinite(used_x)]
                if self.extend.isChecked():
                    lo = g.xaxis.min
                    hi = g.xaxis.max
                else:
                    lo = used_x.min()
                    hi = used_x.max()
                if g.xaxis.scale == "log" and lo > 0:
                    curve_x = np.geomspace(lo, hi, self.curve_points.value())   # even on a log axis
                else:
                    curve_x = np.linspace(lo, hi, self.curve_points.value())
                new_set = g.add_set(curve_x, f(curve_x))
            elif mode == 1:
                new_set = g.add_set(x, f(x))
            else:
                new_set = g.add_set(x, y - f(x))
                new_set.symbol.shape = 1
                new_set.line.type = 0
        new_set.comment = "fit of S%d: %s" % (si, self.formula.text())
        self.main.changed()
