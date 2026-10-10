"""
theme.py - colour schemes for the program's windows, menus and dialogs.

A theme is a small set of named colours. The Qt stylesheet (which works like
CSS for widgets) is a template with $names in it; build_stylesheet() replaces
each $name with the theme's colour.

The plot page itself keeps its real colours, unless "Match page to theme" is
on (that only changes the on-screen preview, never the exported files).
"""
import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QPalette


class Theme:
    def __init__(self, name, dark, colors):
        self.name = name
        self.dark = dark
        # The basic colours. Every theme defines all of these:
        self.bg = colors["bg"]                    # window background
        self.surface = colors["surface"]          # panels, menus, tab pages
        self.surface2 = colors["surface2"]        # buttons, table headers
        self.field = colors["field"]              # text boxes, lists
        self.border = colors["border"]
        self.border_strong = colors["border_strong"]
        self.text = colors["text"]
        self.muted = colors["muted"]              # secondary text
        self.disabled = colors["disabled"]
        self.accent = colors["accent"]            # highlight colour
        self.on_accent = colors["on_accent"]      # text drawn on top of the accent colour
        self.canvas = colors["canvas"]            # area around the page
        self.paper = colors["paper"]              # page colour for "Match page to theme"
        self.ink = colors["ink"]                  # text/line colour for "Match page to theme"

    def rgba(self, hex_color, alpha):
        """A CSS colour with transparency, e.g. "rgba(255, 0, 0, 0.5)"."""
        c = QColor(hex_color)
        return "rgba(%d, %d, %d, %s)" % (c.red(), c.green(), c.blue(), alpha)

    def hover_color(self):
        if self.dark:
            return self.rgba(self.text, 0.07)
        return self.rgba(self.text, 0.06)

    def pressed_color(self):
        if self.dark:
            return self.rgba(self.text, 0.13)
        return self.rgba(self.text, 0.11)

    def accent_soft(self):
        if self.dark:
            return self.rgba(self.accent, 0.20)
        return self.rgba(self.accent, 0.13)

    def accent_hover(self):
        if self.dark:
            return QColor(self.accent).lighter(112).name()
        return QColor(self.accent).darker(110).name()


# ---------------------------------------------------------------------------
# All themes, in menu order. To add a theme, copy one block and change the colours.
# ---------------------------------------------------------------------------
THEMES = {}          # name -> Theme


def add_theme(name, dark, bg, surface, surface2, field, border, border_strong, text, muted,
              disabled, accent, on_accent, canvas, paper, ink):
    colors = {"bg": bg, "surface": surface, "surface2": surface2, "field": field,
              "border": border, "border_strong": border_strong, "text": text, "muted": muted,
              "disabled": disabled, "accent": accent, "on_accent": on_accent,
              "canvas": canvas, "paper": paper, "ink": ink}
    THEMES[name] = Theme(name, dark, colors)


add_theme("Graphite", True,
          bg="#16171a", surface="#1d1f23", surface2="#26292e", field="#121316",
          border="#2b2e34", border_strong="#3d4148", text="#e8eaed", muted="#8f96a0", disabled="#555a62",
          accent="#6ea8fe", on_accent="#0a1426", canvas="#101113", paper="#1b1d21", ink="#d7dae0")
add_theme("Nord", True,
          bg="#2b303b", surface="#323844", surface2="#3b4252", field="#262a33",
          border="#3e4555", border_strong="#4c566a", text="#eceff4", muted="#a2abbc", disabled="#5f6b82",
          accent="#88c0d0", on_accent="#1b232b", canvas="#242830", paper="#2e3440", ink="#e5e9f0")
add_theme("Mocha", True,
          bg="#181825", surface="#1e1e2e", surface2="#2a2b3c", field="#14141f",
          border="#2e2f42", border_strong="#45475a", text="#cdd6f4", muted="#a6adc8", disabled="#6c7086",
          accent="#cba6f7", on_accent="#1e1e2e", canvas="#11111b", paper="#1e1e2e", ink="#cdd6f4")
