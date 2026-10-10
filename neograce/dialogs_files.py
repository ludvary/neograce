"""
dialogs_files.py - reading data files, printing/exporting, and preferences.
"""
import os

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem)

from . import io_formats, latex
from .dialogs_base import GraceDialog, make_combo
from .model import SET_TYPES
from .render import EXPORT_FORMATS, EXTENSIONS

DATA_FILE_FILTER = "Data files (*.dat *.txt *.csv *.xy *.out);;All files (*)"

# Shown in the "Set type" combo boxes, in the order of model.SET_TYPES
SET_TYPE_LABELS = ["XY", "XY DX", "XY DY", "XY DX DX (asymmetric)", "XY DY DY (asymmetric)",
                   "XY DX DY", "XY DX DX DY DY"]


# ===========================================================================
# Data > Import > ASCII
# ===========================================================================
class ImportAsciiDialog(GraceDialog):
    title = "Read Sets"

    def __init__(self, main):
        super().__init__(main)
        form = QFormLayout()
        file_row = QHBoxLayout()
        self.path = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        file_row.addWidget(self.path)
        file_row.addWidget(browse)
        self.mode = make_combo(["Single set", "NXY (x y1 y2 …)", "Block data"])
        self.set_type = make_combo(SET_TYPE_LABELS)
        self.columns = QLineEdit("1:2")
        self.columns.setToolTip("Block data only: one or more 1-based column specs, e.g.  1:2 2:3 1:3.\n"
                                "Columns after x:y are the error columns of the set type.")
        self.graph = QComboBox()
        self.autoscale = QCheckBox("Autoscale on read")
        self.autoscale.setChecked(True)
        form.addRow("File:", file_row)
        form.addRow("Load as:", self.mode)
        form.addRow("Set type:", self.set_type)
        form.addRow("Block columns:", self.columns)
        form.addRow("Read to graph:", self.graph)
        form.addRow(self.autoscale)
        self.vbox.addLayout(form)
        self.add_buttons(["OK", "Cancel"])

    def browse(self):
        path, selected_filter = QFileDialog.getOpenFileName(self, "Select data file",
                                                            os.path.dirname(self.path.text()), DATA_FILE_FILTER)
        if path:
            self.path.setText(path)

    def refresh(self):
        project = self.project()
        self.graph.clear()
        for i in range(len(project.graphs)):
            self.graph.addItem("G%d" % i)
        self.graph.setCurrentIndex(project.current)

    def apply(self):
        path = self.path.text().strip()
        if not os.path.isfile(path):
            return self.warn("Choose an existing data file.")
        modes = ["single", "nxy", "block"]
        mode = modes[self.mode.currentIndex()]
        set_type = SET_TYPES[self.set_type.currentIndex()]
        try:
            columns = None
            if mode == "block":
                columns = io_formats.parse_column_list(self.columns.text())
            count = self.main.load_data(path, mode, set_type, columns, self.graph.currentIndex(),
                                        self.autoscale.isChecked())
        except (ValueError, OSError) as error:
            return self.warn(str(error))
        if count == 0:
            return self.warn("No numeric data found in that file.")
        self.main.statusBar().showMessage("Read %d set(s) from %s" % (count, os.path.basename(path)), 5000)


