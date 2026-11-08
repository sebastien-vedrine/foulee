"""Widgets réutilisables."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from .theme import C, DISPLAY


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setObjectName(role)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse if wrap else Qt.NoTextInteraction)
    return lb


def card(role: str = "card") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName(role)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(8)
    return f, lay


def rule() -> QFrame:
    f = QFrame()
    f.setObjectName("rule")
    return f


def clear_layout(lay: QLayout) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def scroll_page(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(inner)
    return sa


class Balise(QWidget):
    """Marque de balisage : bande blanche au-dessus d'une bande de couleur."""

    def __init__(self, color: str, w: int = 34, h: int = 22, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(w, h)

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        band = (h - 2) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["white"]))
        p.drawRoundedRect(QRectF(0, 0, w, band), 1.5, 1.5)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, band + 2, w, band), 1.5, 1.5)


class Gauge(QWidget):
    """Jauge circulaire 0–100 pour la disponibilité du jour."""

    def __init__(self, size: int = 150, parent=None):
        super().__init__(parent)
        self.value: float | None = None
        self.color = QColor(C["faint"])
        self.caption = ""
        self.setFixedSize(size, size)

    def set_value(self, value: float | None, color: str, caption: str = "") -> None:
        self.value, self.color, self.caption = value, QColor(color), caption
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height())
        r = QRectF(9, 9, s - 18, s - 18)
        pen = QPen(QColor(C["line"]), 9, Qt.SolidLine, Qt.FlatCap)
        p.setPen(pen)
        p.drawArc(r, 225 * 16, -270 * 16)
        if self.value is not None:
            pen.setColor(self.color)
            p.setPen(pen)
            p.drawArc(r, 225 * 16, int(-270 * 16 * max(0, min(self.value, 100)) / 100))
        p.setPen(QColor(C["white"]))
        f = QFont(DISPLAY)
        f.setPixelSize(int(s * 0.30))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        txt = "–" if self.value is None else f"{self.value:.0f}"
        p.drawText(QRectF(0, s * 0.18, s, s * 0.5), Qt.AlignCenter, txt)
        f2 = QFont()
        f2.setPixelSize(int(s * 0.095))
        p.setFont(f2)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(0, s * 0.62, s, s * 0.16), Qt.AlignCenter, self.caption)


class Bar(QWidget):
    """Barre horizontale fine (0–100)."""

    def __init__(self, value: float, color: str, parent=None):
        super().__init__(parent)
        self.value, self.color = value, QColor(color)
        self.setFixedHeight(6)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["line"]))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 6), 3, 3)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, self.width() * max(0, min(self.value, 100)) / 100, 6), 3, 3)


class StackedBar(QWidget):
    """Barre de répartition (ex. temps par zone)."""

    def __init__(self, parts: list[tuple[float, str]], height: int = 12, parent=None):
        super().__init__(parent)
        self.parts = parts
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):
        tot = sum(v for v, _ in self.parts) or 1
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        x = 0.0
        for v, col in self.parts:
            w = self.width() * v / tot
            p.setBrush(QColor(col))
            p.drawRect(QRectF(x, 0, w, self.height()))
            x += w


class Tile(QFrame):
    """Indicateur : intitulé, valeur, précision."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.t = label(title, "small")
        self.v = label("–", "big")
        self.s = label("", "small", wrap=True)
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.s)
        lay.addStretch(1)

    def set(self, value: str, sub: str = "", color: str | None = None, tip: str = "") -> None:
        self.v.setText(value)
        self.s.setText(sub)
        self.v.setStyleSheet(f"color: {color};" if color else "")
        if tip:
            self.setToolTip(tip)

    def sizeHint(self):
        return QSize(160, 96)


def hbox(*widgets, spacing: int = 10, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay
