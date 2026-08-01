"""Confidence intervals that stay honest when every run agrees.

DESIGN specifies "the mean with a bootstrap 95% CI" for every reported score.
That is right for a mean of bounded reals and **wrong at the boundary**, which
is where every measurement this project has taken so far has landed:

- The Phase 0 pilot found its seeded defect in 34 of 34 runs.
- `TS-0001` was found in 0 of 10, and its per-run precision was 0.00 in all 10.

A percentile bootstrap resamples the observed values. When those values are all
identical, every resample is identical, so the interval is `[v, v]` — half-width
±0.00 — at *every* K. Read naively that says K=1 suffices and the number is
known exactly. It says nothing of the kind. Zero *sample* variance is not zero
*sampling* uncertainty: 0 successes in 5 runs is consistent with a true rate as
high as 0.52, and in 10 runs as high as 0.31. The estimator collapsed; the
uncertainty did not.

So this module draws the line by *what is being estimated*, not by what the
sample happens to look like:

- A **rate** — a count of successes out of n runs, like recall on one fixture —
  gets `clopper_pearson`. It is exact, it is defined at 0/n and n/n, and its
  0-success upper bound is the familiar rule of three (≈3/n).
- A **mean of per-run values** — like the mean of K per-run precisions, where
  each run's precision is itself a ratio — gets `bootstrap_mean`, which sets
  `degenerate=True` when the sample is constant so a caller cannot mistake a
  collapsed interval for a precise one.

Nothing here decides which to use for a given metric; `assay.eval.precision`
and, later, `score.py` do. **Phase 4 must import this module rather than write
its own intervals** — the same rule `review_floor` carries, for the same reason.

The second thing this module exists to say is that CI non-overlap, which DESIGN
makes the definition of a regression, is a far blunter instrument than it looks
per fixture. `disjoint` is deliberately cheap to call so that claim can be
checked rather than assumed: at K=5 even the most extreme possible result —
0/5 against 5/5 — does not separate.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import comb

#: Two-sided, matching DESIGN's "bootstrap 95% CI".
DEFAULT_CONFIDENCE = 0.95

#: Enough that the percentile estimate is stable to ~0.001 and cheap enough to
#: run inside a test. Scoring must be reproducible, so the seed is explicit
#: everywhere rather than left to global RNG state.
DEFAULT_RESAMPLES = 10_000
DEFAULT_SEED = 0

#: Bisection steps for the Clopper-Pearson root find. 2^-60 is far below any
#: precision a rate is reported to; the loop is a fixed count rather than a
#: tolerance test so the result is bit-identical on every machine and every run.
_BISECTION_STEPS = 60


class IntervalError(ValueError):
    """An interval was asked for over data that cannot support one."""


@dataclass(frozen=True)
class Interval:
    """A two-sided interval, and how it was arrived at.

    `method` and `degenerate` travel with the numbers on purpose. A report that
    prints `0.00 ±0.00` is indistinguishable from a precise measurement unless
    it also carries the fact that the estimator had nothing to work with.
    """

    point: float
    lo: float
    hi: float
    confidence: float
    method: str
    #: The sample could not inform the width — every observation was identical,
    #: so the resampled interval collapsed to a point. Never true of an exact
    #: interval, which is defined at the boundary.
    degenerate: bool = False

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def half_width(self) -> float:
        return self.width / 2

    def contains(self, value: float) -> bool:
        return self.lo <= value <= self.hi

    def __str__(self) -> str:
        text = f"{self.point:.3f} [{self.lo:.3f}, {self.hi:.3f}]"
        return text + " (degenerate — sample constant)" if self.degenerate else text


def disjoint(left: Interval, right: Interval) -> bool:
    """Whether two intervals fail to overlap — DESIGN's definition of a difference.

    Worth knowing before relying on it: non-overlap is a *conservative* test.
    Two 95% intervals can overlap while a direct two-sample test rejects at the
    same level, so this under-reports real differences rather than inventing
    them. That bias is the safe one for a benchmark, and it is why the corpus,
    not K, has to carry the statistical weight — see the module docstring.
    """
    return left.hi < right.lo or right.hi < left.lo


# --- exact intervals for rates -----------------------------------------------


def binomial_cdf(successes: int, trials: int, rate: float) -> float:
    """P(X <= successes) for X ~ Binomial(trials, rate). Exact, no dependencies.

    Summed directly because `trials` here is K, or K times a corpus of 15 — in
    the hundreds at most. An approximation would buy nothing and would have to
    be justified at exactly the boundary where approximations are worst.
    """
    if successes < 0:
        return 0.0
    if successes >= trials:
        return 1.0
    return sum(
        comb(trials, i) * rate**i * (1 - rate) ** (trials - i) for i in range(successes + 1)
    )


def _solve_increasing(f, target: float) -> float:  # type: ignore[no-untyped-def]
    """Bisect for `f(p) == target` on [0, 1] where `f` is non-decreasing."""
    lo, hi = 0.0, 1.0
    for _ in range(_BISECTION_STEPS):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(
    successes: int, trials: int, confidence: float = DEFAULT_CONFIDENCE
) -> Interval:
    """The exact interval for a rate, defined at 0/n and n/n.

    Exact rather than Wilson or normal-approximate because the boundary is the
    case this project keeps landing on, and it is precisely where the
    approximations misbehave — a normal interval at 0/n has zero width, which is
    the same failure as the bootstrap's, dressed differently.

    Conservative: actual coverage is at least `confidence`, so intervals are a
    little wide. For a benchmark that is the right direction to err. At 0
    successes the upper bound reduces to the rule of three, `1 - alpha^(1/n)`,
    which is ≈3/n for n above about 10 — so `0/10` reports `[0, 0.31]`, not
    `[0, 0]`.
    """
    if trials <= 0:
        raise IntervalError("a rate over zero trials is not a rate; handle no-data first")
    if not 0 <= successes <= trials:
        raise IntervalError(f"{successes} successes out of {trials} trials is impossible")
    if not 0 < confidence < 1:
        raise IntervalError(f"confidence must be in (0, 1), got {confidence}")

    tail = (1 - confidence) / 2
    # Lower: the largest p for which observing >= `successes` is still likely
    # enough. Exactly 0 at 0 successes — no run succeeded, so no rate is ruled
    # out from below.
    lo = (
        0.0
        if successes == 0
        else _solve_increasing(lambda p: 1 - binomial_cdf(successes - 1, trials, p), tail)
    )
    # Upper: the smallest p for which observing <= `successes` is still likely
    # enough. `binomial_cdf` decreases in p, so solve on its negation.
    hi = (
        1.0
        if successes == trials
        else _solve_increasing(lambda p: -binomial_cdf(successes, trials, p), -tail)
    )
    return Interval(
        point=successes / trials,
        lo=lo,
        hi=hi,
        confidence=confidence,
        method="clopper-pearson",
    )


# --- bootstrap for means of per-run values -----------------------------------


def bootstrap_mean(
    values: list[float],
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> Interval:
    """Percentile bootstrap over per-run values — DESIGN's specified interval.

    Kept, because it is the right tool for a mean of bounded reals that is not a
    count: the mean of K per-run precisions, where each run contributes its own
    ratio, is not a binomial rate and Clopper-Pearson does not apply to it.

    `degenerate` is the whole reason this is a function rather than three lines
    at a call site. A constant sample resamples to itself, so the interval is a
    point at every K — and a report that prints that without the flag is
    claiming certainty it has not earned. Callers are expected to fall back to
    an exact interval on a pooled count, or to say the width is unknown.

    Seeded and fixed-count so scoring the same transcripts twice yields
    identical output, which Phase 4's replay-determinism test requires.
    """
    if not values:
        raise IntervalError("cannot bootstrap an empty sample")
    if resamples < 1:
        raise IntervalError(f"resamples must be positive, got {resamples}")
    if not 0 < confidence < 1:
        raise IntervalError(f"confidence must be in (0, 1), got {confidence}")

    point = sum(values) / len(values)
    if all(v == values[0] for v in values):
        return Interval(
            point=point,
            lo=values[0],
            hi=values[0],
            confidence=confidence,
            method="bootstrap",
            degenerate=True,
        )

    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples)
    )
    tail = (1 - confidence) / 2
    low_index = int(tail * resamples)
    high_index = min(resamples - 1, int((1 - tail) * resamples))
    return Interval(
        point=point,
        lo=means[low_index],
        hi=means[high_index],
        confidence=confidence,
        method="bootstrap",
    )


# --- how much a larger K can buy ---------------------------------------------


def design_effect(runs: int, correlation: float) -> float:
    """`1 + (runs - 1) * rho` — the variance penalty for repeating one fixture.

    K runs of one fixture are not K independent observations of the corpus. They
    are a cluster, and `rho` is how much a run tells you that the fixture's
    other runs did not. At `rho = 0` the runs are independent and K buys the
    full 1/K. At `rho = 1` a fixture's outcome is fixed and K buys nothing at
    all — which is what every fixture measured so far has looked like: 34/34 in
    the pilot, 0/10 on `TS-0001`.
    """
    if runs < 1:
        raise IntervalError(f"runs must be positive, got {runs}")
    if not 0 <= correlation <= 1:
        raise IntervalError(f"correlation must be in [0, 1], got {correlation}")
    return 1 + (runs - 1) * correlation


def effective_trials(fixtures: int, runs: int, correlation: float) -> float:
    """Independent-observation equivalent of `fixtures` x `runs` clustered runs.

    This is the arithmetic the K decision rests on. Because the divisor grows
    with K at almost the same rate as the numerator once `rho` is high, the
    curve flattens fast: at `rho = 0.8` and 15 fixtures, going from K=5 to K=10
    moves effective trials from 17.9 to 18.3. Cost doubles; the interval does
    not measurably move. Corpus size, by contrast, multiplies this number
    linearly — which is why the v1 cap of 15 fixtures, not K, is the binding
    constraint on every published width.
    """
    if fixtures < 1:
        raise IntervalError(f"fixtures must be positive, got {fixtures}")
    return fixtures * runs / design_effect(runs, correlation)


def smallest_trials(
    target_half_width: float,
    rate: float = 0.5,
    max_trials: int = 1_000,
    confidence: float = DEFAULT_CONFIDENCE,
) -> int | None:
    """Fewest trials whose exact interval is no wider than `target_half_width`.

    `rate` defaults to 0.5, the worst case: a proportion's interval is widest in
    the middle, so an answer here holds everywhere. Returns None when
    `max_trials` is not enough, rather than a number that quietly is not one.
    """
    if not 0 < target_half_width < 1:
        raise IntervalError(f"target half-width must be in (0, 1), got {target_half_width}")
    for trials in range(1, max_trials + 1):
        if clopper_pearson(round(rate * trials), trials, confidence).half_width <= (
            target_half_width
        ):
            return trials
    return None
