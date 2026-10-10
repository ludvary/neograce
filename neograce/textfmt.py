"""
textfmt.py - drawing text with Grace's formatting codes.

Grace lets you put codes inside any string:
    \\S  start superscript         \\s  start subscript      \\N  back to normal
    \\x  greek letters (Symbol font)                       \\f{Times-Italic}  switch font
    \\f1 switch to Grace font number 1                     \\u ... \\U  underline
    \\o ... \\O  overline           \\+  \\-  bigger / smaller      \\\\  a backslash

We turn such a string into a small piece of HTML and let Qt's QTextDocument
lay it out. Each run of characters with the same formatting becomes one
<span style="...">, so there is never any nesting to get wrong.

LaTeX: depending on the project's text mode, strings are typeset by a real
LaTeX installation instead (see latex.py): "auto" uses LaTeX for strings that
contain $...$, "all" uses it for every string. While a string is still being
compiled (or if LaTeX is missing), the plain text is shown instead.
"""
import html
import math

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QFont, QFontDatabase, QTextDocument

from . import latex

# In the Symbol font, Latin letters show up as greek ones. This table does the same.
LATIN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
GREEK = "αβχδεφγηιϕκλμνοπθρστυϖωξψζΑΒΧΔΕΦΓΗΙϑΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖ"
SYMBOL_MAP = {}
for _i in range(len(LATIN)):
    SYMBOL_MAP[LATIN[_i]] = GREEK[_i]

# Grace's standard font table: the number used in "\f1" or "label font 4".
GRACE_FONTS = ["Times-Roman", "Times-Italic", "Times-Bold", "Times-BoldItalic",
               "Helvetica", "Helvetica-Oblique", "Helvetica-Bold", "Helvetica-BoldOblique",
               "Courier", "Courier-Oblique", "Courier-Bold", "Courier-BoldOblique",
               "Symbol", "ZapfDingbats"]

# For each PostScript family, installed fonts that look the same (first one found wins).
FONT_CANDIDATES = {
    "times": ["Times New Roman", "Times", "Nimbus Roman", "Nimbus Roman No9 L", "TeX Gyre Termes",
              "Liberation Serif", "Tinos", "DejaVu Serif", "serif"],
    "helvetica": ["Helvetica", "Arial", "Nimbus Sans", "Nimbus Sans L", "TeX Gyre Heros",
                  "Liberation Sans", "Arimo", "DejaVu Sans", "sans-serif"],
    "courier": ["Courier New", "Courier", "Nimbus Mono PS", "Nimbus Mono L", "Liberation Mono",
                "Cousine", "DejaVu Sans Mono", "monospace"],
    "palatino": ["Palatino", "Palatino Linotype", "P052", "TeX Gyre Pagella", "URW Palladio L", "serif"],
    "bookman": ["Bookman", "URW Bookman", "URW Bookman L", "TeX Gyre Bonum", "serif"],
    "avantgarde": ["Avant Garde", "URW Gothic", "URW Gothic L", "TeX Gyre Adventor", "sans-serif"],
    "newcenturyschlbk": ["New Century Schoolbook", "C059", "TeX Gyre Schola", "serif"],
}

# Newer URW font names used by modern Grace installs, mapped to the classic family.
FONT_ALIASES = {"nimbusroman": "times", "nimbussans": "helvetica", "nimbussansnarrow": "helvetica",
                "nimbusmonops": "courier", "p052": "palatino", "urwbookman": "bookman",
                "urwgothic": "avantgarde", "c059": "newcenturyschlbk", "d050000l": "times",
                "standardsymbolsps": "symbol", "z003": "times", "utopia": "times"}

_installed_families = {}     # lower-case name -> real name, filled on first use
_resolved_families = {}      # family key -> installed family name


def installed_families():
    if len(_installed_families) == 0:
        for family in QFontDatabase.families():
            _installed_families[family.lower()] = family
    return _installed_families


