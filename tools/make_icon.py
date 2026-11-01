"""Draw the app icon: two speech bubbles, one with a Latin and one with an Arabic letter.

Usage: python tools/make_icon.py img/icon.png [LETTER [FONT]]
This is a simple starting icon, to be replaced by a designed one.
"""
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

SIZE = 1024


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


def main(output, letter="ع", font_name="Geeza Pro"):
    app = QGuiApplication([])
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Background: a rounded square with a blue gradient
    gradient = QLinearGradient(QPointF(0, 0), QPointF(0, SIZE))
    gradient.setColorAt(0, QColor("#3b82f6"))
    gradient.setColorAt(1, QColor("#1d4ed8"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(40, 40, SIZE - 80, SIZE - 80), 220, 220)

    # The bubbles
    bubble(painter, QRectF(150, 190, 470, 380), True, QColor("#ffffff"))
    bubble(painter, QRectF(400, 400, 470, 380), False, QColor("#fbbf24"))

    # The letters
    painter.setPen(QColor("#1d4ed8"))
    font = QFont("Arial", 1)
    font.setBold(True)
    font.setPixelSize(280)
    painter.setFont(font)
    painter.drawText(QRectF(140, 190, 360, 380), Qt.AlignmentFlag.AlignCenter, "A")
    arabic = QFont(font_name, 1)
    arabic.setPixelSize(300)
    painter.setFont(arabic)
    painter.setPen(QColor("#7c2d12"))
    painter.drawText(QRectF(400, 400, 470, 380), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    image.save(output)
    print("Saved", output)


if __name__ == "__main__":
    main(*sys.argv[1:4])
