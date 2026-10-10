"""
widgets.py - small reusable widgets used by the dialogs.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QComboBox, QDoubleSpinBox, QHBoxLayout, QLineEdit, QSlider, QWidget

from .model import GRACE_COLORS
from .textfmt import GRACE_FONTS


def color_swatch(hex_color, size=14):
    """A small square icon filled with the colour."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(hex_color))
    p = QPainter(pixmap)
    p.setPen(QColor("#555555"))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pixmap)


class ColorCombo(QComboBox):
    """Grace's colour list plus "Custom…" to pick any colour.

    Each item stores its colour ("#rrggbb") as item data. "Custom…" stores None.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        for name, hex_color in GRACE_COLORS:
            self.addItem(color_swatch(hex_color), name, hex_color)
        self.addItem("Custom…", None)
        self.last_index = 1                 # black
        self.setCurrentIndex(1)
        self.activated.connect(self.on_activated)

    def on_activated(self, index):
        if self.itemData(index) is not None:
            self.last_index = index
            return
        # "Custom…" was chosen: open the colour picker
        start = self.itemData(self.last_index)
        if start is None:
            start = "#000000"
        chosen = QColorDialog.getColor(QColor(start), self, "Pick colour")
        if chosen.isValid():
            self.setColor(chosen.name())
        else:
            self.setCurrentIndex(self.last_index)

    def color(self):
        value = self.itemData(self.currentIndex())
        if value is None:
            return "#000000"
        return value

    def setColor(self, hex_color):
        if not hex_color:
            hex_color = "#000000"
        hex_color = hex_color.lower()
        for i in range(self.count()):
            data = self.itemData(i)
            if data is not None and data.lower() == hex_color:
                self.setCurrentIndex(i)
                self.last_index = i
                return
        # Not in the list yet: insert it just before "Custom…"
        position = self.count() - 1
        self.insertItem(position, color_swatch(hex_color), hex_color, hex_color)
        self.setCurrentIndex(position)
        self.last_index = position


class SliderSpin(QWidget):
    """A slider with a number box next to it; both always show the same value."""
    valueChanged = Signal(float)

    def __init__(self, lo=0.0, hi=10.0, step=0.1, decimals=2, suffix="", parent=None):
        super().__init__(parent)
        self.steps_per_unit = 1.0 / step     # the slider only knows integers
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(round(lo * self.steps_per_unit)), int(round(hi * self.steps_per_unit)))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(84)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.slider.valueChanged.connect(self.on_slider_moved)
        self.spin.valueChanged.connect(self.on_spin_changed)

    def on_slider_moved(self, position):
        self.spin.setValue(position / self.steps_per_unit)

    def on_spin_changed(self, value):
        self.slider.blockSignals(True)       # don't bounce the change back to the spin box
        self.slider.setValue(int(round(value * self.steps_per_unit)))
        self.slider.blockSignals(False)
        self.valueChanged.emit(value)

    def value(self):
        return self.spin.value()

    def setValue(self, value):
        self.spin.setValue(float(value))


class OpacitySlider(SliderSpin):
    """Shows 0-100 %, but value()/setValue() use 0.0-1.0 like the model."""

    def __init__(self, parent=None):
        super().__init__(0, 100, 1, 0, " %", parent)

    def value(self):
        return self.spin.value() / 100.0

    def setValue(self, value):
        self.spin.setValue(float(value) * 100.0)


class FloatEdit(QLineEdit):
    """A text box for a number. value() raises ValueError if the text isn't a number."""

    def value(self):
        return float(self.text().strip())

    def setValue(self, value):
        self.setText("%.10g" % float(value))


class FontCombo(QComboBox):
    """Pick a font: "Default", Grace's standard fonts, or type any installed font name."""

    def __init__(self, allow_default=True, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.allow_default = allow_default
        if allow_default:
            self.addItem("Default")
        for name in GRACE_FONTS:
            if name != "Symbol" and name != "ZapfDingbats":
                self.addItem(name)
        self.setMinimumWidth(180)

    def font_spec(self):
        """The chosen font name, or "" for the project default."""
        text = self.currentText().strip()
        if self.allow_default and (text == "" or text == "Default"):
            return ""
        return text

    def set_font_spec(self, spec):
        if spec:
            self.setCurrentText(spec)
        elif self.allow_default:
            self.setCurrentText("Default")
        else:
            self.setCurrentText("Times-Roman")
