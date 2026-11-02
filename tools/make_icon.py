"""Draw the app icon: two speech bubbles, one with a Latin and one with an Arabic letter.

Usage: python tools/make_icon.py img/icon.png [LETTER [FONT [macos]]]
With macos, the drawing is smaller, as macOS leaves a transparent margin around icons.
This is a simple starting icon, to be replaced by a designed one.
"""
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

SIZE = 1024
BOLD = True  # the Arabic letter is as heavy as the bold A


def bubble(painter, rect, tail_left, fill):
    """A rounded speech bubble with a small tail at the bottom"""
    path = QPainterPath()
    path.addRoundedRect(rect, 90, 90)
    x = rect.left() + 110 if tail_left else rect.right() - 110
    tail = QPainterPath()
    tail.moveTo(x - 40, rect.bottom() - 5)
    tail.lineTo(x + (-50 if tail_left else 50), rect.bottom() + 85)
    tail.lineTo(x + 50, rect.bottom() - 5)
    tail.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawPath(path.united(tail))


def draw_letter(painter, font, bold, letter, area, color, size):
    font.setBold(bold)
    font.setPixelSize(size)
    box = QFontMetricsF(font).tightBoundingRect(letter)
    scale = min(1.0, 0.6 * area.height() / box.height(), 0.7 * area.width() / box.width())
    font.setPixelSize(int(size * scale))
    box = QFontMetricsF(font).tightBoundingRect(letter)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QPointF(area.center().x() - box.center().x(), area.center().y() - box.center().y()), letter)


def main(output, letter="ع", font_name="Geeza Pro", style=""):
    app = QGuiApplication([])
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if style == "macos":  # the icon takes 824 of 1024 pixels
        painter.translate(SIZE / 2, SIZE / 2)
        painter.scale(824 / 1024, 824 / 1024)
        painter.translate(-SIZE / 2, -SIZE / 2)

    # Background: a rounded square with a blue gradient
    gradient = QLinearGradient(QPointF(0, 0), QPointF(0, SIZE))
    gradient.setColorAt(0, QColor("#3b82f6"))
    gradient.setColorAt(1, QColor("#1d4ed8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(40, 40, SIZE - 80, SIZE - 80), 220, 220)

    # The white bubble with its A first, so the yellow bubble can cover a little of the foot of the A
    bubble(painter, QRectF(150, 190, 470, 380), True, QColor("#ffffff"))
    draw_letter(painter, QFont("Arial", 1), True, "A", QRectF(150, 190, 400, 370), QColor("#1d4ed8"), 280)
    bubble(painter, QRectF(400, 400, 470, 380), False, QColor("#fbbf24"))
    draw_letter(painter, QFont(font_name, 1), BOLD, letter, QRectF(400, 400, 470, 380), QColor("#7c2d12"), 300)
    painter.end()
    image.save(output)
    print("Saved", output)


if __name__ == "__main__":
    main(*sys.argv[1:5])
