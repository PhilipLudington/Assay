"""Precision over a stored batch, from hand labels rather than from proximity.

PLAN's last open Phase 1 task is "measure precision variance on `TS-0001` and
settle K", inherited from the Phase 0 gate. The runs for it already exist — the
ten single-shot runs taken for locality verification — but the 2026-07-31
measurement showed the proximity matcher cannot compute precision over them: it
scored the seeded defect found 10 times out of 10 and every one of those matches
was a false positive. So the input here is a **label per finding**, not a line
distance, and the module refuses to score a batch that is not fully labelled.

**What precision means here**, following DESIGN: a reviewer's findings that
matched some seeded defect, over all its findings. A distractor bite is a false
positive, as intended — that is what distractors are for. So is any other
finding: a plausible, real, unseeded bug still counts against precision, because
a corpus cannot distinguish "found a bug we did not seed" from "wrong" without a
second answer key. That is a known bias of a hand-authored corpus and it belongs
in the README rather than in a correction factor here.

**Two intervals, deliberately.**

- The *mean of per-run precisions* gets DESIGN's bootstrap. It is a mean of
  bounded reals, so that is the right estimator — and on every batch measured so
  far it collapses, because every batch has been constant. The report prints the
  collapse as a collapse.
- The *pooled* precision — true positives over all findings in the batch — gets
  an exact interval. It is a count out of a count, it is defined at 0, and it is
  the number that can honestly be quoted. On `TS-0001` it is 0 of 29, which is
  `[0.00, 0.12]` and not `0.00 ± 0.00`.

**A run that reported nothing has no precision**, and is dropped from the mean
rather than scored. Calling it 0.0 punishes silence and calling it 1.0 rewards
it; both are answers to a question the run did not participate in. It stays in
the recall denominator, where "found nothing" is a real and correct outcome.

Run it — free, no model calls::

    .venv/bin/python -m assay.eval.precision \\
        corpus/ts/TS-0001-reservation-double-release \\
        --from results/locality/TS-0001-20260731T170244Z.json \\
        --labels results/precision/TS-0001-20260731T170244Z.finding-labels.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.corpus.loader import Fixture, load_fixture
from assay.corpus.locality import partition_runs
from assay.eval.interval import (
    Interval,
    bootstrap_mean,
    clopper_pearson,
    effective_trials,
    smallest_trials,
)

#: A finding that is neither a seeded defect nor a declared distractor. Still a
#: false positive for scoring; named separately so a report can show how much of
#: a reviewer's output the answer key does not describe at all.
LABEL_OTHER = "other"
DEFECT_PREFIX = "defect:"
DISTRACTOR_PREFIX = "distractor:"

#: Candidate K values the report tabulates. Spans "one run" to "four times the
#: provisional K", which is enough to show the curve flattening.
K_CANDIDATES = (1, 3, 5, 10, 20)

#: Intra-fixture correlations the K table is evaluated at. 1.0 is what every
#: batch measured so far has actually looked like (34/34, then 0/10); 0.5 is a
#: deliberately generous assumption in favour of a larger K.
RHO_CANDIDATES = (0.5, 0.8, 1.0)


class PrecisionError(ValueError):
    """The batch cannot be scored in a state that means anything."""


# --- labels ------------------------------------------------------------------


def finding_key(run_index: int, finding_index: int) -> str:
    """The key a finding-label file uses for one finding of one run."""
    return f"{run_index}:{finding_index}"


def valid_labels(fixture: Fixture) -> set[str]:
    """Every label this fixture's answer key can justify.

    Validated against rather than parsed loosely, because a typo in a label is
    silent: `defect:TS-0001-dl` would score as an unrecognised string, and the
    natural fallback — treat what we do not recognise as a false positive —
    turns a fat finger into a precision of zero that looks like a result.
    """
    labels = {LABEL_OTHER}
    labels |= {f"{DEFECT_PREFIX}{d.id}" for d in fixture.defects}
    labels |= {f"{DISTRACTOR_PREFIX}{d.kind}" for d in fixture.distractors}
    return labels


def load_labels(path: Path, fixture: Fixture) -> dict[str, str]:
    """Reads a finding-label file, refusing anything the fixture cannot justify.

    Keys prefixed with `_` are commentary — a label file is where the reasoning
    behind a hand judgement lives, and that reasoning has to be readable next to
    the labels it explains rather than in a session transcript.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PrecisionError(f"{path}: label file must be a JSON object")

    permitted = valid_labels(fixture)
    labels: dict[str, str] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        if not isinstance(value, str):
            raise PrecisionError(f"{path}: label for {key!r} is not a string")
        if value not in permitted:
            raise PrecisionError(
                f"{path}: label {value!r} for {key!r} is not one of "
                f"{sorted(permitted)} — a mislabelled finding scores silently"
            )
        labels[key] = value
    if not labels:
        raise PrecisionError(f"{path}: no labels found")
    return labels


# --- scoring -----------------------------------------------------------------


@dataclass(frozen=True)
class RunScore:
    run_index: int
    findings: int
    true_positives: int
    distractor_bites: tuple[str, ...]
    other: int

    @property
    def precision(self) -> float | None:
        """None when the run reported nothing — silence has no precision."""
        return self.true_positives / self.findings if self.findings else None


