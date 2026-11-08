"""Graphiques (matplotlib intégré à Qt)."""
from __future__ import annotations

from datetime import date, timedelta

import matplotlib

matplotlib.use("QtAgg")
import matplotlib.dates as mdates  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from .theme import C  # noqa: E402

MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _fr_date(x, _pos=None):
    d = mdates.num2date(x)
    return f"{d.day} {MONTHS[d.month - 1]}"


class Chart(FigureCanvasQTAgg):
    def __init__(self, height: float = 2.6, rows: int = 1, sharex: bool = True):
        self.fig = Figure(figsize=(8, height), dpi=100, facecolor=C["panel"])
        super().__init__(self.fig)
        self.rows = rows
        self.sharex = sharex
        self.setMinimumHeight(int(height * 100))
        self.axes = []
        self.reset()

    def reset(self):
        self.fig.clear()
        if self.rows == 1:
            self.axes = [self.fig.add_subplot(111)]
        else:
            self.axes = list(self.fig.subplots(self.rows, 1, sharex=self.sharex))
        for ax in self.axes:
            style(ax)
        return self.axes

    def finish(self):
        self.fig.tight_layout(pad=1.0)
        self.draw_idle()


def style(ax):
    ax.set_facecolor(C["panel"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C["line"])
    ax.tick_params(colors=C["muted"], labelsize=9, length=0, pad=6)
    ax.grid(True, axis="y", color=C["line"], linewidth=0.6, alpha=0.8)
    ax.yaxis.label.set_color(C["muted"])
    ax.xaxis.set_major_formatter(_fr_date)


def legend(ax, **kw):
    lg = ax.legend(frameon=False, fontsize=9, labelcolor=C["muted"], loc=kw.pop("loc", "upper left"), ncol=kw.pop("ncol", 4), **kw)
    return lg


def empty(ax, text="Pas encore de données sur cette période."):
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", color=C["faint"], fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])


def date_axis(ax, start: date, end: date):
    ax.set_xlim(start, end)
    span = (end - start).days
    if span <= 45:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    elif span <= 200:
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
    else:
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1, interval=2))
    ax.xaxis.set_major_formatter(_fr_date)


def rolling(values: list[float | None], n: int) -> list[float | None]:
    out = []
    for i in range(len(values)):
        win = [v for v in values[max(0, i - n + 1): i + 1] if v is not None]
        out.append(sum(win) / len(win) if win else None)
    return out


def days_back(today: date, n: int) -> list[date]:
    return [today - timedelta(days=n - 1 - i) for i in range(n)]
