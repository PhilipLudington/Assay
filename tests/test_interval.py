"""Intervals, and the boundary behaviour they exist to get right.

The heaviest tests here are the ones about a *constant* sample. Every
measurement this project has taken has been constant — 34/34 in the Phase 0
pilot, 0/10 on `TS-0001` — and the bootstrap DESIGN specifies reports ±0.00 for
all of them, at every K. If that reads as "measured exactly" the K decision
collapses to K=1 and every published width is a fiction, so the tests below pin
both halves: the bootstrap still collapses (it is the correct estimator for what
it estimates), and it says so.
"""

from __future__ import annotations

import pytest

from assay.eval.interval import (
    DEFAULT_CONFIDENCE,
    Interval,
    IntervalError,
    binomial_cdf,
    bootstrap_mean,
    clopper_pearson,
    design_effect,
    disjoint,
    effective_trials,
    smallest_trials,
)

# --- the binomial CDF the exact interval is inverted from --------------------


def test_cdf_matches_hand_computed_values() -> None:
    # P(X <= 1 | n=3, p=0.5) = (1 + 3) / 8
    assert binomial_cdf(1, 3, 0.5) == pytest.approx(0.5)
    assert binomial_cdf(0, 3, 0.5) == pytest.approx(0.125)


def test_cdf_saturates_outside_its_support() -> None:
    assert binomial_cdf(-1, 5, 0.3) == 0.0
    assert binomial_cdf(5, 5, 0.3) == 1.0
    assert binomial_cdf(9, 5, 0.3) == 1.0


def test_cdf_is_monotone_decreasing_in_the_rate() -> None:
    # The property the upper-bound root find depends on. If it ever fails, the
    # bisection returns a number rather than an error.
    values = [binomial_cdf(2, 10, p / 20) for p in range(1, 20)]
    assert values == sorted(values, reverse=True)


# --- clopper-pearson against published values --------------------------------


def test_zero_successes_reproduces_the_rule_of_three() -> None:
    # The textbook 95% upper bound for 0/n is 1 - 0.025^(1/n), ~3/n for n >= 10.
    interval = clopper_pearson(0, 10)
    assert interval.lo == 0.0
    assert interval.hi == pytest.approx(0.3085, abs=5e-4)
    assert interval.point == 0.0
    assert not interval.degenerate


def test_interior_matches_the_published_interval() -> None:
    interval = clopper_pearson(5, 10)
    assert interval.lo == pytest.approx(0.1871, abs=5e-4)
    assert interval.hi == pytest.approx(0.8129, abs=5e-4)


def test_all_successes_pins_the_upper_bound_at_one() -> None:
    interval = clopper_pearson(10, 10)
    assert interval.hi == 1.0
    assert interval.lo == pytest.approx(0.6915, abs=5e-4)


def test_the_boundary_interval_is_not_zero_width() -> None:
    """The single fact the module exists for.

    A normal approximation and a bootstrap both report ±0.00 here. Neither the
    K decision nor any published rate may rest on that.
    """
    assert clopper_pearson(0, 5).half_width > 0.25
    assert clopper_pearson(0, 10).half_width > 0.15
    assert clopper_pearson(10, 10).half_width > 0.15


def test_intervals_narrow_as_trials_grow() -> None:
    widths = [clopper_pearson(0, n).half_width for n in (5, 10, 20, 40, 80)]
    assert widths == sorted(widths, reverse=True)


def test_the_interval_is_widest_at_a_half() -> None:
    middle = clopper_pearson(10, 20).half_width
    assert middle > clopper_pearson(2, 20).half_width
    assert middle > clopper_pearson(18, 20).half_width


def test_confidence_widens_the_interval() -> None:
    assert clopper_pearson(5, 10, 0.99).half_width > clopper_pearson(5, 10, 0.90).half_width


def test_the_point_estimate_sits_inside_its_own_interval() -> None:
    for successes in range(0, 11):
        interval = clopper_pearson(successes, 10)
        assert interval.contains(interval.point)


def test_no_trials_is_refused_rather_than_answered() -> None:
    # A caller with no scored runs has a reporting problem, not a rate. Handing
    # back [0, 1] would let "we ran nothing" print as a measurement.
    with pytest.raises(IntervalError, match="zero trials"):
        clopper_pearson(0, 0)


def test_impossible_and_malformed_inputs_are_refused() -> None:
    with pytest.raises(IntervalError, match="impossible"):
        clopper_pearson(11, 10)
    with pytest.raises(IntervalError, match="impossible"):
        clopper_pearson(-1, 10)
    with pytest.raises(IntervalError, match="confidence"):
        clopper_pearson(1, 10, 1.0)
    with pytest.raises(IntervalError, match="confidence"):
        clopper_pearson(1, 10, 0.0)


# --- the bootstrap, and the collapse it has to admit to ----------------------


def test_a_constant_sample_collapses_and_says_so() -> None:
    interval = bootstrap_mean([0.0] * 10)
    assert interval.lo == interval.hi == 0.0
    assert interval.degenerate


def test_the_collapse_is_the_same_at_every_k() -> None:
    """K buys nothing from a bootstrap over identical values — the trap itself.

    Reading ±0.00 at K=1 as "already precise" is what would have settled K on a
    measurement that measured nothing.
    """
    for runs in (1, 5, 10, 50):
        assert bootstrap_mean([1.0] * runs).half_width == 0.0


def test_a_varying_sample_is_not_flagged_degenerate() -> None:
    interval = bootstrap_mean([0.0, 0.5, 1.0, 0.25])
    assert not interval.degenerate
    assert interval.half_width > 0


def test_the_bootstrap_is_deterministic_across_calls() -> None:
    values = [0.1, 0.4, 0.9, 0.2, 0.7]
    first = bootstrap_mean(values, seed=7)
    assert bootstrap_mean(values, seed=7) == first