@dataclass(frozen=True)
class PrecisionReport:
    fixture_id: str
    model: str
    stamp: str
    total_runs: int
    failed: int
    unparseable: int
    scored: int
    runs: tuple[RunScore, ...]
    #: DESIGN's specified interval over the per-run precisions. None when no run
    #: reported a finding at all.
    mean_precision: Interval | None
    #: True positives over every finding in the batch, with an exact interval.
    pooled_precision: Interval | None
    #: Per defect: runs that found it, out of scored runs, with an exact interval.
    recall: dict[str, Interval]
    distractor_bites: dict[str, int]
    total_findings: int

    @property
    def silent_runs(self) -> int:
        return sum(1 for r in self.runs if r.findings == 0)

    @property
    def precision_is_degenerate(self) -> bool:
        """Whether the per-run precisions were constant, collapsing the bootstrap.

        The single fact that decides whether this batch can settle K. It cannot
        if this is true — a constant sample reports ±0.00 at every K, and
        reading that as precision would choose K=1 off a measurement that
        measured nothing.
        """
        return self.mean_precision is not None and self.mean_precision.degenerate


def score(
    fixture: Fixture, transcript: dict[str, Any], labels: dict[str, str]
) -> PrecisionReport:
    """Scores a stored batch against hand labels. Makes no model calls.

    Every finding in every scored run must carry a label. A partially labelled
    batch is refused rather than scored over what happens to be present: the
    unlabelled findings would drop out of the denominator, and precision would
    rise for no reason but incomplete work.
    """
    runs = list(transcript.get("runs", []))
    billed, scored_runs = partition_runs(runs)

    defect_ids = [d.id for d in fixture.defects]
    bites: dict[str, int] = {f"{DISTRACTOR_PREFIX}{d.kind}": 0 for d in fixture.distractors}
    found: dict[str, int] = dict.fromkeys(defect_ids, 0)

    missing: list[str] = []
    scores: list[RunScore] = []
    for position, record in enumerate(scored_runs):
        index = int(record.get("run_index", position))
        findings = [f for f in record.get("findings", []) if isinstance(f, dict)]

        true_positives = 0
        bitten: list[str] = []
        other = 0
        run_found: set[str] = set()
        for offset in range(len(findings)):
            key = finding_key(index, offset)
            if key not in labels:
                missing.append(key)
                continue
            label = labels[key]
            if label.startswith(DEFECT_PREFIX):
                true_positives += 1
                run_found.add(label[len(DEFECT_PREFIX) :])
            elif label.startswith(DISTRACTOR_PREFIX):
                bitten.append(label)
            else:
                other += 1

        for name in set(bitten):
            bites[name] += 1
        for defect_id in run_found:
            found[defect_id] += 1
        scores.append(
            RunScore(
                run_index=index,
                findings=len(findings),
                true_positives=true_positives,
                distractor_bites=tuple(sorted(set(bitten))),
                other=other,
            )
        )

    if missing:
        raise PrecisionError(
            f"{len(missing)} finding(s) carry no label: {missing[:8]}"
            + (" ..." if len(missing) > 8 else "")
            + " — an unlabelled finding leaves the denominator and inflates precision"
        )

    extra = set(labels) - {
        finding_key(s.run_index, offset) for s in scores for offset in range(s.findings)
    }
    if extra:
        # Points at the wrong transcript, a renumbered run, or a label written
        # for a finding that no longer exists. All three make the score fiction.
        raise PrecisionError(
            f"{len(extra)} label(s) name findings this batch does not have: {sorted(extra)[:8]}"
        )

    per_run = [s.precision for s in scores if s.precision is not None]
    total_findings = sum(s.findings for s in scores)
    total_true = sum(s.true_positives for s in scores)

    n = len(scores)
    return PrecisionReport(
        fixture_id=fixture.id,
        model=str(transcript.get("model", "")),
        stamp=str(transcript.get("stamp", "")),
        total_runs=len(runs),
        failed=len(runs) - len(billed),
        unparseable=len(billed) - len(scored_runs),
        scored=n,
        runs=tuple(scores),
        mean_precision=bootstrap_mean(per_run) if per_run else None,
        pooled_precision=(
            clopper_pearson(total_true, total_findings) if total_findings else None
        ),
        recall={
            defect_id: clopper_pearson(found[defect_id], n) for defect_id in defect_ids
        }
        if n
        else {},
        distractor_bites=bites,
        total_findings=total_findings,
    )


# --- what K can buy ----------------------------------------------------------


@dataclass(frozen=True)
class KRow:
    runs: int
    correlation: float
    effective: float
    half_width: float