# ===========================================================================
# Data > Import > Block data   (pick column combinations like 1:2, 2:3, 1:3)
# ===========================================================================
class BlockDataDialog(GraceDialog):
    title = "Block Data"

    def __init__(self, main):
        super().__init__(main)
        self.blocks = []            # list of 2D arrays from the file
        self.names = []             # column names from the header line, if any

        file_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("Data file with several columns")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        load = QPushButton("Load")
        load.clicked.connect(self.load_file)
        file_row.addWidget(self.path, 1)
        file_row.addWidget(browse)
        file_row.addWidget(load)
        self.vbox.addLayout(file_row)

        self.info = QLabel("Load a file to see its columns.")
        self.vbox.addWidget(self.info)
        self.preview = QTableWidget(0, 0)
        self.preview.setMinimumHeight(170)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vbox.addWidget(self.preview)

        grid = QGridLayout()
        self.block = QComboBox()
        self.block.currentIndexChanged.connect(self.show_block)
        self.x_column = QComboBox()
        self.y_columns = QListWidget()
        self.y_columns.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.y_columns.setMaximumHeight(120)
        self.dx_column = QComboBox()
        self.dy_column = QComboBox()
        self.specs = QLineEdit()
        self.specs.setPlaceholderText("or type pairs, e.g.  1:2 2:3 1:3   (x:y or x:y:dy, 1-based)")
        self.spec_type = make_combo(SET_TYPE_LABELS)
        self.spec_type.setToolTip("How the columns after x:y in typed pairs are used")
        self.graph = QComboBox()
        self.autoscale = QCheckBox("Autoscale after creating sets")
        self.autoscale.setChecked(True)
        grid.addWidget(QLabel("Block:"), 0, 0)
        grid.addWidget(self.block, 0, 1)
        grid.addWidget(QLabel("X from column:"), 1, 0)
        grid.addWidget(self.x_column, 1, 1)
        grid.addWidget(QLabel("Y from column(s):"), 2, 0)
        grid.addWidget(self.y_columns, 2, 1)
        grid.addWidget(QLabel("dX from column:"), 3, 0)
        grid.addWidget(self.dx_column, 3, 1)
        grid.addWidget(QLabel("dY from column:"), 4, 0)
        grid.addWidget(self.dy_column, 4, 1)
        grid.addWidget(QLabel("Column pairs:"), 5, 0)
        grid.addWidget(self.specs, 5, 1)
        grid.addWidget(QLabel("Pairs set type:"), 6, 0)
        grid.addWidget(self.spec_type, 6, 1)
        grid.addWidget(QLabel("Into graph:"), 7, 0)
        grid.addWidget(self.graph, 7, 1)
        grid.addWidget(self.autoscale, 8, 1)
        self.vbox.addLayout(grid)
        self.add_buttons(["Create sets", "Close"])
        self.resize(620, 640)

    def refresh(self):
        project = self.project()
        self.graph.clear()
        for i in range(len(project.graphs)):
            self.graph.addItem("G%d" % i)
        self.graph.setCurrentIndex(project.current)

    def browse(self):
        path, selected_filter = QFileDialog.getOpenFileName(self, "Block data file", "", DATA_FILE_FILTER)
        if path:
            self.path.setText(path)
            self.load_file()

    def load_file(self):
        path = self.path.text().strip()
        try:
            self.blocks = io_formats.read_ascii(path)
            self.names = io_formats.column_names(path)
        except OSError as error:
            return self.warn(str(error))
        if len(self.blocks) == 0:
            return self.warn("No numeric data found in that file.")
        self.block.blockSignals(True)
        self.block.clear()
        for i in range(len(self.blocks)):
            shape = self.blocks[i].shape
            self.block.addItem("Block %d  (%d rows × %d columns)" % (i + 1, shape[0], shape[1]))
        self.block.blockSignals(False)
        self.show_block()

    def column_title(self, j):
        """"2  signal" if the file has a header, else just "2"."""
        title = str(j + 1)
        if j < len(self.names) and self.names[j]:
            title = title + "  " + self.names[j]
        return title

    def current_block(self):
        return self.blocks[max(0, self.block.currentIndex())]

    def show_block(self):
        a = self.current_block()
        rows = a.shape[0]
        columns = a.shape[1]
        self.info.setText("%d rows, %d columns. Pick X and one or more Y columns, or type column pairs."
                          % (rows, columns))
        titles = []
        for j in range(columns):
            titles.append(self.column_title(j))

        shown_rows = min(rows, 60)
        self.preview.setColumnCount(columns)
        self.preview.setRowCount(shown_rows)
        self.preview.setHorizontalHeaderLabels(titles)
        for i in range(shown_rows):
            for j in range(columns):
                self.preview.setItem(i, j, QTableWidgetItem("%.6g" % a[i, j]))

        self.x_column.clear()
        self.x_column.addItems(titles)
        for combo in (self.dx_column, self.dy_column):
            combo.clear()
            combo.addItem("none")
            combo.addItems(titles)
        self.y_columns.clear()
        self.y_columns.addItems(titles)
        if columns > 1:
            self.y_columns.item(1).setSelected(True)

    def on_create_sets(self):
        if len(self.blocks) == 0:
            return self.warn("Load a file first.")
        try:
            if self.specs.text().strip() != "":
                specs = io_formats.parse_column_list(self.specs.text())
                set_type = SET_TYPES[self.spec_type.currentIndex()]
            else:
                x_col = self.x_column.currentIndex()
                dx_col = self.dx_column.currentIndex() - 1           # -1 means "none"
                dy_col = self.dy_column.currentIndex() - 1
                y_cols = []
                for item in self.y_columns.selectedItems():
                    y_cols.append(self.y_columns.row(item))
                if len(y_cols) == 0:
                    return self.warn("Select at least one Y column.")
                y_cols.sort()
                specs = []
                for y_col in y_cols:
                    spec = [x_col, y_col]
                    if dx_col >= 0:
                        spec.append(dx_col)
                    if dy_col >= 0:
                        spec.append(dy_col)
                    specs.append(spec)
                set_type = "xy"
                if dx_col >= 0 and dy_col >= 0:
                    set_type = "xydxdy"
                elif dx_col >= 0:
                    set_type = "xydx"
                elif dy_col >= 0:
                    set_type = "xydy"
            new_sets = io_formats.blocks_to_sets([self.current_block()], "block", set_type, specs)
        except ValueError as error:
            return self.warn(str(error))

        g = self.project().graphs[self.graph.currentIndex()]
        base = os.path.basename(self.path.text())
        for k in range(len(new_sets)):
            x, y, this_type, errors = new_sets[k]
            ds = g.add_set(x, y)
            ds.set_errors(this_type, errors)
            column_text = []
            for c in specs[k]:
                column_text.append(str(c + 1))
            ds.comment = base + " cols " + ":".join(column_text)
        if self.autoscale.isChecked():
            g.autoscale()
        self.main.changed()
        self.main.statusBar().showMessage("Created %d set(s) from %s" % (len(new_sets), base), 4000)