def parse_font(spec, default="Helvetica"):
    """Turn a font name like "Times-BoldItalic" into (installed family, bold, italic, is_symbol)."""
    if not spec:
        spec = default
    if not spec:
        spec = "Helvetica"
    spec = spec.strip()

    # "Times-BoldItalic" -> base "Times", style "BoldItalic"
    dash = spec.find("-")
    if dash >= 0:
        base = spec[:dash]
        style = spec[dash + 1:].lower()
    else:
        base = spec
        style = ""
    bold = ("bold" in style) or ("demi" in style)
    italic = ("italic" in style) or ("oblique" in style)

    key = base.lower().replace(" ", "")
    if key in FONT_ALIASES:
        key = FONT_ALIASES[key]
    if key == "symbol" or key == "zapfdingbats":
        return "Symbol", False, False, True

    if key not in _resolved_families:
        families = installed_families()
        if key in FONT_CANDIDATES:
            candidates = FONT_CANDIDATES[key]
        else:
            candidates = [spec, base]
        found = None
        for name in candidates:
            if name.lower() in families:
                found = families[name.lower()]
                break
        if found is None:
            found = base            # let Qt pick its own substitute
        _resolved_families[key] = found
    return _resolved_families[key], bold, italic, False


class TextState:
    """The formatting that is active while we walk through a string."""

    def __init__(self, family, bold, italic, greek):
        self.family = family
        self.bold = bold
        self.italic = italic
        self.greek = greek
        self.script = ""        # "", "super" or "sub"
        self.underline = False
        self.overline = False
        self.scale = 1.0

    def key(self):
        """A value that is equal for two identical states (used to merge characters into runs)."""
        return (self.family, self.bold, self.italic, self.greek, self.script,
                self.underline, self.overline, self.scale)

    def css(self, px):
        parts = ["font-family:'" + self.family + "'"]
        if self.bold:
            parts.append("font-weight:700")
        else:
            parts.append("font-weight:400")
        if self.italic:
            parts.append("font-style:italic")
        else:
            parts.append("font-style:normal")
        if self.scale != 1.0:
            parts.append("font-size:" + str(max(1, round(px * self.scale))) + "px")
        if self.script != "":
            parts.append("vertical-align:" + self.script)
        decorations = []
        if self.underline:
            decorations.append("underline")
        if self.overline:
            decorations.append("overline")
        if len(decorations) > 0:
            parts.append("text-decoration:" + " ".join(decorations))
        return ";".join(parts)


def switch_font(state, spec, default_font):
    family, bold, italic, is_symbol = parse_font(spec, default_font)
    if is_symbol:
        state.greek = True
    else:
        state.family = family
        state.bold = bold
        state.italic = italic
        state.greek = False


def grace_to_html(text, px, default_font):
    """Convert a string with Grace codes into HTML for QTextDocument."""
    family, bold, italic, is_symbol = parse_font(default_font)
    state = TextState(family, bold, italic, is_symbol)

    runs = []              # list of [state key, css string, list of characters]
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            code = text[i + 1]
            i += 2
            if code == "\\":
                add_char(runs, state, "\\", px)
            elif code == "S":
                state.script = "super"
            elif code == "s":
                state.script = "sub"
            elif code == "N":
                state.script = ""
            elif code == "x":
                state.greek = True
            elif code == "f":
                if i < n and text[i] == "{":
                    # \f{Name}
                    close = text.find("}", i)
                    if close < 0:
                        close = n
                    name = text[i + 1:close].strip()
                    i = close + 1
                    if name == "":
                        name = default_font
                    switch_font(state, name, default_font)
                elif i < n and text[i].isdigit():
                    # \f1, \f12 ...
                    start = i
                    while i < n and text[i].isdigit():
                        i += 1
                    number = int(text[start:i])
                    if number < len(GRACE_FONTS):
                        switch_font(state, GRACE_FONTS[number], default_font)
                    else:
                        switch_font(state, default_font, default_font)
                else:
                    switch_font(state, default_font, default_font)
            elif code == "u":
                state.underline = True
            elif code == "U":
                state.underline = False
            elif code == "o":
                state.overline = True
            elif code == "O":
                state.overline = False
            elif code == "+":
                state.scale = state.scale * 1.19
            elif code == "-":
                state.scale = state.scale / 1.19
            elif i < n and text[i] == "{":
                # Some other code with an argument, e.g. \v{0.5}: skip it
                close = text.find("}", i)
                if close < 0:
                    i = n
                else:
                    i = close + 1
            continue

        if state.greek and c in SYMBOL_MAP:
            c = SYMBOL_MAP[c]
        add_char(runs, state, c, px)
        i += 1

    pieces = []
    for run in runs:
        pieces.append('<span style="' + run[1] + '">' + html.escape("".join(run[2])) + "</span>")
    return "".join(pieces)


