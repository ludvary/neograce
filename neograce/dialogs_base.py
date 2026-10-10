"""
dialogs_base.py - what all dialogs have in common.

Every dialog follows the same pattern (like Grace's dialogs):

    refresh()   copy values from the model into the widgets
    apply()     copy values from the widgets into the model, then call main.changed()
    Buttons:    Apply / Accept (apply and close) / Close

Dialogs are non-modal: you can keep them open while working in the main window.
When anything changes, the main window calls refresh() on every open dialog.

"main" is the MainWindow. Dialogs reach the data through main.project.
"""
from PySide6.QtCore import Qt
import numpy as np
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QListWidget, QMenu,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .model import REGION_TYPE_NAMES, REGION_TYPES, region_mask

# Buttons that are drawn in the accent colour (the "main" action of a dialog)
PRIMARY_BUTTONS = ["Accept", "OK", "Print to file", "Fit", "Create sets"]


class GraceDialog(QDialog):
    title = "Dialog"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(self.title)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(16, 14, 16, 14)
        self.vbox.setSpacing(10)

    def project(self):
        return self.main.project

    def add_buttons(self, names):
        """Add a centred row of buttons.

        Standard names call standard functions: Apply -> apply(), Accept/OK -> apply and close,
        Close/Cancel -> close(). Any other name calls a method named on_<name>,
        e.g. "Print to file" calls on_print_to_file().
        """
        row = QHBoxLayout()
        row.addStretch(1)
        for name in names:
            button = QPushButton(name)
            primary = name in PRIMARY_BUTTONS
            if name == "Apply" and "Accept" not in names:
                primary = True               # Apply is the main button if there's no Accept
            if primary:
                button.setProperty("primary", True)       # the stylesheet colours it
                if name != "Apply":
                    button.setDefault(True)               # Enter presses it

            if name == "Apply":
                button.clicked.connect(self.apply)
            elif name == "Accept" or name == "OK":
                button.clicked.connect(self.accept_and_close)
            elif name == "Close" or name == "Cancel":
                button.clicked.connect(self.close)
            else:
                method_name = "on_" + name.lower().replace(" ", "_")
                button.clicked.connect(getattr(self, method_name))
            row.addWidget(button)
        row.addStretch(1)
        self.vbox.addLayout(row)

    def accept_and_close(self):
        result = self.apply()
        if result is not False:              # apply() returns False when it found an error
            self.close()

    def refresh(self):
        pass

    def apply(self):
        pass

    def warn(self, message):
        """Show a warning box. Returns False so you can write: return self.warn("...")"""
        QMessageBox.warning(self, self.title, message)
        return False


def make_combo(labels):
    combo = QComboBox()
    combo.addItems(labels)
    return combo


def set_label(graph_index, set_index, ds):
    """How a set is shown in lists, e.g. "G0.S2 [257]  T = 400"."""
    text = "G%d.S%d [%d]" % (graph_index, set_index, len(ds))
    if ds.legend:
        text = text + "  " + ds.legend
    elif ds.comment:
        text = text + "  (" + ds.comment + ")"
    if ds.hidden:
        text = text + "  [hidden]"
    return text


class SetList(QListWidget):
    """A list of the sets in a graph, with a right-click menu (hide, kill, ...)."""

    def __init__(self, main, multiple=True):
        super().__init__()
        self.main = main
        if multiple:
            self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        else:
            self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMinimumHeight(100)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def populate(self, graph_index, graph):
        """Fill the list from a graph, keeping the selection if possible."""
        previously_selected = self.selected()
        self.blockSignals(True)
        self.clear()
        for si in range(len(graph.sets)):
            self.addItem(set_label(graph_index, si, graph.sets[si]))
        for si in previously_selected:
            if si < self.count():
                self.item(si).setSelected(True)
        if len(self.selectedItems()) == 0 and self.count() > 0:
            self.item(0).setSelected(True)
            self.setCurrentRow(0)
        self.blockSignals(False)

    def selected(self):
        """Sorted list of selected row numbers (= set indices)."""
        rows = []
        for item in self.selectedItems():
            rows.append(self.row(item))
        rows.sort()
        return rows

    def select(self, set_index):
        if set_index >= 0 and set_index < self.count():
            self.blockSignals(True)
            self.clearSelection()
            self.item(set_index).setSelected(True)
            self.setCurrentRow(set_index)
            self.blockSignals(False)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        operations = {}                          # QAction -> operation name
        operations[menu.addAction("Hide")] = "hide"
        operations[menu.addAction("Show")] = "show"
        menu.addSeparator()
        operations[menu.addAction("Duplicate")] = "duplicate"
        operations[menu.addAction("Kill")] = "kill"
        menu.addSeparator()
        operations[menu.addAction("Bring to front")] = "front"
        operations[menu.addAction("Send to back")] = "back"
        menu.addSeparator()
        select_all = menu.addAction("Select all")

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == select_all:
            self.selectAll()
        elif chosen in operations:
            set_operation(self.main, operations[chosen], self.selected())


def set_operation(main, operation, selected):
    """Hide/show/duplicate/kill/reorder the selected sets of the current graph."""
    g = main.project.cg()
    chosen = []
    others = []
    for si in range(len(g.sets)):
        if si in selected:
            chosen.append(g.sets[si])
        else:
            others.append(g.sets[si])
    if len(chosen) == 0:
        return

    if operation == "hide":
        for ds in chosen:
            ds.hidden = True
    elif operation == "show":
        for ds in chosen:
            ds.hidden = False
    elif operation == "duplicate":
        for ds in chosen:
            g.sets.append(ds.copy())
    elif operation == "kill":
        g.sets = others
    elif operation == "front":
        g.sets = others + chosen        # drawn last = on top
    elif operation == "back":
        g.sets = chosen + others
    main.changed()


class RegionChooser(QWidget):
    """"Restrict to region: [None / R0 / R1 ...]  [ ] Negate" - used by the data dialogs."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.negate = QCheckBox("Negate")
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.negate)

    def refresh(self, project):
        keep = self.combo.currentIndex()
        self.combo.clear()
        self.combo.addItem("None (all points)")
        for k in range(len(project.regions)):
            region = project.regions[k]
            name = REGION_TYPE_NAMES[REGION_TYPES.index(region.type)]
            self.combo.addItem("R%d  %s (G%d)" % (k, name, region.graph))
        if keep >= 0 and keep < self.combo.count():
            self.combo.setCurrentIndex(keep)

    def mask(self, project, x, y):
        """Boolean array of the points to use, or None when no region is chosen."""
        index = self.combo.currentIndex() - 1
        if index < 0 or index >= len(project.regions):
            return None
        inside = region_mask(project.regions[index], x, y)
        if self.negate.isChecked():
            return np.logical_not(inside)
        return inside