# ===========================================================================
# File > Print setup
# ===========================================================================
class PrintSetupDialog(GraceDialog):
    title = "Print / Export Setup"

    def __init__(self, main):
        super().__init__(main)
        form = QFormLayout()
        self.device = make_combo(EXPORT_FORMATS)
        self.device.currentIndexChanged.connect(self.fix_extension)
        file_row = QHBoxLayout()
        self.path = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        file_row.addWidget(self.path)
        file_row.addWidget(browse)
        self.dpi = QSpinBox()
        self.dpi.setRange(36, 2400)
        self.dpi.setSuffix(" dpi")
        self.transparent = QCheckBox("Transparent background (PNG, SVG, PDF)")
        form.addRow("Device:", self.device)
        form.addRow("File name:", file_row)
        form.addRow("Resolution (PNG/JPEG):", self.dpi)
        form.addRow(self.transparent)
        self.vbox.addLayout(form)
        self.add_buttons(["Print to file", "Accept", "Close"])

    def fix_extension(self):
        """When the device changes, change the file extension to match."""
        path = self.path.text().strip()
        if path:
            base = os.path.splitext(path)[0]
            self.path.setText(base + EXTENSIONS[self.device.currentText()])

    def browse(self):
        extension = EXTENSIONS[self.device.currentText()]
        path, selected_filter = QFileDialog.getSaveFileName(self, "Export to", self.path.text(),
                                                            "%s (*%s)" % (self.device.currentText(), extension))
        if path:
            if not path.lower().endswith(extension):
                path = path + extension
            self.path.setText(path)

    def refresh(self):
        settings = self.main.print_settings
        self.device.blockSignals(True)
        self.device.setCurrentText(settings["fmt"])
        self.device.blockSignals(False)
        if settings["path"]:
            self.path.setText(settings["path"])
        else:
            self.path.setText(self.main.default_export_path(settings["fmt"]))
        self.dpi.setValue(settings["dpi"])
        self.transparent.setChecked(settings["transparent"])

    def apply(self):
        settings = self.main.print_settings
        settings["fmt"] = self.device.currentText()
        settings["path"] = self.path.text().strip()
        settings["dpi"] = self.dpi.value()
        settings["transparent"] = self.transparent.isChecked()

    def on_print_to_file(self):
        self.apply()
        self.main.do_export()


