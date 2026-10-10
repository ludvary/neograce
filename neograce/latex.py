"""
latex.py - real LaTeX typesetting for labels, using a TeX installation.

Every string that should be typeset is put into its own TeX box. One LaTeX run
handles many strings at once: each box becomes one page whose size is exactly
the box (width x height+depth), and dvisvgm turns each page into an SVG with the
glyphs as vector outlines. That keeps PDF/SVG exports fully vector.

    string -> item_N.tex -> latex -> batch.dvi -> dvisvgm -> item-N.svg

The SVG is read by our own small reader (read_svg below) into QPainterPaths,
which are then simply filled. (Qt's own SVG renderer draws these glyphs too bold
in PDF files, so we don't use it.)

Results are cached on disk (key = hash of preamble + colour + text), so every
string is compiled only once, ever. Compiling happens in a background thread:
while a string is not ready yet, the renderer draws the plain text instead, and
the canvas repaints when the LaTeX version arrives. Exports wait for LaTeX.

Needs `latex` and `dvisvgm` (both part of TeX Live and MiKTeX).
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ElementTree

from PySide6.QtCore import QRectF, QStandardPaths, Qt
from PySide6.QtGui import QColor, QPainterPath, QTransform

# Strings are typeset at 10 pt. SVG units are PostScript points (bp): 10 pt = 9.9626 bp.
FONT_SIZE_BP = 10.0 * 72.0 / 72.27

# Folders where TeX is often installed but may not be on PATH
EXTRA_TEX_FOLDERS = ["/Library/TeX/texbin", "/usr/local/texlive/2025/bin/x86_64-linux",
                     "/usr/local/texlive/2024/bin/x86_64-linux", "/usr/local/texlive/2023/bin/x86_64-linux",
                     "/usr/local/texlive/2025/bin/universal-darwin", "/usr/local/texlive/2024/bin/universal-darwin",
                     "C:\\Program Files\\MiKTeX\\miktex\\bin\\x64", "C:\\texlive\\2025\\bin\\windows",
                     "C:\\texlive\\2024\\bin\\windows"]

BATCH_HEADER = r"""\documentclass[10pt]{article}
\usepackage{amsmath,amssymb}
\usepackage{xcolor}
%PREAMBLE%
\newsavebox{\ngbox}
\hoffset=-1in \voffset=-1in
\begin{document}
\def\ngitem#1#2{%
  \typeout{NGBEGIN:#1}%
  \sbox{\ngbox}{\strut\input{#2}\unskip}%
  \typeout{NGBOX:#1:\the\wd\ngbox:\the\ht\ngbox:\the\dp\ngbox}%
  \shipout\hbox{\special{papersize=\the\wd\ngbox,\the\dimexpr\ht\ngbox+\dp\ngbox\relax}\usebox{\ngbox}}%
}
"""


# ---------------------------------------------------------------------------
# Reading dvisvgm's SVG output
#
# dvisvgm writes: <defs> with one <path> per glyph, then <use x= y= href=#glyph>
# for every character, <rect> for rules (fraction bars, square root lines), and
# <g fill="#cc3333"> around coloured parts. That small subset is all we read.
# ---------------------------------------------------------------------------
PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_path_data(d):
    """An SVG path string ("M1 2L3 4C...Z") -> QPainterPath. Supports M L H V C S Q T Z."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)        # TeX glyph outlines use the non-zero rule
    tokens = PATH_TOKEN.findall(d)
    i = 0
    command = ""
    x = 0.0
    y = 0.0
    start_x = 0.0
    start_y = 0.0
    last_control_x = 0.0      # for the smooth curve commands S and T
    last_control_y = 0.0
    last_command = ""

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command in "Zz":
                path.closeSubpath()
                x = start_x
                y = start_y
                last_command = command
                continue
        relative = command.islower()
        kind = command.upper()
        base_x = 0.0
        base_y = 0.0
        if relative:
            base_x = x
            base_y = y

        if kind == "M":
            x = base_x + float(tokens[i])
            y = base_y + float(tokens[i + 1])
            i += 2
            path.moveTo(x, y)
            start_x = x
            start_y = y
            # further number pairs after M are line-tos
            if relative:
                command = "l"
            else:
                command = "L"
        elif kind == "L":
            x = base_x + float(tokens[i])
            y = base_y + float(tokens[i + 1])
            i += 2
            path.lineTo(x, y)
        elif kind == "H":
            x = base_x + float(tokens[i])
            i += 1
            path.lineTo(x, y)
        elif kind == "V":
            y = base_y + float(tokens[i])
            i += 1
            path.lineTo(x, y)
        elif kind == "C":
            x1 = base_x + float(tokens[i])
            y1 = base_y + float(tokens[i + 1])
            x2 = base_x + float(tokens[i + 2])
            y2 = base_y + float(tokens[i + 3])
            x = base_x + float(tokens[i + 4])
            y = base_y + float(tokens[i + 5])
            i += 6
            path.cubicTo(x1, y1, x2, y2, x, y)
            last_control_x = x2
            last_control_y = y2
        elif kind == "S":
            if last_command.upper() in ("C", "S"):
                x1 = 2 * x - last_control_x
                y1 = 2 * y - last_control_y
            else:
                x1 = x
                y1 = y
            x2 = base_x + float(tokens[i])
            y2 = base_y + float(tokens[i + 1])
            x = base_x + float(tokens[i + 2])
            y = base_y + float(tokens[i + 3])
            i += 4
            path.cubicTo(x1, y1, x2, y2, x, y)
            last_control_x = x2
            last_control_y = y2
        elif kind == "Q":
            x1 = base_x + float(tokens[i])
            y1 = base_y + float(tokens[i + 1])
            x = base_x + float(tokens[i + 2])
            y = base_y + float(tokens[i + 3])
            i += 4
            path.quadTo(x1, y1, x, y)
            last_control_x = x1
            last_control_y = y1
        elif kind == "T":
            if last_command.upper() in ("Q", "T"):
                x1 = 2 * x - last_control_x
                y1 = 2 * y - last_control_y
            else:
                x1 = x
                y1 = y
            x = base_x + float(tokens[i])
            y = base_y + float(tokens[i + 1])
            i += 2
            path.quadTo(x1, y1, x, y)
            last_control_x = x1
            last_control_y = y1
        else:
            i += 1                       # unknown: skip
        last_command = command
    return path


def parse_transform(text):
    """SVG transform attribute -> QTransform (matrix, translate, scale and rotate)."""
    result = QTransform()
    if not text:
        return result
    for match in re.finditer(r"(\w+)\s*\(([^)]*)\)", text):
        name = match.group(1)
        values = []
        for number in NUMBER.findall(match.group(2)):
            values.append(float(number))
        step = QTransform()
        if name == "matrix" and len(values) == 6:
            step = QTransform(values[0], values[1], values[2], values[3], values[4], values[5])
        elif name == "translate" and len(values) >= 1:
            dy = 0.0
            if len(values) > 1:
                dy = values[1]
            step = QTransform.fromTranslate(values[0], dy)
        elif name == "scale" and len(values) >= 1:
            sy = values[0]
            if len(values) > 1:
                sy = values[1]
            step = QTransform.fromScale(values[0], sy)
        elif name == "rotate" and len(values) >= 1:
            step = QTransform().rotate(values[0])
        # In SVG the rightmost transform is applied first
        result = step * result
    return result


def local_name(tag):
    """'{http://www.w3.org/2000/svg}path' -> 'path'"""
    if "}" in tag:
        return tag[tag.index("}") + 1:]
    return tag


class LatexResult:
    """One typeset string: filled shapes (one path per colour) and its size in bp."""

    def __init__(self, svg_path):
        self.shapes = []          # list of [QPainterPath, QColor]
        self.width = 0.0
        self.height = 0.0
        self.read(svg_path)

    def read(self, svg_path):
        root = ElementTree.parse(svg_path).getroot()
        box = []
        for number in NUMBER.findall(root.get("viewBox", "0 0 0 0")):
            box.append(float(number))
        if len(box) != 4:
            box = [0.0, 0.0, 0.0, 0.0]
        self.width = box[2]
        self.height = box[3]

        glyphs = {}               # glyph id -> QPainterPath
        for element in root.iter():
            if local_name(element.tag) == "path" and element.get("id"):
                glyphs[element.get("id")] = parse_path_data(element.get("d", ""))

        by_color = {}             # colour -> QPainterPath with all shapes of that colour
        shift = QTransform.fromTranslate(-box[0], -box[1])   # move the viewBox corner to (0, 0)
        for child in root:
            if local_name(child.tag) != "defs":
                self.collect(child, shift, "#000000", glyphs, by_color)
        for color in by_color:
            self.shapes.append([by_color[color], QColor(color)])

    def collect(self, element, parent_transform, parent_fill, glyphs, by_color):
        tag = local_name(element.tag)
        transform = parse_transform(element.get("transform")) * parent_transform
        fill = element.get("fill", parent_fill)
        if fill == "none":
            return

        shape = None
        if tag == "use":
            href = element.get("{http://www.w3.org/1999/xlink}href", element.get("href", ""))
            glyph = glyphs.get(href.lstrip("#"))
            if glyph is not None:
                x = float(element.get("x", "0"))
                y = float(element.get("y", "0"))
                shape = (QTransform.fromTranslate(x, y) * transform).map(glyph)
        elif tag == "rect":
            rect = QPainterPath()
            rect.addRect(QRectF(float(element.get("x", "0")), float(element.get("y", "0")),
                                float(element.get("width", "0")), float(element.get("height", "0"))))
            shape = transform.map(rect)
        elif tag == "path":
            shape = transform.map(parse_path_data(element.get("d", "")))
        elif tag == "g" or tag == "svg":
            for child in element:
                self.collect(child, transform, fill, glyphs, by_color)

        if shape is not None:
            if fill not in by_color:
                combined = QPainterPath()
                combined.setFillRule(Qt.FillRule.WindingFill)
                by_color[fill] = combined
            by_color[fill].addPath(shape)

    def draw(self, painter, w, h):
        """Draw into the rectangle (0, 0, w, h) of the painter's current coordinates."""
        if self.width <= 0 or self.height <= 0:
            return
        painter.save()
        painter.scale(w / self.width, h / self.height)
        painter.setPen(Qt.PenStyle.NoPen)
        for path, color in self.shapes:
            painter.setBrush(color)
            painter.drawPath(path)
        painter.restore()


class LatexEngine:
    def __init__(self):
        self.preamble = ""
        self.tool_folder = ""            # set from the preferences; "" = search PATH
        self.latex_command = None
        self.dvisvgm_command = None
        self.find_tools()

        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        if not location:
            location = os.path.join(os.path.expanduser("~"), ".cache", "neograce")
        self.cache_folder = os.path.join(location, "latex")
        os.makedirs(self.cache_folder, exist_ok=True)

        self.results = {}          # key -> LatexResult (loaded in the main thread)
        self.errors = {}           # key -> error message
        self.queue = []            # strings waiting to be compiled: list of (key, text, color)
        self.queued_keys = set()
        self.lock = threading.Lock()
        self.worker = None
        self.new_results = False   # set by the worker, read by the main thread (take_new_results)
        self.last_error = ""

    # ----------------------------------------------------------- tools
    def find_tools(self):
        self.latex_command = None
        self.dvisvgm_command = None
        folders = []
        if self.tool_folder:
            folders.append(self.tool_folder)
        for name in ("latex", "dvisvgm"):
            found = None
            for folder in folders:
                candidate = shutil.which(name, path=folder)
                if candidate:
                    found = candidate
                    break
            if found is None:
                found = shutil.which(name)
            if found is None:
                for folder in EXTRA_TEX_FOLDERS:
                    if os.path.isdir(folder):
                        candidate = shutil.which(name, path=folder)
                        if candidate:
                            found = candidate
                            break
            if name == "latex":
                self.latex_command = found
            else:
                self.dvisvgm_command = found

    def available(self):
        return self.latex_command is not None and self.dvisvgm_command is not None

    def missing_tools_message(self):
        missing = []
        if self.latex_command is None:
            missing.append("latex")
        if self.dvisvgm_command is None:
            missing.append("dvisvgm")
        return ("LaTeX labels need " + " and ".join(missing) + ". Install TeX Live or MiKTeX, "
                "or set the TeX folder in Edit → Preferences.")

    # ----------------------------------------------------------- lookups (main thread)
    def make_key(self, text, color):
        data = self.preamble + "\n" + color.upper() + "\n" + text
        return hashlib.sha1(data.encode("utf-8")).hexdigest()

    def lookup(self, text, color):
        """The typeset string, or None if it isn't ready (it gets queued) or failed."""
        if not self.available():
            return None
        key = self.make_key(text, color)
        if key in self.results:
            return self.results[key]
        if key in self.errors:
            return None

        svg_path = os.path.join(self.cache_folder, key + ".svg")
        error_path = os.path.join(self.cache_folder, key + ".err")
        if os.path.isfile(svg_path):
            try:
                result = LatexResult(svg_path)
            except (ElementTree.ParseError, ValueError, IndexError):
                result = None
            if result is not None:
                self.results[key] = result
                return result
        if os.path.isfile(error_path):
            with open(error_path) as fh:
                self.errors[key] = fh.read()
            return None

        self.add_to_queue(key, text, color)
        return None

    def error_for(self, text, color):
        key = self.make_key(text, color)
        if key in self.errors:
            return self.errors[key]
        return None

    def add_to_queue(self, key, text, color):
        with self.lock:
            if key in self.queued_keys:
                return
            self.queued_keys.add(key)
            self.queue.append((key, text, color))
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.worker_loop, daemon=True)
                self.worker.start()

    def take_new_results(self):
        """True once after the worker finished something (the canvas then repaints)."""
        with self.lock:
            flag = self.new_results
            self.new_results = False
        return flag

    def busy(self):
        with self.lock:
            return len(self.queue) > 0 or (self.worker is not None and self.worker.is_alive())

    def wait(self, timeout=120.0):
        """Block until everything queued is compiled (used before exporting)."""
        worker = self.worker
        if worker is not None:
            worker.join(timeout)

    def clear_cache(self):
        with self.lock:
            self.results = {}
            self.errors = {}
        for name in os.listdir(self.cache_folder):
            if name.endswith(".svg") or name.endswith(".err") or name.endswith(".json"):
                os.remove(os.path.join(self.cache_folder, name))

    def forget_errors(self):
        """Forget failed strings so they are tried again (e.g. after changing the preamble)."""
        self.errors = {}

    # ----------------------------------------------------------- background compiling
    def worker_loop(self):
        while True:
            with self.lock:
                batch = self.queue
                self.queue = []
                if len(batch) == 0:
                    return
            try:
                self.compile_batch(batch)
            except Exception as error:          # never let the thread die silently
                for key, text, color in batch:
                    self.write_error(key, "LaTeX failed: %s" % error)
            with self.lock:
                for key, text, color in batch:
                    self.queued_keys.discard(key)
                self.new_results = True

    def write_error(self, key, message):
        with open(os.path.join(self.cache_folder, key + ".err"), "w") as fh:
            fh.write(message)
        self.last_error = message

    def compile_batch(self, batch):
        """Typeset all strings in one LaTeX run. Writes key.svg (or key.err) into the cache."""
        folder = tempfile.mkdtemp(prefix="neograce-tex-")
        lines = [BATCH_HEADER.replace("%PREAMBLE%", self.preamble)]
        for i in range(len(batch)):
            key, text, color = batch[i]
            with open(os.path.join(folder, "item%d.tex" % i), "w", encoding="utf-8") as fh:
                fh.write("\\color[HTML]{" + color.lstrip("#").upper() + "}" + text)
            lines.append("\\ngitem{%d}{item%d}" % (i, i))
        lines.append("\\end{document}")
        with open(os.path.join(folder, "batch.tex"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

        run = subprocess.run([self.latex_command, "-interaction=nonstopmode", "-no-shell-escape", "batch.tex"],
                             cwd=folder, capture_output=True, text=True, timeout=120)
        log_path = os.path.join(folder, "batch.log")
        dvi_path = os.path.join(folder, "batch.dvi")
        log_text = ""
        if os.path.isfile(log_path):
            with open(log_path, errors="replace") as fh:
                log_text = fh.read()

        # Which items had errors? Errors are the lines starting with "!" after "NGBEGIN:i".
        errors = {}
        current = -1
        preamble_error = ""
        log_lines = log_text.splitlines()
        for k in range(len(log_lines)):
            line = log_lines[k]
            if line.startswith("NGBEGIN:"):
                current = int(line[len("NGBEGIN:"):])
            elif line.startswith("!"):
                message = line[1:].strip()
                if k + 1 < len(log_lines) and log_lines[k + 1].startswith("l."):
                    message = message + "  (" + log_lines[k + 1].strip() + ")"
                if current < 0:
                    preamble_error = message
                elif current not in errors:
                    errors[current] = message

        if preamble_error or not os.path.isfile(dvi_path):
            message = preamble_error
            if not message:
                message = "LaTeX produced no output. " + run.stdout[-300:]
            for key, text, color in batch:
                self.write_error(key, "LaTeX error (preamble?): " + message)
            shutil.rmtree(folder, ignore_errors=True)
            return

        subprocess.run([self.dvisvgm_command, "--no-fonts", "--bbox=papersize", "--page=1-",
                        "--output=item-%p.svg", "batch.dvi"],
                       cwd=folder, capture_output=True, text=True, timeout=120)

        # Page numbers in the file names may be zero-padded; read them back as numbers
        pages = {}
        for name in os.listdir(folder):
            if name.startswith("item-") and name.endswith(".svg"):
                number_text = name[len("item-"):-len(".svg")]
                if number_text.isdigit():
                    pages[int(number_text)] = os.path.join(folder, name)

        for i in range(len(batch)):
            key = batch[i][0]
            if i in errors:
                self.write_error(key, errors[i])
            elif (i + 1) in pages:
                shutil.move(pages[i + 1], os.path.join(self.cache_folder, key + ".svg"))
            else:
                self.write_error(key, "dvisvgm did not produce this label")
        shutil.rmtree(folder, ignore_errors=True)

    # ----------------------------------------------------------- self test
    def test(self):
        """Typeset one formula right now. Returns (ok, message)."""
        self.find_tools()
        if not self.available():
            return False, self.missing_tools_message()
        key = self.make_key("$\\int_0^1 x\\,dx$ test", "#000000")
        for ending in (".svg", ".err"):
            path = os.path.join(self.cache_folder, key + ending)
            if os.path.isfile(path):
                os.remove(path)
        self.compile_batch([(key, "$\\int_0^1 x\\,dx$ test", "#000000")])
        if os.path.isfile(os.path.join(self.cache_folder, key + ".svg")):
            return True, "LaTeX works.\nlatex: %s\ndvisvgm: %s" % (self.latex_command, self.dvisvgm_command)
        with open(os.path.join(self.cache_folder, key + ".err")) as fh:
            return False, fh.read()


# The one engine shared by the whole program (created on first use, after QApplication exists)
_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = LatexEngine()
    return _engine