add_theme("Abyss", True,
          bg="#0b111d", surface="#101827", surface2="#172135", field="#080d17",
          border="#1b263b", border_strong="#2a3852", text="#e1e8f4", muted="#8796b0", disabled="#46536b",
          accent="#3dd6c6", on_accent="#03201d", canvas="#060a12", paper="#0f1626", ink="#d6deeb")
add_theme("Ember", True,
          bg="#171412", surface="#1e1a17", surface2="#28231f", field="#120f0d",
          border="#302a25", border_strong="#463e37", text="#eee7e0", muted="#a99e93", disabled="#5f564e",
          accent="#f2b04a", on_accent="#241703", canvas="#100d0b", paper="#1c1815", ink="#e8e0d8")
add_theme("Dracula", True,
          bg="#1f2029", surface="#262834", surface2="#313342", field="#1a1b23",
          border="#363849", border_strong="#4a4d63", text="#f8f8f2", muted="#a9abc2", disabled="#5c5f78",
          accent="#bd93f9", on_accent="#1b1530", canvas="#16171e", paper="#22232c", ink="#f1f1ec")
add_theme("Gruvbox", True,
          bg="#1d2021", surface="#282828", surface2="#32302f", field="#181a1b",
          border="#3c3836", border_strong="#504945", text="#ebdbb2", muted="#a89984", disabled="#665c54",
          accent="#fabd2f", on_accent="#231b02", canvas="#151718", paper="#1d2021", ink="#ebdbb2")
add_theme("Tokyo Night", True,
          bg="#16161e", surface="#1a1b26", surface2="#24283b", field="#13131a",
          border="#292e42", border_strong="#3b4261", text="#c0caf5", muted="#9aa5ce", disabled="#565f89",
          accent="#7aa2f7", on_accent="#0d1426", canvas="#101016", paper="#1a1b26", ink="#c0caf5")
add_theme("Rosé Pine", True,
          bg="#191724", surface="#1f1d2e", surface2="#26233a", field="#16141f",
          border="#2a2740", border_strong="#403d52", text="#e0def4", muted="#a8a5c3", disabled="#6e6a86",
          accent="#ebbcba", on_accent="#2a1a1a", canvas="#13111c", paper="#1f1d2e", ink="#e0def4")
add_theme("Evergreen", True,
          bg="#121916", surface="#17201c", surface2="#1f2a25", field="#0f1512",
          border="#25312b", border_strong="#36463e", text="#e2ece6", muted="#93a89c", disabled="#506157",
          accent="#5fd39a", on_accent="#062016", canvas="#0c120f", paper="#16201b", ink="#dbe7e0")
add_theme("Monokai", True,
          bg="#1e1f1c", surface="#272822", surface2="#31322c", field="#1a1b18",
          border="#3a3b34", border_strong="#4e4f46", text="#f8f8f2", muted="#a6a68e", disabled="#5f6050",
          accent="#a6e22e", on_accent="#1a2402", canvas="#161714", paper="#272822", ink="#f8f8f2")
add_theme("OLED", True,
          bg="#000000", surface="#0a0a0a", surface2="#141414", field="#050505",
          border="#1c1c1c", border_strong="#2c2c2c", text="#f2f2f2", muted="#8c8c8c", disabled="#4a4a4a",
          accent="#ffffff", on_accent="#000000", canvas="#000000", paper="#0a0a0a", ink="#eeeeee")
add_theme("Crimson", True,
          bg="#170f12", surface="#1e1418", surface2="#281b20", field="#120b0e",
          border="#30222a", border_strong="#46323b", text="#f1e4e8", muted="#ad959d", disabled="#634c55",
          accent="#ff5c7a", on_accent="#2a0710", canvas="#100a0c", paper="#1c1316", ink="#eadde1")
add_theme("Paper", False,
          bg="#f3f4f6", surface="#ffffff", surface2="#f6f7f9", field="#ffffff",
          border="#e1e4e9", border_strong="#c9ced6", text="#1b1f27", muted="#5f6673", disabled="#a8adb6",
          accent="#2f6bed", on_accent="#ffffff", canvas="#e4e7ec", paper="#ffffff", ink="#111111")