# ===========================================================================
# Edit > Preferences (autosave and undo)
# ===========================================================================
class PreferencesDialog(GraceDialog):
    title = "Preferences"

    def __init__(self, main):
        super().__init__(main)
        box = QGroupBox("Autosave")
        form = QFormLayout(box)
        self.autosave = QCheckBox("Autosave periodically")
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setSuffix(" min")
        self.mode = make_combo(["Write a backup copy (name.autosave.ngr)", "Save the project file itself"])
        self.folder = QLineEdit()
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(choose)
        open_folder = QPushButton("Open autosave folder")
        open_folder.clicked.connect(self.main.open_autosave_folder)
        form.addRow(self.autosave)
        form.addRow("Every:", self.minutes)
        form.addRow("Mode:", self.mode)
        form.addRow("Folder for unsaved projects:", folder_row)
        form.addRow(open_folder)
        self.vbox.addWidget(box)

        box = QGroupBox("LaTeX")
        form = QFormLayout(box)
        self.tex_folder = QLineEdit()
        self.tex_folder.setPlaceholderText("empty = find latex and dvisvgm automatically")
        choose_tex = QPushButton("Choose…")
        choose_tex.clicked.connect(self.choose_tex_folder)
        tex_row = QHBoxLayout()
        tex_row.addWidget(self.tex_folder, 1)
        tex_row.addWidget(choose_tex)
        test_button = QPushButton("Test LaTeX")
        test_button.clicked.connect(self.test_latex)
        clear_button = QPushButton("Clear LaTeX cache")
        clear_button.clicked.connect(self.clear_latex_cache)
        button_row = QHBoxLayout()
        button_row.addWidget(test_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        self.latex_result = QLabel("")
        self.latex_result.setWordWrap(True)
        form.addRow("TeX programs folder:", tex_row)
        form.addRow(button_row)
        form.addRow(self.latex_result)
        self.vbox.addWidget(box)

        box = QGroupBox("Undo")
        form = QFormLayout(box)
        self.undo_levels = QSpinBox()
        self.undo_levels.setRange(5, 2000)
        form.addRow("Undo levels:", self.undo_levels)
        self.vbox.addWidget(box)
        self.add_buttons(["Apply", "Accept", "Close"])

    def choose_tex_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with latex and dvisvgm", self.tex_folder.text())
        if folder:
            self.tex_folder.setText(folder)

    def test_latex(self):
        engine = latex.engine()
        engine.tool_folder = self.tex_folder.text().strip()
        ok, message = engine.test()
        if ok:
            self.latex_result.setText("✓ " + message)
        else:
            self.latex_result.setText("✗ " + message)

    def clear_latex_cache(self):
        latex.engine().clear_cache()
        self.latex_result.setText("Cache cleared; labels will be typeset again.")
        self.main.changed(False)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Autosave folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def refresh(self):
        prefs = self.main.prefs
        self.autosave.setChecked(prefs["autosave"])
        self.minutes.setValue(prefs["autosave_minutes"])
        if prefs["autosave_mode"] == "backup":
            self.mode.setCurrentIndex(0)
        else:
            self.mode.setCurrentIndex(1)
        self.folder.setText(prefs["autosave_dir"])
        self.undo_levels.setValue(prefs["undo_levels"])
        self.tex_folder.setText(prefs["tex_folder"])

    def apply(self):
        prefs = self.main.prefs
        prefs["autosave"] = self.autosave.isChecked()
        prefs["autosave_minutes"] = self.minutes.value()
        if self.mode.currentIndex() == 0:
            prefs["autosave_mode"] = "backup"
        else:
            prefs["autosave_mode"] = "overwrite"
        prefs["autosave_dir"] = self.folder.text().strip()
        prefs["undo_levels"] = self.undo_levels.value()
        prefs["tex_folder"] = self.tex_folder.text().strip()
        self.main.prefs_changed()
