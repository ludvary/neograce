"""
dialogs.py - creates dialogs by name. The main window asks for e.g. "axis"
and gets an AxisDialog. Transformations are named "t_" + kind, e.g. "t_fft".
"""
from .dialogs_data import (TRANSFORMS, DataSetsDialog, EvaluateDialog, FormulaDialog, RegressionDialog,
                           SetOperationsDialog, TransformDialog)
from .dialogs_files import BlockDataDialog, ImportAsciiDialog, PreferencesDialog, PrintSetupDialog
from .dialogs_fit import NonlinearFitDialog
from .dialogs_objects import DrawingObjectsDialog, RegionsDialog
from .dialogs_plot import (ArrangeDialog, AxisDialog, GraphAppearanceDialog, PlotAppearanceDialog,
                           SetAppearanceDialog)

DIALOG_CLASSES = {
    "set": SetAppearanceDialog,
    "axis": AxisDialog,
    "graph": GraphAppearanceDialog,
    "plot": PlotAppearanceDialog,
    "arrange": ArrangeDialog,
    "datasets": DataSetsDialog,
    "setops": SetOperationsDialog,
    "formula": FormulaDialog,
    "evaluate": EvaluateDialog,
    "regression": RegressionDialog,
    "nlfit": NonlinearFitDialog,
    "import": ImportAsciiDialog,
    "block": BlockDataDialog,
    "print": PrintSetupDialog,
    "prefs": PreferencesDialog,
    "objects": DrawingObjectsDialog,
    "regions": RegionsDialog,
}


def create_dialog(name, main):
    if name.startswith("t_"):
        kind = name[2:]
        if kind in TRANSFORMS:
            return TransformDialog(main, kind)
    return DIALOG_CLASSES[name](main)