add_theme("Latte", False,
          bg="#eff1f5", surface="#f8f9fb", surface2="#e6e9ef", field="#ffffff",
          border="#d3d7e0", border_strong="#bcc0cc", text="#4c4f69", muted="#6c6f85", disabled="#a5a8b8",
          accent="#8839ef", on_accent="#ffffff", canvas="#dce0e8", paper="#ffffff", ink="#4c4f69")
add_theme("Solarized", False,
          bg="#fbf4e2", surface="#fffaf0", surface2="#f1ead6", field="#fffdf7",
          border="#e6ddc4", border_strong="#d4c9a8", text="#26383f", muted="#61767d", disabled="#a9b2ae",
          accent="#268bd2", on_accent="#ffffff", canvas="#ece4cd", paper="#fdf6e3", ink="#073642")
add_theme("Gruvbox Light", False,
          bg="#f6efd9", surface="#fbf1c7", surface2="#ebdbb2", field="#fffaeb",
          border="#e2d3a8", border_strong="#d5c4a1", text="#3c3836", muted="#665c54", disabled="#a89984",
          accent="#b57614", on_accent="#ffffff", canvas="#ebe1c2", paper="#fbf1c7", ink="#282828")
add_theme("Dawn", False,
          bg="#faf4ed", surface="#fffaf3", surface2="#f2e9e1", field="#fffdf9",
          border="#e6dcd2", border_strong="#d7c9bc", text="#575279", muted="#797593", disabled="#b4aec4",
          accent="#d7827e", on_accent="#ffffff", canvas="#efe6dc", paper="#fffaf3", ink="#575279")
add_theme("Arctic", False,
          bg="#eef3f8", surface="#f8fbfe", surface2="#e3ebf4", field="#ffffff",
          border="#d3deea", border_strong="#b8c7d9", text="#15263a", muted="#56687e", disabled="#a3b1c2",
          accent="#0a84c6", on_accent="#ffffff", canvas="#dfe8f2", paper="#ffffff", ink="#0d1b2a")
add_theme("Lilac", False,
          bg="#f4f1f9", surface="#fcfbfe", surface2="#ebe5f4", field="#ffffff",
          border="#ddd5ea", border_strong="#c7bcdb", text="#2a2140", muted="#675c80", disabled="#aca3bf",
          accent="#7c4ddb", on_accent="#ffffff", canvas="#e7e0f2", paper="#ffffff", ink="#211a33")
add_theme("Mono", False,
          bg="#f2f2f2", surface="#fafafa", surface2="#e9e9e9", field="#ffffff",
          border="#dadada", border_strong="#c2c2c2", text="#111111", muted="#5c5c5c", disabled="#a6a6a6",
          accent="#111111", on_accent="#ffffff", canvas="#e3e3e3", paper="#ffffff", ink="#000000")
add_theme("Sage", False,
          bg="#f1f4f1", surface="#fbfcfb", surface2="#e8ede8", field="#ffffff",
          border="#d8e0d8", border_strong="#bfcabf", text="#1e2a22", muted="#5a6b5f", disabled="#a6b3a9",
          accent="#2f8f5b", on_accent="#ffffff", canvas="#e0e7e1", paper="#ffffff", ink="#17201a")

DARK_DEFAULT = "Graphite"
LIGHT_DEFAULT = "Paper"


def mono_family():
    """A monospace font for the coordinate display."""
    families = QFontDatabase.families()
    for name in ["JetBrains Mono", "SF Mono", "Cascadia Mono", "Menlo", "Consolas", "Fira Code",
                 "Source Code Pro", "Ubuntu Mono", "DejaVu Sans Mono"]:
        if name in families:
            return name
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


# ---------------------------------------------------------------------------
# Little arrow and check-mark images used by combo boxes, spin boxes and check boxes.
# The stylesheet can only use images from files, so we write them to a temp folder.
# ---------------------------------------------------------------------------
ASSET_FOLDER = tempfile.mkdtemp(prefix="neograce-theme-")

