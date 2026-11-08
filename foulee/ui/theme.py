"""Thème visuel.

Direction : la signalétique des sentiers. Les types de séance reprennent les
couleurs du balisage (rouge GR pour l'intensité, jaune PR pour le renfo, vert et
bleu pour l'endurance et le repos) et la typographie Barlow, dessinée d'après les
panneaux routiers, sert aux titres et aux chiffres. Fond bleu ardoise d'une
sortie avant l'aube.
"""
from __future__ import annotations

from ..paths import resource

C = {
    "bg": "#141B24",
    "side": "#10161E",
    "panel": "#1B2430",
    "panel2": "#232E3B",
    "line": "#2D3A49",
    "text": "#E7ECF1",
    "muted": "#93A1B2",
    "faint": "#5F6E80",
    "white": "#F3F5F7",
    "red": "#E5484D",
    "yellow": "#E8B53A",
    "green": "#3DB37A",
    "blue": "#4E8FD8",
    "orange": "#EE8A3C",
}

KIND_COLORS = {"REPOS": C["blue"], "FRACTIONNE": C["red"], "RENFO": C["yellow"], "Z2": C["green"], "COURSE": C["orange"]}

DISPLAY = "Barlow Semi Condensed"
BODY = "Barlow"
FONT_FILES = ["BarlowSemiCondensed-SemiBold.ttf", "BarlowSemiCondensed-Medium.ttf",
              "Barlow-Regular.ttf", "Barlow-Medium.ttf", "Barlow-SemiBold.ttf"]


def level_color(score: float | None) -> str:
    if score is None:
        return C["faint"]
    if score >= 70:
        return C["green"]
    if score >= 50:
        return C["yellow"]
    if score >= 35:
        return C["orange"]
    return C["red"]


def load_fonts() -> None:
    from PySide6.QtGui import QFontDatabase
    for f in FONT_FILES:
        p = resource(f"assets/{f}")
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))
    try:
        from matplotlib import font_manager, rcParams
        for f in FONT_FILES:
            p = resource(f"assets/{f}")
            if p.exists():
                font_manager.fontManager.addfont(str(p))
        rcParams["font.family"] = [BODY, "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False
    except Exception:
        pass


STYLESHEET = f"""
* {{ font-family: "{BODY}", "Segoe UI", sans-serif; font-size: 14px; color: {C['text']}; }}
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {C['bg']}; }}
QWidget#sidebar {{ background: {C['side']}; }}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-family: "{DISPLAY}"; font-size: 30px; font-weight: 600; color: {C['white']}; }}
QLabel#brandSub {{ color: {C['faint']}; font-size: 12px; }}
QPushButton#nav {{ text-align: left; padding: 10px 18px; border: none; border-left: 3px solid transparent;
    background: transparent; color: {C['muted']}; font-size: 15px; }}
QPushButton#nav:hover {{ color: {C['text']}; background: {C['panel']}; }}
QPushButton#nav:checked {{ color: {C['white']}; border-left: 3px solid {C['red']}; background: {C['panel']}; font-weight: 600; }}
QLabel#h1 {{ font-family: "{DISPLAY}"; font-size: 28px; font-weight: 600; color: {C['white']}; }}
QLabel#h2 {{ font-family: "{DISPLAY}"; font-size: 19px; font-weight: 600; color: {C['white']}; }}
QLabel#h3 {{ font-family: "{DISPLAY}"; font-size: 16px; font-weight: 500; color: {C['text']}; }}
QLabel#muted {{ color: {C['muted']}; }}
QLabel#small {{ color: {C['muted']}; font-size: 12px; }}
QLabel#big {{ font-family: "{DISPLAY}"; font-size: 34px; font-weight: 600; color: {C['white']}; }}
QLabel#kind {{ font-family: "{DISPLAY}"; font-size: 44px; font-weight: 600; color: {C['white']}; }}
QFrame#card {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 6px; }}
QFrame#hero {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 10px; }}
QFrame#chip {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 6px; }}
QFrame#chipToday {{ background: {C['panel2']}; border: 1px solid {C['muted']}; border-radius: 6px; }}
QFrame#rule {{ background: {C['line']}; max-height: 1px; min-height: 1px; border: none; }}
QPushButton {{ background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 5px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {C['muted']}; }}
QPushButton:disabled {{ color: {C['faint']}; }}
QPushButton#primary {{ background: {C['red']}; border: 1px solid {C['red']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #F0585D; }}
QPushButton#seg {{ padding: 5px 12px; border-radius: 4px; }}
QPushButton#seg:checked {{ background: {C['line']}; border-color: {C['muted']}; }}
QPushButton:focus {{ outline: none; border-color: {C['blue']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit, QPlainTextEdit {{
    background: {C['bg']}; border: 1px solid {C['line']}; border-radius: 4px; padding: 5px 8px;
    selection-background-color: {C['blue']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border-color: {C['blue']}; }}
QComboBox QAbstractItemView {{ background: {C['panel']}; border: 1px solid {C['line']}; selection-background-color: {C['panel2']}; }}
QCheckBox {{ spacing: 8px; }}
QTableWidget {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 6px; gridline-color: {C['line']};
    alternate-background-color: {C['panel2']}; selection-background-color: #34465C; }}
QHeaderView::section {{ background: {C['panel']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['line']};
    padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {C['panel']}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C['line']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {C['line']}; border-radius: 5px; min-width: 30px; }}
QProgressBar {{ background: {C['panel2']}; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {C['blue']}; border-radius: 3px; }}
QStatusBar {{ background: {C['side']}; color: {C['muted']}; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['line']}; padding: 6px; }}
QDialog {{ background: {C['bg']}; }}
QMessageBox {{ background: {C['bg']}; }}
"""
