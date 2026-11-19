"""Display paths of the graph curves: binned by pixel column, broken at gaps."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pyqtgraph")
from can_toolbox.ui.graphics import display_path, gap_path, visible_gaps  # noqa: E402

pytestmark = pytest.mark.gui


def _gappy(period: float, seconds: float = 100.0):
    """Samples every ``period`` with eight 2 s holes; returns times, values and gap indices."""
    times = np.arange(0.0, seconds, period)
    for start in np.linspace(5.0, seconds - 10.0, 8):
        times = times[(times < start) | (times >= start + 2.0)]
    values = np.sin(times)
    gaps = np.flatnonzero(np.diff(times) > 1.5 * period)
    return times, values, gaps


def _solid_spans(x: np.ndarray, y: np.ndarray):
    """The holds a stepMode="right" curve draws: (from, to) of each finite value."""
    finite = np.isfinite(y[:-1])
    return x[:-1][finite], x[1:][finite]


@pytest.mark.parametrize("period", [0.01, 0.001])
@pytest.mark.parametrize("columns", [1300, 300])
def test_no_solid_hold_crosses_a_gap_at_any_zoom(period, columns):
    times, values, gaps = _gappy(period)
    assert len(gaps) == 8
    x, y = display_path(times, values, gaps, 0.0, 100.0, columns)
    assert len(x) <= 4 * (columns + 2) + len(gaps)  # binned, not one point per sample
    starts, ends = _solid_spans(x, y)
    for gap in gaps:
        middle = (times[gap] + times[gap + 1]) / 2
        assert not np.any((starts <= middle) & (ends > middle)), f"solid hold across the gap at {middle}"
        # The curve picks up again right after the gap.
        after = times[gap + 1]
        assert np.any(np.isfinite(y) & (x >= after) & (x <= after + 2 * 100.0 / columns))


def test_binned_columns_keep_the_extremes_and_the_held_value():
    rng = np.random.default_rng(1)
    times = np.sort(rng.uniform(0.0, 10.0, 50_000))
    values = rng.normal(size=len(times))
    x, y = display_path(times, values, np.zeros(0, np.int64), 2.0, 8.0, 100)
    assert np.nanmax(y) == pytest.approx(values[(times >= 1.9) & (times <= 8.1)].max(), abs=1.0)
    start = int(np.searchsorted(times, 2.0, side="right")) - 1
    stop = int(np.searchsorted(times, 8.0, side="left")) + 1
    visible = values[start:stop]
    assert np.nanmax(y) == visible.max() and np.nanmin(y) == visible.min()
    # Each column ends on its last sample, which is what is held until the next column.
    assert y[-1] == visible[-1]
    assert np.all(np.diff(x) >= 0)


def test_few_samples_are_drawn_as_they_are_with_a_break_per_gap():
    times = np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7])
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    x, y = display_path(times, values, np.array([2]), 0.15, 0.65, 1000)
    # One sample beyond each edge stays: its hold crosses into the view.
    assert x.tolist() == pytest.approx([0.1, 0.2, 0.2, 0.5, 0.6, 0.7])
    assert np.isnan(y[2]) and np.delete(y, 2).tolist() == [2.0, 3.0, 4.0, 5.0, 6.0]
    assert display_path(np.zeros(0), np.zeros(0), np.zeros(0, np.int64), 0.0, 1.0, 10)[0].size == 0


def test_gap_path_draws_each_missed_hold_and_its_step():
    times = np.array([0.0, 0.1, 0.5, 0.6])
    values = np.array([1.0, 2.0, 3.0, 4.0])
    x, y = gap_path(times, values, np.array([1]))
    assert x.tolist() == pytest.approx([0.1, 0.5, 0.5, 0.5])
    assert y[:3].tolist() == [2.0, 2.0, 3.0] and np.isnan(y[3])


def test_only_gaps_on_screen_and_wide_enough_to_dash_are_kept():
    times = np.array([0.0, 1.0, 1.05, 3.0, 3.01, 3.5, 9.0, 9.5])
    gaps = np.array([0, 2, 5])  # 1.0 s, 1.95 s and 5.5 s holds
    assert visible_gaps(times, gaps, 0.5, 4.0, 0.01).tolist() == [0, 2, 5]
    assert visible_gaps(times, gaps, 0.5, 4.0, 1.5).tolist() == [2, 5]
    assert visible_gaps(times, gaps, 1.2, 2.0, 0.01).tolist() == [2]  # the others end or start off screen
    assert visible_gaps(times, gaps, 4.0, 8.0, 0.01).tolist() == [5]  # a hold crossing the whole view
    assert visible_gaps(times, np.zeros(0, np.int64), 0.0, 9.0, 0.1).tolist() == []
