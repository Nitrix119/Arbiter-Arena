"""Draw the write-up's charts from a study report's ``matches.csv`` (ledger A11).

    python tools/plot_study.py results/final --out docs/figures

Needs the ``[plots]`` extra (``pip install -e ".[plots]"``). Every point and interval
comes from the report's own estimators (``cluster_ratio``, ``bootstrap_mean``,
``wilson``) at the same seed, so a chart can never disagree with ``summary.md``.
The harness itself never imports a plotting library; this script is the only
consumer of matplotlib.

Three figures, written as SVG and PNG:

- ``validity``: first-attempt validity on fresh decisions, by condition, per model (H1).
- ``friendly_fire``: allies caught per area-spell cast, by condition, per model (H4b).
- ``sonnet_tactics``: Claude Sonnet 5.5's outcome and kiting, by condition.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.arena.study_report import (  # noqa: E402
    bootstrap_mean,
    cluster_ratio,
    wilson,
)

#: The models in the README's order, weakest to strongest, with display names.
MODELS: Dict[str, str] = {
    "nvidia/nemotron-3.5-lightning": "Nemotron 3.5 Lightning",
    "google/gemini-3.8-flash": "Gemini 3.8 Flash",
    "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5",
}
SONNET = "anthropic/claude-sonnet-5.5"
CONDITIONS: Tuple[str, ...] = ("C1", "C2", "C2+M", "C3")

#: One colour per condition, the same in every figure. The first four slots of the
#: dataviz reference palette, validated on white (adjacent CVD ΔE ≥ 9.1). The two
#: lighter slots sit below 3:1 contrast, which is why every condition is also named on
#: its axis: colour is never the only cue.
CONDITION_COLOURS: Dict[str, str] = {
    "C1": "#2a78d6",
    "C2": "#eb6834",
    "C2+M": "#1baf7a",
    "C3": "#eda100",
}
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e6e5e1"

Row = Dict[str, str]
Interval = Tuple[float, float, float]  # point, low, high


@dataclass(frozen=True)
class Point:
    """One condition's estimate in one panel, with its count for the axis label."""

    condition: str
    estimate: Optional[Interval]
    n: int


def read_matches(bundle: Path) -> List[Row]:
    with open(bundle / "report" / "matches.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _num(row: Row, field: str) -> float:
    return float(row[field])


def _cell(rows: Sequence[Row], model: str, condition: str) -> List[Row]:
    return [r for r in rows if r["model"] == model and r["condition"] == condition]


def validity(rows: Sequence[Row], model: str) -> List[Point]:
    """H1: first-attempt valid / fresh decisions, pooled, with the match bootstrap."""
    points = []
    for condition in CONDITIONS:
        cell = _cell(rows, model, condition)
        clusters = [
            (_num(r, "first_attempt_valid"), _num(r, "fresh_decisions")) for r in cell
        ]
        n = int(sum(d for _, d in clusters))
        points.append(Point(condition, cluster_ratio(clusters), n))
    return points


def friendly_fire(rows: Sequence[Row], model: str) -> List[Point]:
    """H4b: allies caught per area cast. ``n`` is the number of casts."""
    points = []
    for condition in CONDITIONS:
        cell = _cell(rows, model, condition)
        clusters = [(_num(r, "area_allies"), _num(r, "area_casts")) for r in cell]
        n = int(sum(d for _, d in clusters))
        points.append(Point(condition, cluster_ratio(clusters), n))
    return points


def _wilson_point(successes: int, trials: int) -> Optional[Interval]:
    interval = wilson(successes, trials)
    if interval is None:
        return None
    return successes / trials, interval[0], interval[1]


def win_rate(rows: Sequence[Row], model: str) -> List[Point]:
    """Share of matches won, with the Wilson interval the report uses."""
    points = []
    for condition in CONDITIONS:
        cell = _cell(rows, model, condition)
        won = sum(r["model_won"] == "True" for r in cell)
        points.append(Point(condition, _wilson_point(won, len(cell)), len(cell)))
    return points


def match_mean(
    rows: Sequence[Row], model: str, field: str, scenario: Optional[str] = None
) -> List[Point]:
    """A per-match field's mean, bootstrapped over matches, as the report does."""
    points = []
    for condition in CONDITIONS:
        cell = [
            r
            for r in _cell(rows, model, condition)
            if (scenario is None or r["scenario"] == scenario) and r[field] != ""
        ]
        values = [_num(r, field) for r in cell]
        points.append(Point(condition, bootstrap_mean(values), len(values)))
    return points


# -- drawing ----------------------------------------------------------------------


def _style(plt: object) -> None:
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.size": 10,
            "text.color": INK,
            "axes.labelcolor": INK_SECONDARY,
            "axes.edgecolor": GRID,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "xtick.color": INK_SECONDARY,
            "ytick.color": INK_SECONDARY,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "svg.fonttype": "none",  # keep text as text in the SVG
        }
    )


