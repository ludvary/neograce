"""
canvas.py - the drawing area. Shows the page and handles the mouse.

This is a normal QWidget subclass, exactly like you would write it in C++:
paintEvent() draws, and the mouse*Event() functions react to the mouse.
It talks to the main window through Qt signals.

Mouse actions:
    left click            select a graph
    left drag on legend   move the legend
    double click          open the dialog for what you clicked (set, axis, title, legend)
    middle drag           pan
    wheel                 zoom around the cursor (Shift: only Y, Ctrl: only X)
    Zoom / ZX / ZY mode   drag a rectangle to zoom
    AutoO mode            click a set to autoscale on it
    place_* modes         click (text) or drag (line, arrow, box, ellipse) to create a drawing object
    region mode           click points of a region; double-click (or right-click) ends a polygon
    drag on an object     move it;  double-click an object to edit it
    Escape                cancel the current mode, or clear the selection

Fine placement: click an axis label, title, subtitle, legend or drawing object
to select it (dashed outline). Then drag it, or use the keyboard:
    arrow keys            move by 0.001 of the page   (Shift: 10x, Alt: 1/5)
    [  ]                  rotate by 1 degree          (Shift: 15 degrees, Alt: 0.1)
    Delete                delete a selected drawing object
"""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import latex
from .model import DrawObject
from .render import Renderer, set_range_t
from .theme import DARK_DEFAULT, THEMES

MODE_HINTS = {
    "draw": "",
    "zoom": "Zoom: drag a rectangle in a graph",
    "zoomx": "Zoom X: drag across the graph",
    "zoomy": "Zoom Y: drag across the graph",
    "autoo": "AutoO: click on a set to autoscale on it",
    "place_text": "Text: click where the text should go",
    "place_line": "Line: drag from start to end",
    "place_arrow": "Arrow: drag from the tail to the tip",
    "place_box": "Box: drag a rectangle",
    "place_ellipse": "Ellipse: drag its bounding rectangle",
    "region": "Region: click points; double-click or right-click to finish a polygon (Esc cancels)",
}

# Selectable labels: renderer name -> text shown in the status bar
LABEL_NAMES = {"xlabel": "X axis label", "ylabel": "Y axis label", "altxlabel": "Top axis label",
               "altylabel": "Right axis label", "title": "Title", "subtitle": "Subtitle", "legend": "Legend"}

# Placement modes that are done by dragging, and the object kind they create
DRAG_PLACEMENT = {"place_line": "line", "place_arrow": "line", "place_box": "box", "place_ellipse": "ellipse"}