CHEVRON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
               '<path d="PATH" fill="none" stroke="COLOR" stroke-width="1.6" stroke-linecap="round" '
               'stroke-linejoin="round"/></svg>')


def write_svg(filename, path_data, color):
    full_path = os.path.join(ASSET_FOLDER, filename)
    svg = CHEVRON_SVG.replace("PATH", path_data).replace("COLOR", color)
    with open(full_path, "w") as fh:
        fh.write(svg)
    return full_path.replace("\\", "/")       # Qt wants forward slashes, also on Windows


def theme_file_key(theme):
    key = ""
    for ch in theme.name.lower():
        if ch.isalnum():
            key = key + ch
    return key


# ---------------------------------------------------------------------------
# The stylesheet template. Each $name is replaced in build_stylesheet().
# ---------------------------------------------------------------------------
STYLESHEET_TEMPLATE = """
QWidget { color: $text; }
QMainWindow, QDialog, QMessageBox { background: $bg; }
QLabel { background: transparent; }
QToolTip { background: $surface2; color: $text; border: 1px solid $border_strong;
           border-radius: 6px; padding: 5px 8px; }

QMenuBar { background: $bg; padding: 3px 6px; border: none; }
QMenuBar::item { background: transparent; padding: 5px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: $hover; }
QMenuBar::item:pressed { background: $pressed; }
QMenu { background: $surface; border: 1px solid $border; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 30px 6px 12px; border-radius: 6px; margin: 1px 0; }
QMenu::item:selected { background: $accent_soft; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $border; margin: 5px 6px; }
QMenu::indicator { width: 14px; height: 14px; left: 8px; }
QMenu::icon { left: 8px; }

#Locator { background: $surface; border: 1px solid $border; border-radius: 10px; }
#Coords { font-family: "$mono"; color: $text; padding: 0 2px; }
#CoordsLabel { color: $muted; }
#Chip { background: $surface2; color: $muted; border: 1px solid $border;
         border-radius: 10px; padding: 1px 9px; }
#ModeChip { background: $accent_soft; color: $accent; border-radius: 10px; padding: 1px 10px; }

#ToolPanel { background: $surface; border: 1px solid $border; border-radius: 12px; }
#ToolPanel QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px;
                          color: $muted; padding: 3px 2px; font-size: 12px; }
#ToolPanel QToolButton:hover { background: $hover; color: $text; }
#ToolPanel QToolButton:pressed { background: $pressed; }
#ToolPanel QToolButton:checked { background: $accent_soft; color: $accent;
                                  border: 1px solid $accent_border; }
#HeaderButton { background: transparent; border: none; border-radius: 6px; padding: 2px; }
#HeaderButton:hover { background: $hover; }
#HeaderButton:pressed { background: $pressed; }
#HeaderRule { background: $border; min-width: 1px; max-width: 1px; margin: 3px 4px; }
#PanelRule { background: $border; max-height: 1px; min-height: 1px; margin: 3px 6px; }

QStatusBar { background: $bg; color: $muted; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $muted; padding: 0 8px; }

QPushButton { background: $surface2; border: 1px solid $border; border-radius: 8px;
               padding: 6px 14px; min-height: 18px; }
QPushButton:hover { background: $hover; border-color: $border_strong; }
QPushButton:pressed { background: $pressed; }
QPushButton:disabled { color: $disabled; }
QPushButton[primary="true"] { background: $accent; color: $on_accent; border: 1px solid $accent;
                               font-weight: 600; }
QPushButton[primary="true"]:hover { background: $accent_hover; border-color: $accent_hover; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget, QTableWidget {
    background: $field; border: 1px solid $border; border-radius: 8px; padding: 4px 8px;
    selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: $border_strong; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
QListWidget:focus, QTableWidget:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: $disabled; }

QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url("$arrow_down"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; border-radius: 8px;
                               padding: 4px; outline: 0; selection-background-color: $accent_soft;
                               selection-color: $text; }

QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; background: transparent; border-top-right-radius: 8px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; background: transparent; border-bottom-right-radius: 8px; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $hover; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("$arrow_up"); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("$arrow_down"); width: 10px; height: 10px; }

QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid $border_strong;
                        background: $field; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }

QSlider { background: transparent; min-height: 18px; }
QSlider::groove:horizontal { height: 4px; background: $border_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $surface; border: 2px solid $accent; width: 10px; height: 10px;
                              margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: $accent; }

QTabWidget::pane { background: $surface; border: 1px solid $border; border-radius: 10px; top: -1px; }
QTabWidget::tab-bar { left: 10px; }
QTabBar::tab { background: transparent; color: $muted; padding: 7px 12px; margin-right: 2px;
                border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }

QGroupBox { background: transparent; border: 1px solid $border; border-radius: 10px;
             margin-top: 16px; padding: 12px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 4px;
                    color: $muted; font-weight: 600; }

QListWidget { padding: 4px; outline: 0; }
QListWidget::item { padding: 5px 6px; border-radius: 6px; }
QListWidget::item:hover { background: $hover; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QTableWidget { gridline-color: $border; padding: 0; }
QTableWidget::item:selected { background: $accent_soft; color: $text; }
QHeaderView::section { background: $surface2; color: $muted; border: none;
                        border-bottom: 1px solid $border; border-right: 1px solid $border; padding: 4px 8px; }
QTableCornerButton::section { background: $surface2; border: none; }
QPlainTextEdit { font-family: "$mono"; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 3px; min-width: 28px; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""


def build_stylesheet(theme):
    key = theme_file_key(theme)
    values = {
        "bg": theme.bg, "surface": theme.surface, "surface2": theme.surface2, "field": theme.field,
        "border": theme.border, "border_strong": theme.border_strong, "text": theme.text,
        "muted": theme.muted, "disabled": theme.disabled, "accent": theme.accent,
        "on_accent": theme.on_accent,
        "hover": theme.hover_color(), "pressed": theme.pressed_color(),
        "accent_soft": theme.accent_soft(), "accent_hover": theme.accent_hover(),
        "accent_border": theme.rgba(theme.accent, 0.45),
        "mono": mono_family(),
        "arrow_down": write_svg(key + "-down.svg", "M3 4.5 L6 7.5 L9 4.5", theme.muted),
        "arrow_up": write_svg(key + "-up.svg", "M3 7.5 L6 4.5 L9 7.5", theme.muted),
        "check": write_svg(key + "-check.svg", "M2.6 6.2 L5 8.5 L9.4 3.6", theme.on_accent),
    }
    # Replace longer names first, so "$border_strong" isn't hit by "$border"
    names = sorted(values, key=len, reverse=True)
    text = STYLESHEET_TEMPLATE
    for name in names:
        text = text.replace("$" + name, values[name])
    return text


def build_palette(theme):
    """Colours for widgets the stylesheet doesn't reach (colour and file dialogs)."""
    palette = QPalette()
    role = QPalette.ColorRole
    pairs = [(role.Window, theme.bg), (role.WindowText, theme.text), (role.Base, theme.field),
             (role.AlternateBase, theme.surface2), (role.Text, theme.text), (role.Button, theme.surface2),
             (role.ButtonText, theme.text), (role.Highlight, theme.accent),
             (role.HighlightedText, theme.on_accent), (role.ToolTipBase, theme.surface2),
             (role.ToolTipText, theme.text), (role.PlaceholderText, theme.muted),
             (role.Link, theme.accent), (role.Mid, theme.border), (role.Dark, theme.border_strong),
             (role.Light, theme.surface)]
    for color_role, color in pairs:
        palette.setColor(color_role, QColor(color))
    for color_role in (role.Text, role.WindowText, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, color_role, QColor(theme.disabled))
    return palette


def apply_theme(app, theme):
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_stylesheet(theme))


def system_prefers_dark(app):
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:           # older Qt versions
        return app.palette().window().color().lightness() < 128