def k_table(fixtures: int) -> list[KRow]:
    """Corpus-level interval half-width against K, at several clustering levels.

    This is what settles K, because the observed variance cannot. K runs of one
    fixture are a cluster, not K independent observations of the corpus, so the
    information they add is divided by `1 + (K-1)*rho`. At the correlations
    actually observed the curve flattens almost immediately, while the fixture
    count multiplies the same quantity linearly.
    """
    rows: list[KRow] = []
    for correlation in RHO_CANDIDATES:
        for runs in K_CANDIDATES:
            effective = effective_trials(fixtures, runs, correlation)
            trials = max(1, round(effective))
            # Worst case, at a rate of one half — an answer here holds for any
            # rate the sweep might actually report.
            interval = clopper_pearson(round(trials / 2), trials)
            rows.append(KRow(runs, correlation, effective, interval.half_width))
    return rows


# --- reporting ---------------------------------------------------------------


def print_report(report: PrecisionReport, fixtures: int) -> None:
    print(f"\nPrecision — {report.fixture_id}  ({report.stamp[:8] or 'unstamped'})")
    print("─" * 64)
    print(f"{report.total_runs:>4} run(s) on file")
    print(f"{report.failed:>4} failed outright — excluded everywhere")
    print(f"{report.unparseable:>4} unparseable — findings unknown, not empty")
    print(f"{report.scored:>4} scored, {report.total_findings} finding(s) labelled")
    if report.silent_runs:
        print(
            f"{report.silent_runs:>4} scored run(s) reported nothing — no precision, "
            "dropped from the mean"
        )

    print("\nPer run")
    print("─" * 64)
    for run in report.runs:
        precision = "n/a" if run.precision is None else f"{run.precision:.2f}"
        bites = f"  bit {', '.join(run.distractor_bites)}" if run.distractor_bites else ""
        print(
            f"  run {run.run_index:>2}: {run.findings} finding(s)  "
            f"tp={run.true_positives}  other={run.other}  precision={precision}{bites}"
        )

    print("\nPrecision")
    print("─" * 64)
    if report.mean_precision is None:
        print("  no run reported a finding; precision is undefined for this batch")
    else:
        print(f"  mean of per-run precisions (bootstrap): {report.mean_precision}")
        if report.precision_is_degenerate:
            print(
                "    ⚠ DEGENERATE — every run scored the same, so the bootstrap\n"
                "      collapses to a point at *every* K. This width is an artifact\n"
                "      of the estimator, not a measurement. K cannot be settled here."
            )
    if report.pooled_precision is not None:
        true_positives = sum(r.true_positives for r in report.runs)
        print(
            f"  pooled, exact: {report.pooled_precision}  "
            f"({true_positives}/{report.total_findings} findings)"
        )

    print("\nRecall")
    print("─" * 64)
    for defect_id, interval in report.recall.items():
        found = round(interval.point * report.scored)
        print(f"  {defect_id}: {found}/{report.scored} runs  {interval}")

    print("\nDistractor bites (by label, not by proximity)")
    print("─" * 64)
    if not report.distractor_bites:
        print("  none declared")
    for name, count in sorted(report.distractor_bites.items()):
        note = "  ← never bitten; it is not doing its job" if count == 0 else ""
        print(f"  {name}: {count}/{report.scored}{note}")

    print(f"\nWhat K buys at {fixtures} fixtures")
    print("─" * 64)
    print("  Corpus-level half-width, worst case, by intra-fixture correlation.")
    print("  rho=1.0 is what every batch measured so far looks like.\n")
    print("   rho    K   effective n   half-width")
    for row in k_table(fixtures):
        print(
            f"  {row.correlation:>4.1f}  {row.runs:>3}   {row.effective:>11.1f}   "
            f"±{row.half_width:.3f}"
        )
    needed = smallest_trials(0.15)
    print(
        f"\n  For reference, ±0.15 needs {needed} independent observations — more than "
        f"{fixtures} fixtures\n  can supply at any K. Corpus size, not K, is the binding "
        "constraint."
    )


# --- cli ---------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score a stored batch's precision from hand labels."
    )
    parser.add_argument("fixture", type=Path, help="fixture root (the dir holding repo/)")
    parser.add_argument(
        "--from",
        dest="from_transcript",
        type=Path,
        required=True,
        help="a stored run transcript. Scoring makes no model calls.",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        required=True,
        help=(
            "JSON map of '<run_index>:<finding_index>' -> "
            "'defect:<id>' | 'distractor:<kind>' | 'other'"
        ),
    )
    parser.add_argument(
        "--fixtures",
        type=int,
        default=15,
        help="corpus size the K table is computed for (v1 caps it at 15)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = load_fixture(args.fixture)
    transcript = json.loads(args.from_transcript.read_text(encoding="utf-8"))

    # Scoring is free, which makes it easy to point at the wrong pair. A batch
    # scored against another fixture's answer key produces a full, plausible
    # report about nothing.
    recorded = transcript.get("fixture")
    if recorded and recorded != fixture.id:
        raise PrecisionError(
            f"{args.from_transcript} holds runs for {recorded}, not {fixture.id}"
        )

    report = score(fixture, transcript, load_labels(args.labels, fixture))
    print_report(report, args.fixtures)
    # Non-zero when the batch cannot settle K, so a caller cannot mistake a
    # collapsed interval for a measurement.
    return 1 if report.precision_is_degenerate else 0


if __name__ == "__main__":
    sys.exit(main())