def add_char(runs, state, c, px):
    """Append c to the last run if the formatting is the same, else start a new run."""
    key = state.key()
    if len(runs) > 0 and runs[-1][0] == key:
        runs[-1][2].append(c)
    else:
        runs.append([key, state.css(px), [c]])


# ---------------------------------------------------------------------------
# Layout cache: building a QTextDocument is slow-ish, so keep the ones we made.
# ---------------------------------------------------------------------------
_documents = {}


def get_document(text, px, font, color):
    key = (text, round(px, 2), font, color)
    if key in _documents:
        return _documents[key]
    if len(_documents) > 4000:
        _documents.clear()

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setUndoRedoEnabled(False)
    family, bold, italic, is_symbol = parse_font(font)
    qfont = QFont(family)
    qfont.setPixelSize(max(1, int(round(px))))
    qfont.setBold(bold)
    qfont.setItalic(italic)
    doc.setDefaultFont(qfont)
    body = grace_to_html(text, px, font)
    doc.setHtml('<span style="white-space:pre; color:' + color + '">' + body + "</span>")
    _documents[key] = doc
    return doc


# ---------------------------------------------------------------------------
# Text mode: "grace", "auto" or "all" (set by the renderer from Project.text_mode)
# ---------------------------------------------------------------------------
_text_mode = ["auto"]       # a one-element list, so functions can change it without "global"


def set_text_mode(mode):
    _text_mode[0] = mode


def text_mode():
    return _text_mode[0]


def uses_latex(text):
    mode = _text_mode[0]
    if mode == "grace":
        return False
    if mode == "all":
        return True
    return text.count("$") >= 2          # "auto": only strings with $...$


def latex_result(text, color):
    """The LaTeX rendering of text, or None (not wanted, not ready yet, or failed)."""
    if not uses_latex(text):
        return None
    return latex.engine().lookup(text, color)


def placeholder(text):
    """What to show while LaTeX is still working: the text without the $ signs."""
    return text.replace("$", "")


def text_size(text, px, font="Helvetica", color="#000000"):
    """Width and height (QSizeF) the text will take when drawn."""
    if not text:
        return QSizeF(0, 0)
    result = latex_result(text, color)
    if result is not None:
        scale = px / latex.FONT_SIZE_BP
        return QSizeF(result.width * scale, result.height * scale)
    if uses_latex(text):
        text = placeholder(text)
    doc = get_document(text, px, font, "#000000")
    return QSizeF(doc.idealWidth(), doc.size().height())


def draw_text(painter, text, x, y, px, color="#000000", font="Helvetica",
              halign=0.5, valign=0.5, angle=0.0):
    """Draw text so that the point (halign, valign) of its box lands on (x, y).

    halign/valign: 0 = left/top, 0.5 = centre, 1 = right/bottom.
    angle: counter-clockwise rotation in degrees.
    Returns the bounding box (exact for 0 and +-90 degrees, approximate otherwise).
    """
    if not text:
        return QRectF(x, y, 0, 0)

    result = latex_result(text, color)
    doc = None
    if result is not None:
        scale = px / latex.FONT_SIZE_BP
        w = result.width * scale
        h = result.height * scale
    else:
        shown = text
        if uses_latex(text):
            shown = placeholder(text)
        doc = get_document(shown, px, font, color)
        w = doc.idealWidth()
        h = doc.size().height()

    painter.save()
    painter.translate(x, y)
    if angle != 0:
        painter.rotate(-angle)        # Qt rotates clockwise, we want counter-clockwise
    painter.translate(-halign * w, -valign * h)
    if result is not None:
        result.draw(painter, w, h)
    else:
        doc.drawContents(painter)
    painter.restore()

    if abs(abs(angle) - 90) < 1e-6:
        return QRectF(x - valign * h, y - (1 - halign) * w, h, w)
    return rotated_box(x, y, w, h, halign, valign, angle)


def rotated_box(x, y, w, h, halign, valign, angle):
    """Axis-aligned bounding box of a w x h text box rotated by angle around its anchor (x, y)."""
    radians = math.radians(-angle)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    xs = []
    ys = []
    for corner_x, corner_y in ((0, 0), (w, 0), (0, h), (w, h)):
        local_x = corner_x - halign * w
        local_y = corner_y - valign * h
        xs.append(x + local_x * cos_a - local_y * sin_a)
        ys.append(y + local_x * sin_a + local_y * cos_a)
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
