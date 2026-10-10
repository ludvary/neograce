"""
icons.py - the line icons in the button column, drawn with QPainter.

Icons are drawn on a 20 x 20 grid (then rendered 3x larger for sharp
high-DPI screens), so they can be recoloured for every theme.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE = 20       # logical size in pixels
SCALE = 3       # drawn 3x larger for sharp icons on high-DPI screens


def line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def arrowhead(p, tip_x, tip_y, angle_degrees, length=3.6):
    """Two short strokes forming an arrow tip at (tip_x, tip_y) pointing in direction angle."""
    angle = math.radians(angle_degrees)
    for side in (-1, 1):
        back = angle + math.pi + side * math.radians(38)
        line(p, tip_x, tip_y, tip_x + length * math.cos(back), tip_y + length * math.sin(back))


def magnifier(p):
    cx = 8.5
    cy = 8.5
    r = 5.2
    p.drawEllipse(QPointF(cx, cy), r, r)
    d = r / math.sqrt(2)
    line(p, cx + d + 0.6, cy + d + 0.6, 17.2, 17.2)


def polyline(p, points):
    path = QPainterPath(QPointF(points[0][0], points[0][1]))
    for i in range(1, len(points)):
        path.lineTo(QPointF(points[i][0], points[i][1]))
    p.drawPath(path)


def draw_icon(name, p):
    if name == "draw":                      # circular arrow
        rect = QRectF(4, 4, 12, 12)
        path = QPainterPath()
        path.arcMoveTo(rect, 60)
        path.arcTo(rect, 60, 285)
        p.drawPath(path)
        end = path.currentPosition()
        arrowhead(p, end.x(), end.y(), -75)
    elif name == "zoom":
        magnifier(p)
    elif name == "zin":
        magnifier(p)
        line(p, 6, 8.5, 11, 8.5)
        line(p, 8.5, 6, 8.5, 11)
    elif name == "zout":
        magnifier(p)
        line(p, 6, 8.5, 11, 8.5)
    elif name == "autoscale":               # four corner brackets
        corners = [(3, 3, 1, 1), (17, 3, -1, 1), (3, 17, 1, -1), (17, 17, -1, -1)]
        for x, y, dx, dy in corners:
            line(p, x, y, x + 4.5 * dx, y)
            line(p, x, y, x, y + 4.5 * dy)
        p.drawRect(QRectF(7.5, 7.5, 5, 5))
    elif name == "left":
        polyline(p, [(12, 5), (7, 10), (12, 15)])
    elif name == "right":
        polyline(p, [(8, 5), (13, 10), (8, 15)])
    elif name == "up":
        polyline(p, [(5, 12.5), (10, 7.5), (15, 12.5)])
    elif name == "down":
        polyline(p, [(5, 7.5), (10, 12.5), (15, 7.5)])
    elif name == "autoticks":               # a ruler
        line(p, 2.5, 14, 17.5, 14)
        positions = [3, 6.5, 10, 13.5, 17]
        for i in range(len(positions)):
            if i % 2 == 0:
                top = 8
            else:
                top = 10.5
            line(p, positions[i], 14, positions[i], top)
    elif name == "target":                  # crosshair
        p.drawEllipse(QPointF(10, 10), 5.5, 5.5)
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(10, 10), 1.3, 1.3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        line(p, 10, 1.5, 10, 4)
        line(p, 10, 16, 10, 18.5)
        line(p, 1.5, 10, 4, 10)
        line(p, 16, 10, 18.5, 10)
    elif name == "zx":                      # |<->|
        line(p, 3, 5, 3, 15)
        line(p, 17, 5, 17, 15)
        line(p, 5.5, 10, 14.5, 10)
        arrowhead(p, 5.5, 10, 180, 2.4)
        arrowhead(p, 14.5, 10, 0, 2.4)
    elif name == "zy":
        line(p, 5, 3, 15, 3)
        line(p, 5, 17, 15, 17)
        line(p, 10, 5.5, 10, 14.5)
        arrowhead(p, 10, 5.5, -90, 2.4)
        arrowhead(p, 10, 14.5, 90, 2.4)
    elif name == "ax":                      # <-|->
        line(p, 10, 5, 10, 15)
        line(p, 7.5, 10, 2.5, 10)
        line(p, 12.5, 10, 17.5, 10)
        arrowhead(p, 2.5, 10, 180, 2.4)
        arrowhead(p, 17.5, 10, 0, 2.4)
    elif name == "ay":
        line(p, 5, 10, 15, 10)
        line(p, 10, 7.5, 10, 2.5)
        line(p, 10, 12.5, 10, 17.5)
        arrowhead(p, 10, 2.5, -90, 2.4)
        arrowhead(p, 10, 17.5, 90, 2.4)
    elif name == "push" or name == "pop":   # a stack of two layers with an arrow
        for y in (12.5, 16.2):
            layer = QPainterPath(QPointF(3.5, y))
            layer.lineTo(10, y - 2.4)
            layer.lineTo(16.5, y)
            layer.lineTo(10, y + 2.4)
            layer.closeSubpath()
            p.drawPath(layer)
        if name == "push":
            line(p, 10, 1.5, 10, 7.2)
            arrowhead(p, 10, 7.2, 90, 2.4)
        else:
            line(p, 10, 7.2, 10, 1.5)
            arrowhead(p, 10, 1.5, -90, 2.4)
    elif name == "undo" or name == "redo":
        path = QPainterPath()
        if name == "undo":
            path.moveTo(5, 8)
            path.lineTo(12.5, 8)
            path.cubicTo(18.5, 8, 18.5, 16, 12.5, 16)
            path.lineTo(8, 16)
            p.drawPath(path)
            arrowhead(p, 5, 8, 180, 3.4)
        else:
            path.moveTo(15, 8)
            path.lineTo(7.5, 8)
            path.cubicTo(1.5, 8, 1.5, 16, 7.5, 16)
            path.lineTo(12, 16)
            p.drawPath(path)
            arrowhead(p, 15, 8, 0, 3.4)
    elif name == "exit":                    # power symbol
        rect = QRectF(4, 4.5, 12, 12)
        path = QPainterPath()
        path.arcMoveTo(rect, 125)
        path.arcTo(rect, 125, 290)
        p.drawPath(path)
        line(p, 10, 2.5, 10, 9.5)


def make_pixmap(name, color):
    pixmap = QPixmap(SIZE * SCALE, SIZE * SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(SCALE, SCALE)
    pen = QPen(QColor(color), 1.55)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    draw_icon(name, p)
    p.end()
    pixmap.setDevicePixelRatio(SCALE)
    return pixmap


def make_icon(name, theme):
    """An icon with different colours for normal, hover, checked and disabled."""
    icon = QIcon()
    icon.addPixmap(make_pixmap(name, theme.muted), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(make_pixmap(name, theme.text), QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(make_pixmap(name, theme.accent), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(make_pixmap(name, theme.accent), QIcon.Mode.Active, QIcon.State.On)
    icon.addPixmap(make_pixmap(name, theme.disabled), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon
