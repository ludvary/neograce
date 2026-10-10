"""
mainwindow.py - the main window: menus, the button column, file handling,
undo/redo and autosave.

The most important function is changed(). EVERY edit, anywhere in the
program, ends by calling main.changed(). It
    1. stores an undo snapshot,
    2. repaints the canvas,
    3. tells every open dialog to reload its values.
"""
import os
import time

from PySide6.QtCore import QDateTime, QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import __version__, agr, io_formats, latex
from .canvas import PlotCanvas
from .dialogs import create_dialog
from .icons import make_icon
from .model import PAGE_SIZES, Project, restore, snapshot
from .render import EXTENSIONS, export_project, set_range_t
from .theme import DARK_DEFAULT, LIGHT_DEFAULT, THEMES, apply_theme, system_prefers_dark

# Menu entries of the Data > Transformations submenu: (text, dialog name)
TRANSFORM_MENU = [("Histograms…", "t_hist"), ("Fourier transforms…", "t_fft"),
                  ("Running averages…", "t_running"), ("Differences…", "t_diff"),
                  ("Integration…", "t_integ"), ("Interpolation / splines…", "t_interp"),
                  ("Correlation…", "t_corr"), ("Sample points…", "t_sample"),
                  ("Sort…", "t_sort"), ("Geometric transforms…", "t_geom")]