class PlotCanvas(QWidget):
    # Signals (like Qt signals in C++). The main window connects to these.
    locatorChanged = Signal(str)            # mouse position text, e.g. "G0: X, Y = [1, 2]"
    projectEdited = Signal()                # the mouse changed the model (zoom, pan, legend drag)
    focusChanged = Signal(int)              # a different graph was clicked
    editRequest = Signal(str, int, int)     # double click: (what, graph index, set index)
    statusMessage = Signal(str)
    modeChanged = Signal(str)
    objectPlaced = Signal(object)           # a new DrawObject made with the mouse
    regionDefined = Signal(str, int, object)  # region type, graph index, list of [x, y] points

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.renderer = Renderer()
        self.mode = "draw"
        self.theme = THEMES[DARK_DEFAULT]
        self.match_page = False             # draw the page in theme colours (screen only)

        self.zoom_origin = None             # where the zoom drag started (QPointF) or None
        self.zoom_rect = None               # current zoom rectangle while dragging, or None
        self.zoom_graph = None              # which graph is being zoomed


        self.pan_graph = None               # graph being panned, or None
        self.pan_start = None
        self.pan_start_ranges = None        # (xmin, xmax, ymin, ymax) when the pan started

        self.backdrop_key = None            # cache for the dotted background
        self.backdrop = None

        self.new_object_coords = "view"     # "view" or "world" for objects placed with the mouse
        self.place_start = None             # drag start while placing a line/box/ellipse
        self.place_current = None

        self.region_type = "inside"         # region being defined with the mouse
        self.region_graph = None
        self.region_points = []             # pixel positions clicked so far (QPointF)
        self.region_world = []              # the same points in data coordinates
        self.mouse_pos = None

        # Selection for fine placement: None, or (kind, index) where kind is a LABEL_NAMES key
        # (index = graph number) or "object" (index = object number)
        self.selected = None
        self.label_drag_start = None        # mouse position where a label drag started
        self.label_drag_original = None     # the label's offsets when the drag started

        # Repaint when LaTeX results arrive from the background compiler
        self.latex_timer = QTimer(self)
        self.latex_timer.setInterval(150)
        self.latex_timer.timeout.connect(self.check_latex)
        self.latex_timer.start()

        self.drag_object = -1               # index of the drawing object being dragged, or -1
        self.drag_start = None
        self.drag_original = None           # (x1, y1, x2, y2) before the drag
        self.drag_corners = None            # the same corners in pixels

        self.setMouseTracking(True)         # get mouseMoveEvent even with no button pressed
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        return QSize(900, 700)

    # ----------------------------------------------------------- helpers
    def set_mode(self, mode):
        self.mode = mode
        if mode != "region":
            self.region_points = []
            self.region_world = []
            self.region_graph = None
        self.place_start = None
        self.update()
        if mode == "draw":
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.statusMessage.emit(MODE_HINTS.get(mode, ""))
        self.modeChanged.emit(mode)

    def check_latex(self):
        if latex.engine().take_new_results():
            self.update()

    def start_region(self, region_type):
        self.set_mode("region")
        self.region_type = region_type

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self.mode != "draw":
                self.set_mode("draw")
            elif self.selected is not None:
                self.select(None)
            return
        if self.selected is None:
            super().keyPressEvent(event)
            return

        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        fine = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        step = 0.001                         # view units (0.1 % of the short page side)
        degrees = 1.0
        if shift:
            step = 0.01
            degrees = 15.0
        elif fine:
            step = 0.0002
            degrees = 0.1

        if key == Qt.Key.Key_Left:
            self.nudge_selected(-step, 0.0)
        elif key == Qt.Key.Key_Right:
            self.nudge_selected(step, 0.0)
        elif key == Qt.Key.Key_Up:
            self.nudge_selected(0.0, step)
        elif key == Qt.Key.Key_Down:
            self.nudge_selected(0.0, -step)
        elif key == Qt.Key.Key_BracketLeft or key == Qt.Key.Key_BraceLeft:
            self.rotate_selected(degrees)        # counter-clockwise
        elif key == Qt.Key.Key_BracketRight or key == Qt.Key.Key_BraceRight:
            self.rotate_selected(-degrees)
        elif (key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace) and self.selected[0] == "object":
            del self.project.objects[self.selected[1]]
            self.selected = None
            self.projectEdited.emit()
        else:
            super().keyPressEvent(event)
            return

    # ----------------------------------------------------------- selection and fine placement
    def select(self, selection):
        self.selected = selection
        self.show_placement()
        self.update()

    def selected_rect(self):
        """Where the selected thing is drawn (pixels), or None."""
        if self.selected is None:
            return None
        kind = self.selected[0]
        index = self.selected[1]
        if kind == "object":
            rects = self.renderer.object_rects
            if index < len(rects):
                return rects[index]
            return None
        lay = self.layout_of(index)
        if lay is None:
            return None
        if kind == "legend":
            return lay.legend_rect
        if kind in lay.label_rects:
            return lay.label_rects[kind]
        return None

    def selected_axis(self, kind, g):
        if kind == "xlabel":
            return g.xaxis
        if kind == "ylabel":
            return g.yaxis
        if kind == "altxlabel":
            return g.alt_xaxis
        return g.alt_yaxis

    def get_offsets(self, kind, index):
        """(dx, dy) of a label in view units (for the legend: its x, y frame fractions)."""
        if kind == "object":
            obj = self.project.objects[index]
            return (obj.x1, obj.y1, obj.x2, obj.y2)
        g = self.project.graphs[index]
        if kind == "legend":
            return (g.legend.x, g.legend.y)
        if kind == "title":
            return (g.title_dx, g.title_dy)
        if kind == "subtitle":
            return (g.subtitle_dx, g.subtitle_dy)
        axis = self.selected_axis(kind, g)
        return (axis.label_dx, axis.label_dy)

    def set_offsets_moved(self, kind, index, original, dx, dy):
        """Set a label's offsets to `original` moved by (dx, dy) view units."""
        if kind == "object":
            obj = self.project.objects[index]
            if obj.coords == "world":
                # Move in pixels, then convert back to data coordinates
                gmap = self.renderer.graph_map(obj.graph)
                if gmap is None:
                    return
                scale = self.renderer.view_scale
                saved = (obj.x1, obj.y1, obj.x2, obj.y2)
                obj.x1, obj.y1, obj.x2, obj.y2 = original
                corners = self.renderer.object_corners_px(obj)
                if corners is None:
                    obj.x1, obj.y1, obj.x2, obj.y2 = saved
                    return
                obj.x1, obj.y1 = gmap.to_world(corners[0] + dx * scale, corners[1] - dy * scale)
                obj.x2, obj.y2 = gmap.to_world(corners[2] + dx * scale, corners[3] - dy * scale)
            else:
                obj.x1 = original[0] + dx
                obj.y1 = original[1] + dy
                obj.x2 = original[2] + dx
                obj.y2 = original[3] + dy
            return
        g = self.project.graphs[index]
        if kind == "legend":
            # The legend position is a fraction of the frame, so convert from view units
            frame_w = g.viewport[2] - g.viewport[0]
            frame_h = g.viewport[3] - g.viewport[1]
            g.legend.x = original[0] + dx / frame_w
            g.legend.y = original[1] + dy / frame_h
        elif kind == "title":
            g.title_dx = original[0] + dx
            g.title_dy = original[1] + dy
        elif kind == "subtitle":
            g.subtitle_dx = original[0] + dx
            g.subtitle_dy = original[1] + dy
        else:
            axis = self.selected_axis(kind, g)
            axis.label_dx = original[0] + dx
            axis.label_dy = original[1] + dy

    def nudge_selected(self, dx, dy):
        kind = self.selected[0]
        index = self.selected[1]
        self.set_offsets_moved(kind, index, self.get_offsets(kind, index), dx, dy)
        self.projectEdited.emit()
        self.show_placement()

    def rotate_selected(self, degrees):
        kind = self.selected[0]
        index = self.selected[1]
        if kind == "legend":
            return
        if kind == "object":
            obj = self.project.objects[index]
            if obj.kind != "text":
                return
            obj.angle = normalize_angle(obj.angle + degrees)
        else:
            g = self.project.graphs[index]
            if kind == "title":
                g.title_angle = normalize_angle(g.title_angle + degrees)
            elif kind == "subtitle":
                g.subtitle_angle = normalize_angle(g.subtitle_angle + degrees)
            else:
                axis = self.selected_axis(kind, g)
                if axis.label_angle_auto:
                    # Start from the automatic angle: 0 for x labels, 90 for y labels
                    axis.label_angle_auto = False
                    if kind == "xlabel" or kind == "altxlabel":
                        axis.label_angle = 0.0
                    else:
                        axis.label_angle = 90.0
                axis.label_angle = normalize_angle(axis.label_angle + degrees)
        self.projectEdited.emit()
        self.show_placement()

    def show_placement(self):
        """Status bar text with the exact position and angle of the selection."""
        if self.selected is None:
            self.statusMessage.emit("")
            return
        kind = self.selected[0]
        index = self.selected[1]
        keys = "   arrows: move (Shift ×10, Alt ÷5) · [ ]: rotate · Esc: deselect"
        if kind == "object":
            obj = self.project.objects[index]
            text = "Object O%d (%s): x = %.4f, y = %.4f" % (index, obj.kind, obj.x1, obj.y1)
            if obj.kind == "text":
                text = text + ", angle %.1f°" % obj.angle
            self.statusMessage.emit(text + keys)
            return
        g = self.project.graphs[index]
        name = LABEL_NAMES[kind] + " (G%d)" % index
        if kind == "legend":
            self.statusMessage.emit(name + ": x = %.4f, y = %.4f of the frame" % (g.legend.x, g.legend.y) + keys)
            return
        if kind == "title":
            values = (g.title_dx, g.title_dy, g.title_angle)
        elif kind == "subtitle":
            values = (g.subtitle_dx, g.subtitle_dy, g.subtitle_angle)
        else:
            axis = self.selected_axis(kind, g)
            angle = axis.label_angle
            if axis.label_angle_auto:
                angle = 0.0
                if kind == "ylabel" or kind == "altylabel":
                    angle = 90.0
            values = (axis.label_dx, axis.label_dy, angle)
        self.statusMessage.emit(name + ": offset %+.4f, %+.4f, angle %.1f°" % values + keys)

    def axis_near(self, pos):
        """(axis name, graph index) when pos is on or right next to a frame edge, else None.

        Like xmgrace: double-clicking an axis anywhere along it opens its dialog.
        The top and right edges belong to the alternate axes when those are switched on.
        """
        near = 10.0
        layouts = self.renderer.layout
        for i in range(len(layouts) - 1, -1, -1):
            lay = layouts[i]
            if lay is None:
                continue
            frame = lay.frame
            g = self.project.graphs[lay.index]
            along_x = pos.x() >= frame.left() - near and pos.x() <= frame.right() + near
            along_y = pos.y() >= frame.top() - near and pos.y() <= frame.bottom() + near
            if along_x and abs(pos.y() - frame.bottom()) <= near:
                return ("xaxis", lay.index)
            if along_x and abs(pos.y() - frame.top()) <= near:
                if g.alt_xaxis.enabled:
                    return ("altxaxis", lay.index)
                return ("xaxis", lay.index)
            if along_y and abs(pos.x() - frame.left()) <= near:
                return ("yaxis", lay.index)
            if along_y and abs(pos.x() - frame.right()) <= near:
                if g.alt_yaxis.enabled:
                    return ("altyaxis", lay.index)
                return ("yaxis", lay.index)
        return None

    def label_at(self, pos):
        """(kind, graph index) of the label or legend under pos, or None."""
        layouts = self.renderer.layout
        for i in range(len(layouts) - 1, -1, -1):
            lay = layouts[i]
            if lay is None:
                continue
            if lay.legend_rect is not None and lay.legend_rect.contains(pos):
                return ("legend", lay.index)
            for kind in lay.label_rects:
                if lay.label_rects[kind].adjusted(-2, -2, 2, 2).contains(pos):
                    return (kind, lay.index)
        return None

    def page_rect(self):
        """The page rectangle: as large as possible, keeping the page's aspect ratio."""
        margin = 28
        available_w = max(1, self.width() - 2 * margin)
        available_h = max(1, self.height() - 2 * margin)
        aspect = self.project.page_w / self.project.page_h
        if available_w / available_h > aspect:
            h = available_h
            w = h * aspect
        else:
            w = available_w
            h = w / aspect
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def layout_of(self, graph_index):
        """The renderer's layout info (frame, coordinate map) for a graph, or None."""
        layouts = self.renderer.layout
        if graph_index is None or graph_index < 0 or graph_index >= len(layouts):
            return None
        return layouts[graph_index]

    def graph_at(self, pos):
        """Index of the graph whose frame contains pos, or None. Top-most graph wins."""
        layouts = self.renderer.layout
        for i in range(len(layouts) - 1, -1, -1):
            lay = layouts[i]
            if lay is not None and lay.frame.contains(pos):
                return lay.index
        return None

    def nearest_set(self, graph_index, pos, max_distance=10.0):
        """Index of the set with a point closest to pos (within max_distance pixels), or None."""
        lay = self.layout_of(graph_index)
        if lay is None:
            return None
        g = self.project.graphs[graph_index]
        best_set = None
        best_distance2 = max_distance * max_distance
        for si in range(len(g.sets)):
            ds = g.sets[si]
            n = len(ds)
            if ds.hidden or n == 0:
                continue
            px = lay.map.x(ds.x[:n])
            py = lay.map.y(ds.y[:n])
            with np.errstate(invalid="ignore"):
                distance2 = (px - pos.x()) ** 2 + (py - pos.y()) ** 2
            if np.all(np.isnan(distance2)):
                continue
            smallest = float(np.nanmin(distance2))
            if smallest < best_distance2:
                best_set = si
                best_distance2 = smallest
        return best_set

    def set_focus_graph(self, graph_index):
        if graph_index != self.project.current:
            self.project.current = graph_index
            self.focusChanged.emit(graph_index)
            self.update()

    # ----------------------------------------------------------- painting
    def paintEvent(self, event):
        theme = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self.get_backdrop())
        p.setPen(Qt.PenStyle.NoPen)
        page = self.page_rect()

        # Soft shadow: a few transparent rounded rectangles, each a bit smaller
        shadow_alphas = [0.012, 0.018, 0.025, 0.035, 0.05, 0.07]
        for i in range(len(shadow_alphas)):
            spread = 12 - 2 * i
            shadow = QColor(0, 0, 0)
            if theme.dark:
                shadow.setAlphaF(shadow_alphas[i] * 3.0)
            else:
                shadow.setAlphaF(shadow_alphas[i])
            p.setBrush(shadow)
            p.drawRoundedRect(page.adjusted(-spread, -spread + 3, spread, spread + 5), 4 + spread, 4 + spread)

        # The page itself, with slightly rounded corners
        clip = QPainterPath()
        clip.addRoundedRect(page, 4, 4)
        p.save()
        p.setClipPath(clip)
        if self.match_page:
            self.renderer.paint(p, self.project, page, screen=True,
                                paper=theme.paper, ink=theme.ink, accent=theme.accent)
        else:
            self.renderer.paint(p, self.project, page, screen=True, accent=theme.accent)
        p.restore()

        if theme.dark:
            p.setPen(QPen(QColor(255, 255, 255, 22), 1))     # faint edge so the page stands out
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(page.adjusted(-0.5, -0.5, 0.5, 0.5), 4, 4)

        self.draw_previews(p)

        rect = self.selected_rect()
        if rect is not None:
            p.setPen(QPen(QColor(self.theme.accent), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-4, -3, 4, 3), 3, 3)

        if self.zoom_rect is not None:
            fill = QColor(theme.accent)
            fill.setAlphaF(0.14)
            p.setPen(QPen(QColor(theme.accent), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(fill)
            p.drawRoundedRect(self.zoom_rect, 2, 2)
        p.end()

    def draw_previews(self, p):
        """Dashed outlines while placing an object or defining a region."""
        pen = QPen(QColor(self.theme.accent), 1.4, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.place_start is not None and self.place_current is not None:
            if self.mode == "place_line" or self.mode == "place_arrow":
                p.drawLine(self.place_start, self.place_current)
            elif self.mode == "place_ellipse":
                p.drawEllipse(QRectF(self.place_start, self.place_current).normalized())
            else:
                p.drawRect(QRectF(self.place_start, self.place_current).normalized())
        if self.mode == "region" and len(self.region_points) > 0:
            for k in range(1, len(self.region_points)):
                p.drawLine(self.region_points[k - 1], self.region_points[k])
            if self.mouse_pos is not None:
                p.drawLine(self.region_points[-1], self.mouse_pos)
            p.setBrush(QColor(self.theme.accent))
            for point in self.region_points:
                p.drawEllipse(point, 3, 3)

    def get_backdrop(self):
        """The background around the page (colour plus faint dot grid), cached."""
        ratio = self.devicePixelRatioF()
        key = (self.width(), self.height(), self.theme.name, ratio)
        if self.backdrop_key == key:
            return self.backdrop

        pixmap = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(self.theme.canvas))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dot = QColor(self.theme.text)
        if self.theme.dark:
            dot.setAlphaF(0.07)
        else:
            dot.setAlphaF(0.10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        spacing = 22
        for x in range(spacing // 2, self.width(), spacing):
            for y in range(spacing // 2, self.height(), spacing):
                p.drawEllipse(QPointF(x, y), 0.9, 0.9)
        p.end()
        self.backdrop_key = key
        self.backdrop = pixmap
        return pixmap

    # ----------------------------------------------------------- mouse
    def zoom_rect_for(self, pos):
        """The zoom rectangle from the drag start to pos (full height for ZX, full width for ZY)."""
        rect = QRectF(self.zoom_origin, pos).normalized()
        lay = self.layout_of(self.zoom_graph)
        if lay is not None:
            frame = lay.frame
            if self.mode == "zoomx":
                rect = QRectF(rect.left(), frame.top(), rect.width(), frame.height())
            elif self.mode == "zoomy":
                rect = QRectF(frame.left(), rect.top(), frame.width(), rect.height())
        return rect

    def mouseMoveEvent(self, event):
        pos = event.position()
        self.mouse_pos = pos

        if self.place_start is not None:
            self.place_current = pos
            self.update()
        elif self.mode == "region" and len(self.region_points) > 0:
            self.update()
        elif self.drag_object >= 0:
            self.move_dragged_object(pos)
            self.show_placement()
            self.update()
        elif self.label_drag_start is not None:
            scale = self.renderer.view_scale
            dx = (pos.x() - self.label_drag_start.x()) / scale
            dy = -(pos.y() - self.label_drag_start.y()) / scale
            self.set_offsets_moved(self.selected[0], self.selected[1], self.label_drag_original, dx, dy)
            self.show_placement()
            self.update()
        elif self.pan_graph is not None:
            lay = self.layout_of(self.pan_graph)
            if lay is not None:
                g = self.project.graphs[self.pan_graph]
                frame = lay.frame
                dx = (pos.x() - self.pan_start.x()) / frame.width()
                dy = -(pos.y() - self.pan_start.y()) / frame.height()
                # Start from the ranges at the beginning of the pan, then shift
                g.xaxis.min = self.pan_start_ranges[0]
                g.xaxis.max = self.pan_start_ranges[1]
                g.yaxis.min = self.pan_start_ranges[2]
                g.yaxis.max = self.pan_start_ranges[3]
                set_range_t(g.xaxis, -dx, 1 - dx)
                set_range_t(g.yaxis, -dy, 1 - dy)
                self.update()

        if self.zoom_origin is not None:
            self.zoom_rect = self.zoom_rect_for(pos)
            self.update()

        # Coordinate read-out
        graph_index = self.graph_at(pos)
        if graph_index is None:
            graph_index = self.project.current
        lay = self.layout_of(graph_index)
        if lay is not None:
            wx, wy = lay.map.to_world(pos.x(), pos.y())
            self.locatorChanged.emit("G%d: X, Y = [%.6g, %.6g]" % (graph_index, wx, wy))

    def mousePressEvent(self, event):
        pos = event.position()
        graph_index = self.graph_at(pos)

        if self.mode == "region":
            if event.button() == Qt.MouseButton.RightButton:
                self.finish_region()
            elif event.button() == Qt.MouseButton.LeftButton:
                self.add_region_point(pos)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self.mode == "place_text":
                self.objectPlaced.emit(self.make_object("text", pos, pos))
                self.set_mode("draw")
                return
            if self.mode in DRAG_PLACEMENT:
                self.place_start = pos
                self.place_current = pos
                return
            if self.mode == "zoom" or self.mode == "zoomx" or self.mode == "zoomy":
                if graph_index is not None:
                    self.zoom_graph = graph_index
                else:
                    self.zoom_graph = self.project.current
                self.zoom_origin = pos
                self.zoom_rect = QRectF(pos, pos)
                return

            if self.mode == "autoo":
                if graph_index is None:
                    graph_index = self.project.current
                si = self.nearest_set(graph_index, pos, 25)
                if si is not None:
                    g = self.project.graphs[graph_index]
                    g.autoscale("xy", [g.sets[si]])
                    self.projectEdited.emit()
                else:
                    self.statusMessage.emit("No set found near the click")
                self.set_mode("draw")
                return

            self.setFocus()                       # so the arrow keys come to us

            # Did we grab a drawing object? (they are on top, so check them first)
            index = self.object_at(pos)
            if index >= 0:
                self.select(("object", index))
                self.start_object_drag(index, pos)
                return

            # A label, title or legend?
            hit = self.label_at(pos)
            if hit is not None:
                self.select(hit)
                self.label_drag_start = pos
                self.label_drag_original = self.get_offsets(hit[0], hit[1])
                self.set_focus_graph(hit[1])
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return

            self.select(None)
            if graph_index is not None:
                self.set_focus_graph(graph_index)

        elif event.button() == Qt.MouseButton.MiddleButton and graph_index is not None:
            g = self.project.graphs[graph_index]
            self.pan_graph = graph_index
            self.pan_start = pos
            self.pan_start_ranges = (g.xaxis.min, g.xaxis.max, g.yaxis.min, g.yaxis.max)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        if self.place_start is not None:
            start = self.place_start
            end = event.position()
            mode = self.mode
            self.set_mode("draw")
            if abs(end.x() - start.x()) + abs(end.y() - start.y()) > 4:
                obj = self.make_object(DRAG_PLACEMENT[mode], start, end)
                if mode == "place_arrow":
                    obj.arrow = 2                    # arrow head at the end point
                self.objectPlaced.emit(obj)
            return
        if self.drag_object >= 0:
            self.drag_object = -1
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.projectEdited.emit()
            return
        if self.label_drag_start is not None:
            moved = self.label_drag_start != event.position()
            self.label_drag_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if moved:
                self.projectEdited.emit()
            return
        if self.zoom_origin is not None:
            rect = self.zoom_rect
            self.zoom_rect = None
            self.zoom_origin = None
            self.update()
            lay = self.layout_of(self.zoom_graph)
            if lay is not None and rect is not None and rect.width() > 3 and rect.height() > 3:
                g = self.project.graphs[lay.index]
                frame = lay.frame
                # Rectangle edges as fractions of the frame (y measured from the bottom)
                tx0 = (rect.left() - frame.left()) / frame.width()
                tx1 = (rect.right() - frame.left()) / frame.width()
                ty0 = (frame.bottom() - rect.bottom()) / frame.height()
                ty1 = (frame.bottom() - rect.top()) / frame.height()
                if self.mode == "zoom" or self.mode == "zoomx":
                    set_range_t(g.xaxis, tx0, tx1)
                if self.mode == "zoom" or self.mode == "zoomy":
                    set_range_t(g.yaxis, ty0, ty1)
                self.projectEdited.emit()
            self.set_mode("draw")              # zooming is one-shot, like in Grace
        elif self.pan_graph is not None:
            self.pan_graph = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.projectEdited.emit()

    def mouseDoubleClickEvent(self, event):
        """Like Grace: double-click a set, an axis, the title or the legend to edit it."""
        pos = event.position()
        if self.mode == "region":
            self.finish_region()
            return
        index = self.object_at(pos)
        if index >= 0:
            self.editRequest.emit("object", -1, index)
            return
        hit = self.label_at(pos)
        if hit is not None:
            self.editRequest.emit(hit[0], hit[1], -1)
            return
        axis_hit = self.axis_near(pos)
        if axis_hit is not None:
            self.editRequest.emit(axis_hit[0], axis_hit[1], -1)
            return
        margin = 0.12 * self.page_rect().height()
        layouts = self.renderer.layout
        for i in range(len(layouts) - 1, -1, -1):
            lay = layouts[i]
            if lay is None:
                continue
            frame = lay.frame
            gi = lay.index
            if lay.legend_rect is not None and lay.legend_rect.contains(pos):
                self.editRequest.emit("legend", gi, -1)
                return
            if frame.contains(pos):
                si = self.nearest_set(gi, pos, 12)
                if si is not None:
                    self.editRequest.emit("set", gi, si)
                else:
                    self.editRequest.emit("graph", gi, -1)
                return
            inside_x = pos.x() >= frame.left() and pos.x() <= frame.right()
            inside_y = pos.y() >= frame.top() and pos.y() <= frame.bottom()
            if inside_x and pos.y() > frame.bottom() and pos.y() < frame.bottom() + margin:
                self.editRequest.emit("xaxis", gi, -1)
                return
            if inside_y and pos.x() > frame.left() - margin and pos.x() < frame.left():
                self.editRequest.emit("yaxis", gi, -1)
                return
            if inside_x and pos.y() > frame.top() - margin and pos.y() < frame.top():
                self.editRequest.emit("title", gi, -1)
                return

    # ----------------------------------------------------------- drawing objects
    def object_at(self, pos):
        """Index of the top-most drawing object under pos, or -1."""
        rects = self.renderer.object_rects
        for i in range(len(rects) - 1, -1, -1):
            rect = rects[i]
            if rect is not None and rect.adjusted(-3, -3, 3, 3).contains(pos):
                return i
        return -1

    def make_object(self, kind, start, end):
        """A new DrawObject from two pixel positions, in page or data coordinates."""
        obj = DrawObject(kind)
        if kind == "text":
            obj.text = "Text"
        graph_index = self.graph_at(start)
        if graph_index is None:
            graph_index = self.project.current
        lay = self.layout_of(graph_index)
        if self.new_object_coords == "world" and lay is not None:
            obj.coords = "world"
            obj.graph = graph_index
            obj.x1, obj.y1 = lay.map.to_world(start.x(), start.y())
            obj.x2, obj.y2 = lay.map.to_world(end.x(), end.y())
        else:
            obj.coords = "view"
            obj.x1, obj.y1 = self.renderer.px_to_view(start.x(), start.y())
            obj.x2, obj.y2 = self.renderer.px_to_view(end.x(), end.y())
        return obj

    def start_object_drag(self, index, pos):
        obj = self.project.objects[index]
        corners = self.renderer.object_corners_px(obj)
        if corners is None:
            return
        self.drag_object = index
        self.drag_start = pos
        self.drag_original = (obj.x1, obj.y1, obj.x2, obj.y2)
        self.drag_corners = corners
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def move_dragged_object(self, pos):
        obj = self.project.objects[self.drag_object]
        dx = pos.x() - self.drag_start.x()
        dy = pos.y() - self.drag_start.y()
        if obj.coords == "world":
            gmap = self.renderer.graph_map(obj.graph)
            if gmap is None:
                return
            c = self.drag_corners
            obj.x1, obj.y1 = gmap.to_world(c[0] + dx, c[1] + dy)
            obj.x2, obj.y2 = gmap.to_world(c[2] + dx, c[3] + dy)
        else:
            scale = self.renderer.view_scale
            original = self.drag_original
            obj.x1 = original[0] + dx / scale
            obj.y1 = original[1] - dy / scale          # view y points up
            obj.x2 = original[2] + dx / scale
            obj.y2 = original[3] - dy / scale

    # ----------------------------------------------------------- regions
    def add_region_point(self, pos):
        if self.region_graph is None:
            graph_index = self.graph_at(pos)
            if graph_index is None:
                graph_index = self.project.current
            self.region_graph = graph_index
        lay = self.layout_of(self.region_graph)
        if lay is None:
            return
        wx, wy = lay.map.to_world(pos.x(), pos.y())
        self.region_points.append(pos)
        self.region_world.append([wx, wy])
        is_polygon = self.region_type == "inside" or self.region_type == "outside"
        if not is_polygon and len(self.region_world) == 2:
            self.finish_region()
        else:
            self.update()

    def finish_region(self):
        is_polygon = self.region_type == "inside" or self.region_type == "outside"
        enough = len(self.region_world) >= 3
        if not is_polygon:
            enough = len(self.region_world) >= 2
        if enough:
            self.regionDefined.emit(self.region_type, self.region_graph, list(self.region_world))
        else:
            self.statusMessage.emit("Region cancelled: not enough points")
        self.set_mode("draw")

    def wheelEvent(self, event):
        """Zoom around the mouse. Shift: Y only. Ctrl: X only."""
        pos = event.position()
        graph_index = self.graph_at(pos)
        lay = self.layout_of(graph_index)
        if lay is None:
            return
        g = self.project.graphs[graph_index]
        frame = lay.frame
        if event.angleDelta().y() > 0:
            factor = 0.85            # zoom in
        else:
            factor = 1 / 0.85        # zoom out
        # Mouse position as a fraction of the frame; that point stays fixed
        tx = (pos.x() - frame.left()) / frame.width()
        ty = (frame.bottom() - pos.y()) / frame.height()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if not shift:
            set_range_t(g.xaxis, tx - tx * factor, tx + (1 - tx) * factor)
        if not ctrl:
            set_range_t(g.yaxis, ty - ty * factor, ty + (1 - ty) * factor)
        self.set_focus_graph(graph_index)
        self.projectEdited.emit()


def normalize_angle(angle):
    """Keep angles between -180 and 180 degrees."""
    while angle > 180.0:
        angle = angle - 360.0
    while angle <= -180.0:
        angle = angle + 360.0
    return round(angle, 4)