def _panel(
    ax: object,
    points: Sequence[Point],
    *,
    title: str,
    ylim: Tuple[float, float],
    fmt: Callable[[float], str],
    n_label: Optional[str] = None,
    empty: str = "none",
) -> None:
    """A dot-and-interval panel: one dot per condition, its 95% interval as a whisker.

    ``n_label`` puts each condition's count under its tick (e.g. "19 casts"), and a
    condition with no data is labelled with ``empty`` rather than silently dropped.
    """
    xs = range(len(points))
    ax.set_title(title)  # type: ignore[attr-defined]
    ax.set_ylim(*ylim)  # type: ignore[attr-defined]
    ax.set_xlim(-0.6, len(points) - 0.4)  # type: ignore[attr-defined]
    ax.grid(axis="y", color=GRID, linewidth=0.8)  # type: ignore[attr-defined]
    ax.set_axisbelow(True)  # type: ignore[attr-defined]
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)  # type: ignore[attr-defined]
    span = ylim[1] - ylim[0]
    labels = []
    for x, p in zip(xs, points):
        label = p.condition if n_label is None else f"{p.condition}\n{p.n} {n_label}"
        labels.append(label)
        colour = CONDITION_COLOURS[p.condition]
        if p.estimate is None:
            ax.text(  # type: ignore[attr-defined]
                x,
                max(ylim[0], 0) + 0.04 * span,
                empty,
                ha="center",
                color=INK_SECONDARY,
            )
            continue
        point, low, high = p.estimate
        ax.vlines(  # type: ignore[attr-defined]
            x, low, high, color=colour, linewidth=2, capstyle="round"
        )
        ax.plot(  # type: ignore[attr-defined]
            x,
            point,
            "o",
            markersize=8,
            color=colour,
            markeredgecolor="white",
            markeredgewidth=2,
            zorder=3,
        )
        ax.annotate(  # type: ignore[attr-defined]
            fmt(point),
            (x, point),
            xytext=(9, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK,
        )
    ax.set_xticks(list(xs), labels)  # type: ignore[attr-defined]


def _save(fig: object, out: Path, name: str) -> List[Path]:
    paths = [out / f"{name}.svg", out / f"{name}.png"]
    for path in paths:
        fig.savefig(  # type: ignore[attr-defined]
            path, dpi=200, bbox_inches="tight", facecolor="white"
        )
    return paths


def _two_dp(v: float) -> str:
    return f"{v:.2f}"


def _percent(v: float) -> str:
    return f"{v:.0%}"


def draw(rows: Sequence[Row], out: Path) -> List[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    out.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    footnote = "Dots: point estimate. Whiskers: 95% interval (match-level bootstrap)."

    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6), sharey=True)
    for ax, (model, name) in zip(axes, MODELS.items()):
        _panel(ax, validity(rows, model), title=name, ylim=(0, 1.05), fmt=_two_dp)
    axes[0].set_ylabel("First-attempt validity\n(fresh decisions)")
    fig.suptitle(
        "Constraining the action interface raises validity; how much depends on "
        "the model",
        x=0.01,
        ha="left",
        fontsize=12,
        fontweight="bold",
    )
    fig.text(0.01, -0.04, footnote, fontsize=8, color=INK_SECONDARY)
    fig.tight_layout()
    written += _save(fig, out, "validity")
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(10, 3.8), sharey=True)
    for ax, (model, name) in zip(axes, MODELS.items()):
        _panel(
            ax,
            friendly_fire(rows, model),
            title=name,
            ylim=(-0.08, 2.0),  # room below zero so a 0.00 dot is not clipped
            fmt=_two_dp,
            n_label="casts",
            empty="no casts",
        )
    axes[0].set_ylabel("Allies caught per area cast")
    fig.suptitle(
        "Choosing from the menu (C3) all but ends friendly fire; only seeing it "
        "(C2+M) helps the stronger models",
        x=0.01,
        ha="left",
        fontsize=12,
        fontweight="bold",
    )
    fig.text(0.01, -0.06, footnote, fontsize=8, color=INK_SECONDARY)
    fig.tight_layout()
    written += _save(fig, out, "friendly_fire")
    plt.close(fig)

    fig, axes = plt.subplots(1, 4, figsize=(12, 3.6), sharey=True)
    panels = [
        ("Matches won", win_rate(rows, SONNET)),
        ("HP left at the end", match_mean(rows, SONNET, "model_hp_fraction")),
        (
            "Kiting: survived",
            match_mean(rows, SONNET, "tactic:kiting_adherence.survived", "kiting"),
        ),
        (
            "Kiting: time out of melee",
            match_mean(
                rows, SONNET, "tactic:kiting_adherence.frac_out_of_melee", "kiting"
            ),
        ),
    ]
    for ax, (title, points) in zip(axes, panels):
        _panel(ax, points, title=title, ylim=(0, 1.05), fmt=_percent)
    axes[0].set_ylabel("Share (Claude Sonnet 5.5)")
    fig.suptitle(
        "Claude Sonnet 5.5 plays worst with bare tool calls (C2), "
        "and a menu rescues it",
        x=0.01,
        ha="left",
        fontsize=12,
        fontweight="bold",
    )
    fig.text(
        0.01,
        -0.04,
        "Matches won: Wilson 95% interval. Other panels: 95% match-level bootstrap. "
        "Kiting panels: the kiting scenario only (10 matches per condition).",
        fontsize=8,
        color=INK_SECONDARY,
    )
    fig.tight_layout()
    written += _save(fig, out, "sonnet_tactics")
    plt.close(fig)
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path, help="a study bundle with report/")
    parser.add_argument("--out", type=Path, default=Path("docs/figures"))
    args = parser.parse_args(argv)
    for path in draw(read_matches(args.bundle), args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