MODE_NAMES = {"zoom": "Zoom", "zoomx": "Zoom X", "zoomy": "Zoom Y", "autoo": "Pick a set",
              "place_text": "Place text", "place_line": "Draw line", "place_arrow": "Draw arrow",
              "place_box": "Draw box", "place_ellipse": "Draw ellipse", "region": "Define region"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = Project()
        self.canvas = PlotCanvas(self.project)
        self.dialogs = {}               # dialog name -> dialog, created on first use
        self.print_settings = {"fmt": "PDF", "path": "", "dpi": 300, "transparent": False}

        # Undo: lists of snapshots (see model.snapshot). self.current_snapshot is the
        # state right now; before each change it is pushed onto undo_stack.
        self.undo_stack = []
        self.redo_stack = []
        self.current_snapshot = snapshot(self.project)
        self.last_merge_key = None      # for merging quick repeated edits (wheel zoom)
        self.last_change_time = 0.0

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)

        # Report LaTeX problems in the status bar (checked twice a second)
        self.shown_latex_error = ""
        self.warned_no_latex = False
        self.latex_status_timer = QTimer(self)
        self.latex_status_timer.timeout.connect(self.check_latex_status)
        self.latex_status_timer.start(500)

        self.tool_buttons = []          # all buttons with icons (recoloured per theme)
        self.mode_buttons = {}          # mode name -> button
        self.build_ui()
        self.build_menus()

        self.canvas.locatorChanged.connect(self.on_locator)
        self.canvas.projectEdited.connect(self.on_canvas_edit)
        self.canvas.focusChanged.connect(self.on_focus_changed)
        self.canvas.editRequest.connect(self.on_edit_request)
        self.canvas.statusMessage.connect(self.statusBar().showMessage)
        self.canvas.modeChanged.connect(self.on_mode_changed)
        self.canvas.objectPlaced.connect(self.on_object_placed)
        self.canvas.regionDefined.connect(self.on_region_defined)

        # Settings are remembered between runs (QSettings = registry / config file)
        self.settings = QSettings("NeoGrace", "NeoGrace")
        if system_prefers_dark(QApplication.instance()):
            default_theme = DARK_DEFAULT
        else:
            default_theme = LIGHT_DEFAULT
        theme_name = self.settings.value("theme", default_theme)
        if theme_name not in THEMES:
            theme_name = default_theme
        self.canvas.match_page = self.settings.value("match_page", False, type=bool)
        self.match_action.setChecked(self.canvas.match_page)
        self.set_theme(theme_name)

        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not app_data:
            app_data = os.path.expanduser("~/.neograce")
        default_folder = os.path.join(app_data, "autosave")
        self.prefs = {
            "autosave": self.settings.value("autosave", True, type=bool),
            "autosave_minutes": self.settings.value("autosave_minutes", 5, type=int),
            "autosave_mode": self.settings.value("autosave_mode", "backup"),
            "autosave_dir": self.settings.value("autosave_dir", default_folder),
            "undo_levels": self.settings.value("undo_levels", 200, type=int),
            "tex_folder": self.settings.value("tex_folder", ""),
        }
        if not self.prefs["autosave_dir"]:
            self.prefs["autosave_dir"] = default_folder
        self.prefs_changed()
        self.update_undo_buttons()
        self.update_title()

    # =================================================================== layout
    def build_ui(self):
        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(10, 4, 10, 6)
        column.setSpacing(8)

        # ---- top bar: undo/redo, current graph, coordinates, mode, autosave status
        self.locator_bar = QFrame()
        self.locator_bar.setObjectName("Locator")          # the stylesheet styles it by this name
        bar = QHBoxLayout(self.locator_bar)
        bar.setContentsMargins(12, 5, 8, 5)
        bar.setSpacing(8)

        self.undo_button = self.make_header_button("undo", "Undo (Ctrl+Z)", self.undo)
        self.redo_button = self.make_header_button("redo", "Redo (Ctrl+Shift+Z)", self.redo)
        bar.addWidget(self.undo_button)
        bar.addWidget(self.redo_button)
        separator = QFrame()
        separator.setObjectName("HeaderRule")
        bar.addWidget(separator)

        self.graph_chip = QLabel("G0")
        self.graph_chip.setObjectName("Chip")
        bar.addWidget(self.graph_chip)
        coords_label = QLabel("X, Y")
        coords_label.setObjectName("CoordsLabel")
        bar.addWidget(coords_label)
        self.locator = QLabel("–")
        self.locator.setObjectName("Coords")
        self.locator.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bar.addWidget(self.locator)
        bar.addStretch(1)
        self.mode_chip = QLabel("")
        self.mode_chip.setObjectName("ModeChip")
        self.mode_chip.hide()
        bar.addWidget(self.mode_chip)
        self.autosave_label = QLabel("")
        self.autosave_label.setObjectName("CoordsLabel")
        bar.addWidget(self.autosave_label)
        column.addWidget(self.locator_bar)

        # ---- button column + canvas
        row = QHBoxLayout()
        row.setSpacing(10)
        self.toolpanel = self.build_toolpanel()
        row.addWidget(self.toolpanel)
        row.addWidget(self.canvas, 1)
        column.addLayout(row, 1)
        self.setCentralWidget(central)

        self.file_label = QLabel()
        self.statusBar().addPermanentWidget(self.file_label)
        self.statusBar().setSizeGripEnabled(False)

    def make_header_button(self, icon_name, tooltip, slot):
        button = QToolButton()
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setObjectName("HeaderButton")
        button.setIconSize(QSize(18, 18))
        button.setProperty("iconName", icon_name)
        button.clicked.connect(slot)
        self.tool_buttons.append(button)
        return button

    def build_toolpanel(self):
        """The left button column, in the same order and places as in xmgrace."""
        panel = QFrame()
        panel.setObjectName("ToolPanel")
        panel.setFixedWidth(96)
        self.panel_grid = QGridLayout(panel)
        self.panel_grid.setContentsMargins(6, 8, 6, 8)
        self.panel_grid.setHorizontalSpacing(4)
        self.panel_grid.setVerticalSpacing(3)

        #                icon         text     tooltip                                      slot              row col span
        self.add_tool("draw", "Draw", "Redraw", self.redraw, 0, 0, 2)
        self.add_mode_tool("zoom", "Zoom", "Zoom: drag a rectangle", "zoom", 1, 0, 2)
        self.add_tool("autoscale", "AS", "Autoscale the current graph", self.autoscale_xy, 2, 0, 2)
        self.add_rule(3)
        self.add_tool("zin", "Z", "Zoom in", self.zoom_in, 4, 0, 1)
        self.add_tool("zout", "z", "Zoom out", self.zoom_out, 4, 1, 1)
        self.add_tool("left", "", "Scroll left", self.scroll_left, 5, 0, 1)
        self.add_tool("right", "", "Scroll right", self.scroll_right, 5, 1, 1)
        self.add_tool("down", "", "Scroll down", self.scroll_down, 6, 0, 1)
        self.add_tool("up", "", "Scroll up", self.scroll_up, 6, 1, 1)
        self.add_rule(7)
        self.add_tool("autoticks", "AutoT", "Automatic tick spacing", self.autotick, 8, 0, 2)
        self.add_mode_tool("target", "AutoO", "Autoscale on a set (click it)", "autoo", 9, 0, 2)
        self.add_rule(10)
        self.add_mode_tool("zx", "ZX", "Zoom along X", "zoomx", 11, 0, 1)
        self.add_mode_tool("zy", "ZY", "Zoom along Y", "zoomy", 11, 1, 1)
        self.add_tool("ax", "AX", "Autoscale X", self.autoscale_x, 12, 0, 1)
        self.add_tool("ay", "AY", "Autoscale Y", self.autoscale_y, 12, 1, 1)
        self.add_tool("push", "PZ", "Push current world to the stack, then zoom", self.push_zoom, 13, 0, 1)
        self.add_tool("pop", "PU", "Pop world from the stack", self.pop_zoom, 13, 1, 1)
        self.panel_grid.setRowStretch(14, 1)
        self.add_tool("exit", "Exit", "Exit", self.close, 15, 0, 2)
        return panel

    def make_tool_button(self, icon_name, text, tooltip, row, column, span):
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setIconSize(QSize(18, 18))
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setProperty("iconName", icon_name)
        if text == "":
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)        # arrows
            button.setFixedHeight(32)
        elif span == 2:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)  # wide buttons
            button.setFixedHeight(32)
        else:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)   # half-width buttons
            button.setFixedHeight(44)
        self.tool_buttons.append(button)
        self.panel_grid.addWidget(button, row, column, 1, span)
        return button

    def add_tool(self, icon_name, text, tooltip, slot, row, column, span):
        button = self.make_tool_button(icon_name, text, tooltip, row, column, span)
        button.clicked.connect(slot)

    def add_mode_tool(self, icon_name, text, tooltip, mode, row, column, span):
        """A button that switches the canvas into a mouse mode (stays lit while active)."""
        button = self.make_tool_button(icon_name, text, tooltip, row, column, span)
        button.setCheckable(True)
        button.setProperty("mode", mode)
        button.clicked.connect(self.on_mode_button)
        self.mode_buttons[mode] = button

    def add_rule(self, row):
        line = QFrame()
        line.setObjectName("PanelRule")
        self.panel_grid.addWidget(line, row, 0, 1, 2)

    # =================================================================== menus
    def add_action(self, menu, text, slot, shortcut=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot is not None:
            action.triggered.connect(slot)
        else:
            action.setEnabled(False)        # not implemented yet: shown greyed out
        menu.addAction(action)
        return action

    def add_dialog_action(self, menu, text, dialog_name, shortcut=None):
        """A menu entry that opens a dialog. The dialog name is stored in the action."""
        action = self.add_action(menu, text, self.on_dialog_action, shortcut)
        action.setData(dialog_name)
        return action

    def add_toggle(self, menu, text, slot, checked):
        action = QAction(text, self)
        action.setCheckable(True)
        action.setChecked(checked)
        action.toggled.connect(slot)
        menu.addAction(action)
        return action

    def build_menus(self):
        bar = self.menuBar()

        menu = bar.addMenu("&File")
        self.add_action(menu, "New", self.file_new, "Ctrl+N")
        self.add_action(menu, "Open…", self.file_open, "Ctrl+O")
        self.add_action(menu, "Save", self.file_save, "Ctrl+S")
        self.add_action(menu, "Save as…", self.file_save_as, "Ctrl+Shift+S")
        self.add_action(menu, "Export as Grace project (.agr)…", self.file_export_agr)
        self.add_action(menu, "Revert to saved", self.file_revert)
        menu.addSeparator()
        self.add_dialog_action(menu, "Print setup…", "print")
        self.add_action(menu, "Print", self.print_page, "Ctrl+P")
        menu.addSeparator()
        self.add_action(menu, "Exit", self.close, "Ctrl+Q")

        menu = bar.addMenu("&Edit")
        self.undo_action = self.add_action(menu, "Undo", self.undo, "Ctrl+Z")
        self.redo_action = self.add_action(menu, "Redo", self.redo, "Ctrl+Shift+Z")
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        menu.addSeparator()
        self.add_dialog_action(menu, "Data sets…", "datasets")
        self.add_dialog_action(menu, "Set operations…", "setops")
        self.add_dialog_action(menu, "Arrange graphs…", "arrange")
        self.add_action(menu, "Autoscale all graphs", self.autoscale_all)
        self.add_dialog_action(menu, "Regions…", "regions")
        menu.addSeparator()
        self.add_dialog_action(menu, "Preferences…", "prefs", "Ctrl+,")

        menu = bar.addMenu("&Data")
        self.add_dialog_action(menu, "Create set from formula…", "formula")
        submenu = menu.addMenu("Transformations")
        self.add_dialog_action(submenu, "Evaluate expression…", "evaluate")
        self.add_dialog_action(submenu, "Regression…", "regression")
        self.add_dialog_action(submenu, "Non-linear curve fitting…", "nlfit", "Ctrl+F")
        submenu.addSeparator()
        for text, name in TRANSFORM_MENU:
            self.add_dialog_action(submenu, text, name)
        submenu = menu.addMenu("Import")
        self.add_dialog_action(submenu, "ASCII…", "import", "Ctrl+R")
        self.add_dialog_action(submenu, "Block data…", "block", "Ctrl+B")
        submenu = menu.addMenu("Export")
        self.add_action(submenu, "ASCII…", self.export_ascii)

        menu = bar.addMenu("&Plot")
        self.add_dialog_action(menu, "Plot appearance…", "plot")
        self.add_dialog_action(menu, "Graph appearance…", "graph")
        self.add_dialog_action(menu, "Set appearance…", "set")
        self.add_dialog_action(menu, "Axis properties…", "axis")

        menu = bar.addMenu("&View")
        theme_menu = menu.addMenu("Theme")
        self.theme_group = QActionGroup(self)        # only one theme can be checked
        self.theme_actions = {}
        for dark in (True, False):
            if dark:
                theme_menu.addSection("Dark")
            else:
                theme_menu.addSection("Light")
            for name in THEMES:
                if THEMES[name].dark != dark:
                    continue
                action = QAction(name, self)
                action.setCheckable(True)
                action.setData(name)
                action.triggered.connect(self.on_theme_action)
                self.theme_group.addAction(action)
                theme_menu.addAction(action)
                self.theme_actions[name] = action
        self.add_action(menu, "Next theme", self.next_theme, "Ctrl+T")
        self.match_action = self.add_toggle(menu, "Match page to theme (screen only)", self.set_match_page, False)
        menu.addSeparator()
        self.add_toggle(menu, "Show locator bar", self.locator_bar.setVisible, True)
        self.add_toggle(menu, "Show status bar", self.statusBar().setVisible, True)
        self.add_toggle(menu, "Show tool bar", self.toolpanel.setVisible, True)
        menu.addSeparator()
        self.add_action(menu, "Redraw", self.redraw, "Ctrl+L")

        menu = bar.addMenu("&Window")
        self.add_dialog_action(menu, "Drawing objects…", "objects", "Ctrl+D")

        menu = bar.addMenu("&Help")
        self.add_action(menu, "About…", self.about)

    # =================================================================== the central "something changed" function
    def changed(self, modified=True, merge_key=None):
        """Call after every edit.

        modified=False: only refresh the screen (e.g. a different graph was selected).
        merge_key: quick repeats with the same key (like wheel zooming) become ONE undo step.
        """
        if modified:
            self.project.modified = True
            now = time.monotonic()
            same_gesture = (merge_key is not None and merge_key == self.last_merge_key
                            and now - self.last_change_time < 0.8 and len(self.undo_stack) > 0)
            if not same_gesture:
                self.undo_stack.append(self.current_snapshot)
                levels = int(self.prefs_value("undo_levels", 200))
                while len(self.undo_stack) > levels:
                    del self.undo_stack[0]
            self.redo_stack = []
            self.current_snapshot = snapshot(self.project)
            self.last_merge_key = merge_key
            self.last_change_time = now
            self.update_undo_buttons()
        self.canvas.update()
        for name in self.dialogs:
            dialog = self.dialogs[name]
            if dialog.isVisible():
                dialog.refresh()
        self.update_title()

    def prefs_value(self, key, default):
        """Prefs may not exist yet while the window is being built."""
        if hasattr(self, "prefs") and key in self.prefs:
            return self.prefs[key]
        return default

    def update_title(self):
        project = self.project
        if project.filename:
            name = os.path.basename(project.filename)
        else:
            name = "Untitled"
        title = "NeoGrace: " + name
        if project.modified:
            title = title + " *"
        self.setWindowTitle(title)
        self.graph_chip.setText("G%d" % project.current)

        size_text = "%.0f×%.0f pt" % (project.page_w, project.page_h)
        for size_name in PAGE_SIZES:
            size = PAGE_SIZES[size_name]
            if abs(size[0] - project.page_w) < 1 and abs(size[1] - project.page_h) < 1:
                size_text = size_name
        self.file_label.setText("NeoGrace : " + size_text + " : File: " + name)

    def set_project(self, project):
        """Switch to another project (New / Open). Clears undo history."""
        self.project = project
        self.canvas.project = project
        self.undo_stack = []
        self.redo_stack = []
        self.current_snapshot = snapshot(project)
        self.update_undo_buttons()
        self.changed(False)

    # =================================================================== undo / redo
    def undo(self):
        if len(self.undo_stack) == 0:
            self.statusBar().showMessage("Nothing to undo", 2000)
            return
        self.redo_stack.append(self.current_snapshot)
        self.current_snapshot = self.undo_stack.pop()
        restore(self.project, self.current_snapshot)
        self.after_undo_redo("Undone")

    def redo(self):
        if len(self.redo_stack) == 0:
            self.statusBar().showMessage("Nothing to redo", 2000)
            return
        self.undo_stack.append(self.current_snapshot)
        self.current_snapshot = self.redo_stack.pop()
        restore(self.project, self.current_snapshot)
        self.after_undo_redo("Redone")

    def after_undo_redo(self, message):
        self.last_merge_key = None
        self.project.modified = True
        self.update_undo_buttons()
        self.changed(False)
        self.statusBar().showMessage("%s  (%d more undo, %d redo)" % (message, len(self.undo_stack),
                                                                     len(self.redo_stack)), 2500)

    def update_undo_buttons(self):
        can_undo = len(self.undo_stack) > 0
        can_redo = len(self.redo_stack) > 0
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)

    # =================================================================== slots for canvas signals
    def on_canvas_edit(self):
        self.changed(True, "view")      # zoom/pan/legend drags merge into one undo step

    def on_focus_changed(self, graph_index):
        self.changed(False)

    def on_locator(self, text):
        # text looks like "G0: X, Y = [1.5, 2.5]"
        colon = text.find(":")
        self.graph_chip.setText(text[:colon])
        coordinates = text[text.find("=") + 1:].strip().strip("[]")
        self.locator.setText(coordinates.replace(",", ",  "))

    def on_mode_changed(self, mode):
        for name in self.mode_buttons:
            self.mode_buttons[name].setChecked(name == mode)
        if mode in MODE_NAMES:
            self.mode_chip.setText(MODE_NAMES[mode])
            self.mode_chip.show()
        else:
            self.mode_chip.hide()

    def on_mode_button(self, checked):
        mode = self.sender().property("mode")
        if checked:
            self.canvas.set_mode(mode)
        else:
            self.canvas.set_mode("draw")

    def on_edit_request(self, what, graph_index, set_index):
        """Double click on the canvas: open the matching dialog."""
        if what == "object":
            self.show_dialog("objects").select_object(set_index)      # set_index holds the object index
            return
        self.project.current = graph_index
        self.changed(False)
        if what == "set":
            self.show_dialog("set").select_set(set_index)
        elif what == "xaxis" or what == "xlabel":
            self.show_dialog("axis").select_axis(0)
        elif what == "yaxis" or what == "ylabel":
            self.show_dialog("axis").select_axis(1)
        elif what == "altxlabel" or what == "altxaxis":
            self.show_dialog("axis").select_axis(2)
        elif what == "altylabel" or what == "altyaxis":
            self.show_dialog("axis").select_axis(3)
        elif what == "subtitle":
            self.show_dialog("graph").select_graph(graph_index, 1)
        elif what == "legend":
            self.show_dialog("graph").select_graph(graph_index, 2)
        elif what == "title":
            self.show_dialog("graph").select_graph(graph_index, 1)
        else:
            self.show_dialog("graph").select_graph(graph_index, 0)

    def check_latex_status(self):
        if self.project.text_mode == "grace":
            return
        engine = latex.engine()
        if not engine.available():
            if not self.warned_no_latex:
                self.warned_no_latex = True
                self.statusBar().showMessage(engine.missing_tools_message(), 15000)
            return
        if engine.last_error != self.shown_latex_error:
            self.shown_latex_error = engine.last_error
            self.statusBar().showMessage("LaTeX error: " + engine.last_error +
                                         "  (the plain text is shown instead)", 15000)

    def on_object_placed(self, obj):
        self.project.objects.append(obj)
        self.changed()
        dialog = self.show_dialog("objects")
        dialog.select_object(len(self.project.objects) - 1)
        if obj.kind == "text":
            dialog.text.setFocus()
            dialog.text.selectAll()

    def on_region_defined(self, region_type, graph_index, points):
        self.show_dialog("regions").add_region(region_type, graph_index, points)

    def on_dialog_action(self):
        self.show_dialog(self.sender().data())

    def show_dialog(self, name):
        if name not in self.dialogs:
            self.dialogs[name] = create_dialog(name, self)
        dialog = self.dialogs[name]
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    # =================================================================== button column actions
    def redraw(self):
        self.canvas.set_mode("draw")
        self.canvas.update()

    def autoscale_xy(self):
        self.project.cg().autoscale("xy")
        self.changed()

    def autoscale_x(self):
        self.project.cg().autoscale("x")
        self.changed()

    def autoscale_y(self):
        self.project.cg().autoscale("y")
        self.changed()

    def autoscale_all(self):
        for g in self.project.graphs:
            g.autoscale()
        self.changed()

    def zoom_center(self, factor):
        g = self.project.cg()
        set_range_t(g.xaxis, 0.5 - 0.5 * factor, 0.5 + 0.5 * factor)
        set_range_t(g.yaxis, 0.5 - 0.5 * factor, 0.5 + 0.5 * factor)
        self.changed()

    def zoom_in(self):
        self.zoom_center(0.9)

    def zoom_out(self):
        self.zoom_center(1 / 0.9)

    def scroll(self, dx, dy):
        """Shift the view by a fraction of the axis range (0.05 = 5 %)."""
        g = self.project.cg()
        if dx != 0:
            set_range_t(g.xaxis, dx, 1 + dx)
        if dy != 0:
            set_range_t(g.yaxis, dy, 1 + dy)
        self.changed()

    def scroll_left(self):
        self.scroll(-0.05, 0)

    def scroll_right(self):
        self.scroll(0.05, 0)

    def scroll_down(self):
        self.scroll(0, -0.05)

    def scroll_up(self):
        self.scroll(0, 0.05)

    def autotick(self):
        g = self.project.cg()
        g.xaxis.auto_ticks = True
        g.yaxis.auto_ticks = True
        self.changed()

    def push_zoom(self):
        g = self.project.cg()
        g.zoom_stack.append((g.xaxis.min, g.xaxis.max, g.yaxis.min, g.yaxis.max))
        self.canvas.set_mode("zoom")
        self.statusBar().showMessage("World pushed (%d on stack). Drag to zoom." % len(g.zoom_stack))

    def pop_zoom(self):
        g = self.project.cg()
        if len(g.zoom_stack) == 0:
            self.statusBar().showMessage("World stack is empty", 3000)
            return
        ranges = g.zoom_stack.pop()
        g.xaxis.min = ranges[0]
        g.xaxis.max = ranges[1]
        g.yaxis.min = ranges[2]
        g.yaxis.max = ranges[3]
        self.changed()

    # =================================================================== files
    def confirm_discard(self):
        """Ask before throwing away unsaved changes. Returns True if it's OK to continue."""
        if not self.project.modified:
            return True
        answer = QMessageBox.question(self, "NeoGrace", "Discard unsaved changes?",
                                      QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard

    def file_new(self):
        if self.confirm_discard():
            self.set_project(Project())

    def file_open(self):
        if not self.confirm_discard():
            return
        path, selected_filter = QFileDialog.getOpenFileName(
            self, "Open project", "", "Projects (*.ngr *.agr);;NeoGrace (*.ngr);;Grace (*.agr);;All files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            if path.lower().endswith(".agr"):
                project = agr.read_agr(path)
                project.filename = path           # Save writes the .agr back
            else:
                project = Project.load(path)
        except Exception as error:
            QMessageBox.critical(self, "Open", "Could not open %s:\n%s" % (path, error))
            return False
        self.set_project(project)
        self.update_title()
        return True

    def file_save(self):
        filename = self.project.filename
        if not filename:
            return self.file_save_as()
        try:
            if filename.lower().endswith(".agr"):
                agr.write_agr(self.project, filename)
                self.project.modified = False
            else:
                self.project.save(filename)
        except OSError as error:
            QMessageBox.critical(self, "Save", str(error))
            return False
        self.update_title()
        self.statusBar().showMessage("Saved " + filename, 4000)
        return True

    def file_save_as(self):
        start = self.project.filename
        if not start:
            start = "untitled.ngr"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save project", start, "NeoGrace project (*.ngr);;Grace project (*.agr)")
        if not path:
            return False
        lower = path.lower()
        if not lower.endswith(".ngr") and not lower.endswith(".agr"):
            if "agr" in selected_filter:
                path = path + ".agr"
            else:
                path = path + ".ngr"
        self.project.filename = path
        return self.file_save()

    def file_export_agr(self):
        if self.project.filename:
            base = os.path.splitext(self.project.filename)[0]
        else:
            base = "untitled"
        path, selected_filter = QFileDialog.getSaveFileName(self, "Export Grace project", base + ".agr",
                                                            "Grace project (*.agr)")
        if not path:
            return
        if not path.lower().endswith(".agr"):
            path = path + ".agr"
        try:
            agr.write_agr(self.project, path)
        except OSError as error:
            QMessageBox.critical(self, "Export", str(error))
            return
        self.statusBar().showMessage("Wrote " + path, 4000)

    def file_revert(self):
        filename = self.project.filename
        if filename and os.path.isfile(filename) and self.confirm_discard():
            self.open_path(filename)

    def default_export_path(self, fmt):
        if self.project.filename:
            base = os.path.splitext(self.project.filename)[0]
        else:
            base = os.path.join(os.getcwd(), "untitled")
        return base + EXTENSIONS[fmt]

    def print_page(self):
        if self.print_settings["path"] == "":
            self.show_dialog("print")
        else:
            self.do_export()

    def do_export(self):
        settings = self.print_settings
        if settings["path"] == "":
            settings["path"] = self.default_export_path(settings["fmt"])
        try:
            export_project(self.project, settings["path"], settings["fmt"], settings["dpi"],
                           settings["transparent"])
        except Exception as error:
            QMessageBox.critical(self, "Print", str(error))
            return
        self.statusBar().showMessage("Wrote " + settings["path"], 5000)

    def load_data(self, path, mode="single", set_type="xy", columns=None, graph_index=None, autoscale=True):
        """Read a data file into a graph. Returns the number of sets created."""
        blocks = io_formats.read_ascii(path)
        new_sets = io_formats.blocks_to_sets(blocks, mode, set_type, columns)
        if graph_index is None:
            graph_index = self.project.current
        g = self.project.graphs[graph_index]
        for x, y, this_type, errors in new_sets:
            ds = g.add_set(x, y)
            ds.set_errors(this_type, errors)
            ds.comment = os.path.basename(path)
        if autoscale and len(new_sets) > 0:
            g.autoscale()
        self.changed()
        return len(new_sets)

    def export_ascii(self):
        visible = []
        for ds in self.project.cg().sets:
            if not ds.hidden:
                visible.append(ds)
        if len(visible) == 0:
            QMessageBox.information(self, "Export", "The current graph has no visible sets.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(self, "Write sets", "sets.dat",
                                                            "Data (*.dat *.txt);;All files (*)")
        if path:
            io_formats.write_ascii(path, visible)
            self.statusBar().showMessage("Wrote %d set(s) to %s" % (len(visible), path), 5000)

    # =================================================================== preferences and autosave
    def prefs_changed(self):
        """Store the preferences and restart the autosave timer."""
        for key in self.prefs:
            self.settings.setValue(key, self.prefs[key])
        self.autosave_timer.stop()
        if self.prefs["autosave"]:
            self.autosave_timer.start(int(self.prefs["autosave_minutes"]) * 60 * 1000)
            self.autosave_label.setText("Autosave every %d min" % self.prefs["autosave_minutes"])
        else:
            self.autosave_label.setText("Autosave off")
        engine = latex.engine()
        if engine.tool_folder != self.prefs["tex_folder"]:
            engine.tool_folder = self.prefs["tex_folder"]
            engine.find_tools()
            self.warned_no_latex = False
        levels = int(self.prefs["undo_levels"])
        while len(self.undo_stack) > levels:
            del self.undo_stack[0]
        self.update_undo_buttons()

    def autosave_path(self):
        filename = self.project.filename
        if self.prefs["autosave_mode"] == "overwrite" and filename:
            return filename
        if filename:
            return os.path.splitext(filename)[0] + ".autosave.ngr"
        os.makedirs(self.prefs["autosave_dir"], exist_ok=True)
        return os.path.join(self.prefs["autosave_dir"], "untitled.autosave.ngr")

    def autosave(self):
        if not self.project.modified:
            return
        path = self.autosave_path()
        try:
            if path.lower().endswith(".agr"):
                agr.write_agr(self.project, path)
            else:
                # Project.save() changes filename/modified, so put them back afterwards
                old_filename = self.project.filename
                old_modified = self.project.modified
                self.project.save(path)
                self.project.filename = old_filename
                self.project.modified = old_modified
            if path == self.project.filename:
                self.project.modified = False         # we really saved the file itself
                self.update_title()
        except OSError as error:
            self.statusBar().showMessage("Autosave failed: %s" % error, 6000)
            return
        self.autosave_label.setText("Autosaved " + QDateTime.currentDateTime().toString("HH:mm"))
        self.autosave_label.setToolTip(path)

    def open_autosave_folder(self):
        folder = os.path.dirname(self.autosave_path())
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # =================================================================== themes
    def set_theme(self, name):
        theme = THEMES[name]
        self.theme = theme
        apply_theme(QApplication.instance(), theme)
        for button in self.tool_buttons:
            button.setIcon(make_icon(button.property("iconName"), theme))
        self.canvas.theme = theme
        if name in self.theme_actions:
            self.theme_actions[name].setChecked(True)
        if hasattr(self, "settings"):
            self.settings.setValue("theme", name)
        self.canvas.update()
        self.statusBar().showMessage("Theme: " + name, 2000)

    def on_theme_action(self):
        self.set_theme(self.sender().data())

    def next_theme(self):
        names = list(THEMES)
        index = names.index(self.theme.name)
        self.set_theme(names[(index + 1) % len(names)])

    def set_match_page(self, checked):
        self.canvas.match_page = checked
        if hasattr(self, "settings"):
            self.settings.setValue("match_page", checked)
        self.canvas.update()
        if checked:
            self.statusBar().showMessage("Page preview follows the theme. Exports keep the real colours.", 5000)

    # =================================================================== misc
    def about(self):
        QMessageBox.about(self, "About NeoGrace",
                          "<b>NeoGrace " + __version__ + "</b><p>A modern take on xmgrace: same workflow, "
                          "anti-aliased rendering, transparency, PDF/SVG/PNG export.</p>"
                          "<p>Double-click sets, axes, titles or the legend to edit them. "
                          "Mouse wheel zooms (Shift: Y only, Ctrl: X only), middle-drag pans.</p>")

    def closeEvent(self, event):
        if not self.confirm_discard():
            event.ignore()
            return
        if not self.project.filename:
            # The untitled autosave isn't needed any more
            try:
                os.remove(self.autosave_path())
            except OSError:
                pass
        event.accept()