def test_the_seed_is_actually_used() -> None:
    # At a low resample count the percentile lands in a different place per
    # seed. Without this, a `bootstrap_mean` that ignored `seed` entirely would
    # still pass the determinism test above.
    values = [0.1, 0.4, 0.9, 0.2, 0.7]
    endpoints = {
        (bootstrap_mean(values, resamples=40, seed=s).lo,
         bootstrap_mean(values, resamples=40, seed=s).hi)
        for s in range(6)
    }
    assert len(endpoints) > 1


def test_the_default_resample_count_makes_the_seed_immaterial() -> None:
    """A published width must not be an artifact of which seed was picked.

    At 10,000 resamples the percentile endpoints are stable across seeds, so
    quoting one is quoting the sample rather than the RNG.
    """
    values = [0.1, 0.4, 0.9, 0.2, 0.7]
    intervals = [bootstrap_mean(values, seed=s) for s in range(5)]
    assert max(i.lo for i in intervals) - min(i.lo for i in intervals) < 0.02
    assert max(i.hi for i in intervals) - min(i.hi for i in intervals) < 0.02


def test_a_wider_sample_gives_a_wider_interval() -> None:
    tight = bootstrap_mean([0.50, 0.51, 0.49, 0.50, 0.51])
    loose = bootstrap_mean([0.05, 0.95, 0.50, 0.10, 0.90])
    assert loose.half_width > tight.half_width


def test_the_interval_stays_inside_the_sample_range() -> None:
    values = [0.2, 0.4, 0.6]
    interval = bootstrap_mean(values)
    assert min(values) <= interval.lo <= interval.hi <= max(values)


def test_an_empty_sample_is_refused() -> None:
    with pytest.raises(IntervalError, match="empty sample"):
        bootstrap_mean([])


def test_malformed_bootstrap_parameters_are_refused() -> None:
    with pytest.raises(IntervalError, match="resamples"):
        bootstrap_mean([0.1, 0.2], resamples=0)
    with pytest.raises(IntervalError, match="confidence"):
        bootstrap_mean([0.1, 0.2], confidence=1.5)


# --- non-overlap, and how blunt it is ----------------------------------------


def test_disjoint_is_symmetric_and_recognises_separation() -> None:
    low = clopper_pearson(0, 100)
    high = clopper_pearson(100, 100)
    assert disjoint(low, high)
    assert disjoint(high, low)


def test_touching_intervals_are_not_disjoint() -> None:
    left = Interval(0.5, 0.0, 0.5, DEFAULT_CONFIDENCE, "test")
    right = Interval(0.5, 0.5, 1.0, DEFAULT_CONFIDENCE, "test")
    assert not disjoint(left, right)


def test_the_most_extreme_result_at_k_of_five_still_does_not_separate() -> None:
    """DESIGN defines a difference as CI non-overlap. Per fixture, it cannot.

    0/5 against 5/5 is the largest effect a five-run cell can possibly show, and
    its intervals still overlap. Any per-fixture claim in a published table
    would therefore read "no difference" no matter what happened, which is why
    the corpus and not K has to carry the statistical weight.
    """
    assert not disjoint(clopper_pearson(0, 5), clopper_pearson(5, 5))
    assert not disjoint(clopper_pearson(0, 10), clopper_pearson(5, 10))
    # It takes both a perfect effect and K=20 before non-overlap appears.
    assert disjoint(clopper_pearson(0, 20), clopper_pearson(20, 20))


# --- what a larger K can and cannot buy --------------------------------------


def test_design_effect_brackets_the_two_extremes() -> None:
    assert design_effect(10, 0.0) == 1.0  # runs independent: K buys the full 1/K
    assert design_effect(10, 1.0) == 10.0  # fixture deterministic: K buys nothing
    assert design_effect(1, 0.7) == 1.0  # a single run is never a cluster


def test_perfect_correlation_makes_extra_runs_worthless() -> None:
    """The case every fixture measured so far has looked like: 34/34, then 0/10."""
    for runs in (1, 5, 20):
        assert effective_trials(15, runs, 1.0) == 15.0


def test_effective_trials_flatten_quickly_at_high_correlation() -> None:
    at_five = effective_trials(15, 5, 0.8)
    at_twenty = effective_trials(15, 20, 0.8)
    # Four times the runs, and four times the spend, for under 4% more
    # information. This is the arithmetic the K decision rests on.
    assert (at_twenty - at_five) / at_five < 0.04


def test_corpus_size_buys_linearly_where_runs_do_not() -> None:
    assert effective_trials(30, 5, 0.8) == pytest.approx(2 * effective_trials(15, 5, 0.8))


def test_malformed_clustering_parameters_are_refused() -> None:
    with pytest.raises(IntervalError, match="runs must be positive"):
        design_effect(0, 0.5)
    with pytest.raises(IntervalError, match="correlation"):
        design_effect(5, 1.5)
    with pytest.raises(IntervalError, match="fixtures must be positive"):
        effective_trials(0, 5, 0.5)


def test_smallest_trials_returns_a_number_that_actually_meets_the_target() -> None:
    needed = smallest_trials(0.15)
    assert needed is not None
    assert clopper_pearson(round(0.5 * needed), needed).half_width <= 0.15
    assert clopper_pearson(round(0.5 * (needed - 1)), needed - 1).half_width > 0.15


def test_smallest_trials_admits_when_the_budget_cannot_reach_the_target() -> None:
    assert smallest_trials(0.01, max_trials=20) is None


def test_smallest_trials_refuses_a_target_outside_the_unit_interval() -> None:
    with pytest.raises(IntervalError, match="target half-width"):
        smallest_trials(0.0)
