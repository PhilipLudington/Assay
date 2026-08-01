"""Precision from hand labels, and the ways a label file can lie by omission.

The rejection tests carry most of the weight. Precision is a ratio whose
denominator is "every finding the reviewer made", so anything that quietly drops
a finding raises the score — an unlabelled finding, a label written against a
renumbered run, a typo in a defect id. Each of those is a way to publish a
better number than the runs earned, so each is refused rather than tolerated.

Everything here runs offline against synthetic transcripts.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from assay.corpus import load_fixture
from assay.eval.precision import (
    PrecisionError,
    finding_key,
    k_table,
    load_labels,
    score,
    valid_labels,
)

SHIPMENTS_TS = """\
export interface Shipment {
  id: string;
  weightKg: number;
}

export function totalWeight(shipments: Shipment[]): number {
  let total = 0;
  for (let i = 0; i <= shipments.length; i += 1) {
    total += shipments[i].weightKg;
  }
  return total;
}
"""

CHANGE_PATCH = """\
diff --git a/src/shipments.ts b/src/shipments.ts
--- a/src/shipments.ts
+++ b/src/shipments.ts
@@ -5,7 +5,7 @@

 export function totalWeight(shipments: Shipment[]): number {
   let total = 0;
-  for (let i = 0; i < shipments.length; i += 1) {
+  for (let i = 0; i <= shipments.length; i += 1) {
     total += shipments[i].weightKg;
   }
   return total;
"""

MANIFEST = """\
id: TS-0001
title: Off-by-one in the shipment weight total
language: typescript
diff: change.patch
defects:
  - id: TS-0001-d1
    class: boundary-error
    severity: high
    locality:
      tier: local
    location:
      file: src/shipments.ts
      lines: [8, 8]
    description: >
      The loop bound reads one past the end of the array, so the final
      iteration dereferences undefined.
distractors:
  - kind: naming-inconsistency
    location:
      file: src/shipments.ts
      lines: [2, 3]
    note: Plausible style complaint about interface field naming; not a defect.
"""


@pytest.fixture
def fixture(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "TS-0001"
    (root / "repo" / "src").mkdir(parents=True)
    (root / "repo" / "src" / "shipments.ts").write_text(SHIPMENTS_TS, encoding="utf-8")
    (root / "fixture.yaml").write_text(textwrap.dedent(MANIFEST), encoding="utf-8")
    (root / "change.patch").write_text(CHANGE_PATCH, encoding="utf-8")
    (root / "NOTES.md").write_text("Provenance: hand-authored for tests.\n", encoding="utf-8")
    return load_fixture(root)


def a_finding(message: str = "something is wrong") -> dict[str, Any]:
    return {
        "file": "src/shipments.ts",
        "start_line": 8,
        "end_line": 8,
        "claimed_class": "boundary-error",
        "severity": "high",
        "confidence": 0.8,
        "message": message,
    }


def transcript(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"fixture": "TS-0001", "model": "claude-opus-5", "stamp": "2026", "runs": runs}


def run(index: int, findings: int, **extra: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "run_index": index,
        "findings": [a_finding() for _ in range(findings)],
        "parse_error": None,
        "cost_usd": 0.04,
    }
    record.update(extra)
    return record


def labels_for(counts: dict[int, int], label: str = "other") -> dict[str, str]:
    return {
        finding_key(index, offset): label
        for index, count in counts.items()
        for offset in range(count)
    }


# --- what a label file is allowed to say -------------------------------------


def test_valid_labels_are_exactly_what_the_answer_key_can_justify(fixture) -> None:  # type: ignore[no-untyped-def]
    assert valid_labels(fixture) == {
        "other",
        "defect:TS-0001-d1",
        "distractor:naming-inconsistency",
    }


def test_a_typoed_defect_id_is_refused(tmp_path: Path, fixture) -> None:  # type: ignore[no-untyped-def]
    """The failure mode a loose parser hides.

    `defect:TS-0001-dl` is one keystroke from the real id. Anything that treats
    an unrecognised label as a false positive turns that into a precision of
    zero that reads exactly like a measurement.
    """
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"0:0": "defect:TS-0001-dl"}), encoding="utf-8")

    with pytest.raises(PrecisionError, match="not one of"):
        load_labels(path, fixture)


def test_an_undeclared_distractor_kind_is_refused(tmp_path: Path, fixture) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"0:0": "distractor:invented"}), encoding="utf-8")

    with pytest.raises(PrecisionError, match="not one of"):
        load_labels(path, fixture)


def test_commentary_keys_are_skipped_not_scored(tmp_path: Path, fixture) -> None:  # type: ignore[no-untyped-def]
    # The reasoning behind a hand judgement has to live beside the labels it
    # explains, so the format has to tolerate prose.
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps({"_why": ["a paragraph", "of reasoning"], "0:0": "other"}), encoding="utf-8"
    )

    assert load_labels(path, fixture) == {"0:0": "other"}


def test_a_non_string_label_is_refused(tmp_path: Path, fixture) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"0:0": True}), encoding="utf-8")

    with pytest.raises(PrecisionError, match="not a string"):
        load_labels(path, fixture)


def test_an_empty_or_malformed_label_file_is_refused(tmp_path: Path, fixture) -> None:  # type: ignore[no-untyped-def]
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"_only": "commentary"}), encoding="utf-8")
    with pytest.raises(PrecisionError, match="no labels"):
        load_labels(empty, fixture)

    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps(["0:0", "other"]), encoding="utf-8")
    with pytest.raises(PrecisionError, match="must be a JSON object"):
        load_labels(wrong, fixture)


# --- refusing to score an incomplete batch -----------------------------------


def test_an_unlabelled_finding_is_refused(fixture) -> None:  # type: ignore[no-untyped-def]
    """Scoring over "whatever is labelled" would raise precision for free."""
    batch = transcript([run(0, 3)])

    with pytest.raises(PrecisionError, match="carry no label"):
        score(fixture, batch, labels_for({0: 2}))


def test_a_label_for_a_finding_that_does_not_exist_is_refused(fixture) -> None:  # type: ignore[no-untyped-def]
    # Points at the wrong transcript, or at a run that has since been
    # renumbered. Either way the score would be about something else.
    batch = transcript([run(0, 2)])

    with pytest.raises(PrecisionError, match="does not have"):
        score(fixture, batch, labels_for({0: 2, 7: 1}))


def test_labels_are_keyed_by_recorded_run_index_not_by_position(fixture) -> None:  # type: ignore[no-untyped-def]
    """A failed run leaves a gap, and the gap must not shift every later label.

    `run_index` is recorded precisely so a dead run can stay in the transcript
    without renumbering the ones after it.
    """
    batch = transcript([run(0, 0, failed=True), run(1, 1), run(2, 1)])

    report = score(fixture, batch, labels_for({1: 1, 2: 1}))

    assert [r.run_index for r in report.runs] == [1, 2]


# --- the score itself --------------------------------------------------------


def test_precision_counts_only_seeded_defects_as_true_positives(fixture) -> None:  # type: ignore[no-untyped-def]
    batch = transcript([run(0, 4)])
    labels = {
        "0:0": "defect:TS-0001-d1",
        "0:1": "distractor:naming-inconsistency",
        "0:2": "other",
        "0:3": "other",
    }

    report = score(fixture, batch, labels)

    assert report.runs[0].precision == 0.25
    assert report.pooled_precision is not None
    assert report.pooled_precision.point == 0.25


def test_a_distractor_bite_and_an_unseeded_finding_both_cost_precision(fixture) -> None:  # type: ignore[no-untyped-def]
    """DESIGN: distractor hits count against precision, as intended.

    An unseeded finding costs the same. A corpus cannot tell "found a bug we did
    not seed" from "wrong" without a second answer key, and pretending otherwise
    would let a reviewer be credited for output nobody adjudicated.
    """
    batch = transcript([run(0, 2)])

    report = score(
        fixture,
        batch,
        {"0:0": "distractor:naming-inconsistency", "0:1": "other"},
    )

    assert report.runs[0].precision == 0.0


def test_a_run_that_reported_nothing_has_no_precision(fixture) -> None:  # type: ignore[no-untyped-def]
    """Silence is not a precision of 0.0, and not a 1.0 either.

    It stays in the recall denominator, where "found nothing" is a real answer.
    """
    batch = transcript([run(0, 2), run(1, 0)])

    report = score(fixture, batch, {"0:0": "defect:TS-0001-d1", "0:1": "other"})

    assert report.runs[1].precision is None
    assert report.silent_runs == 1
    # The mean is over the one run that had a precision at all.
    assert report.mean_precision is not None
    assert report.mean_precision.point == 0.5
    # ...but recall is over both runs: run 1 genuinely failed to find it.
    assert report.recall["TS-0001-d1"].point == 0.5


def test_a_batch_in_which_nobody_reported_anything_has_no_precision(fixture) -> None:  # type: ignore[no-untyped-def]
    report = score(fixture, transcript([run(0, 0), run(1, 0)]), {})

    assert report.mean_precision is None
    assert report.pooled_precision is None
    assert report.recall["TS-0001-d1"].point == 0.0
    assert not report.precision_is_degenerate


def test_a_distractor_bitten_twice_in_one_run_counts_once(fixture) -> None:  # type: ignore[no-untyped-def]
    # The tally answers "how many runs took this bait", which is what decides
    # whether the bait works. Two bites in one run is still one run.
    batch = transcript([run(0, 2)])

    report = score(
        fixture,
        batch,
        {
            "0:0": "distractor:naming-inconsistency",
            "0:1": "distractor:naming-inconsistency",
        },
    )

    assert report.distractor_bites["distractor:naming-inconsistency"] == 1


def test_a_defect_found_twice_in_one_run_counts_once_for_recall(fixture) -> None:  # type: ignore[no-untyped-def]
    batch = transcript([run(0, 2)])

    report = score(
        fixture, batch, {"0:0": "defect:TS-0001-d1", "0:1": "defect:TS-0001-d1"}
    )

    assert report.recall["TS-0001-d1"].point == 1.0
    # Both still count as true positives for precision — the reviewer made two
    # correct findings, and precision is over findings.
    assert report.runs[0].precision == 1.0


def test_failed_and_unparseable_runs_leave_the_score(fixture) -> None:  # type: ignore[no-untyped-def]
    """The three-tier split, applied to precision.

    An unparseable run's findings are unknown, not empty. Scoring it as a run
    that reported nothing would move both rates.
    """
    batch = transcript(
        [
            run(0, 1),
            run(1, 0, failed=True, error="boom"),
            run(2, 1, parse_error="no structured output"),
        ]
    )

    report = score(fixture, batch, {"0:0": "defect:TS-0001-d1"})

    assert (report.total_runs, report.failed, report.unparseable, report.scored) == (3, 1, 1, 1)
    assert report.recall["TS-0001-d1"].point == 1.0
    assert report.total_findings == 1


def test_a_constant_batch_is_flagged_degenerate(fixture) -> None:  # type: ignore[no-untyped-def]
    """`TS-0001`'s actual shape, and the reason K could not be settled on it."""
    batch = transcript([run(i, 3) for i in range(10)])

    report = score(fixture, batch, labels_for(dict.fromkeys(range(10), 3)))

    assert report.precision_is_degenerate
    assert report.mean_precision is not None
    assert report.mean_precision.half_width == 0.0
    # The exact interval on the pooled count is the one that can be quoted.
    assert report.pooled_precision is not None
    assert report.pooled_precision.half_width > 0.0


def test_a_varying_batch_is_not_flagged_degenerate(fixture) -> None:  # type: ignore[no-untyped-def]
    batch = transcript([run(0, 2), run(1, 2)])

    report = score(
        fixture,
        batch,
        {
            "0:0": "defect:TS-0001-d1",
            "0:1": "other",
            "1:0": "other",
            "1:1": "other",
        },
    )

    assert not report.precision_is_degenerate
    assert report.mean_precision is not None
    assert report.mean_precision.point == 0.25


def test_recall_at_the_boundary_is_not_reported_as_certain(fixture) -> None:  # type: ignore[no-untyped-def]
    """0/10 is `[0, 0.31]`, which is the whole argument against the bootstrap."""
    batch = transcript([run(i, 1) for i in range(10)])

    report = score(fixture, batch, labels_for(dict.fromkeys(range(10), 1)))

    interval = report.recall["TS-0001-d1"]
    assert interval.point == 0.0
    assert interval.hi == pytest.approx(0.3085, abs=5e-4)


# --- what K buys -------------------------------------------------------------


def test_more_runs_never_widen_the_corpus_interval() -> None:
    for correlation in (0.5, 0.8, 1.0):
        widths = [r.half_width for r in k_table(15) if r.correlation == correlation]
        assert widths == sorted(widths, reverse=True)


def test_perfectly_correlated_runs_make_k_irrelevant() -> None:
    """What 34/34 and 0/10 both look like: a fixture whose outcome is fixed."""
    widths = {r.half_width for r in k_table(15) if r.correlation == 1.0}
    assert len(widths) == 1


def test_the_curve_flattens_well_before_the_top_of_the_table() -> None:
    rows = {r.runs: r for r in k_table(15) if r.correlation == 0.8}
    # K=1 to K=5 buys something; K=5 to K=20, at four times the spend, does not.
    assert rows[1].half_width - rows[5].half_width > 0.015
    assert rows[5].half_width - rows[20].half_width < 0.010


def test_a_bigger_corpus_buys_what_a_bigger_k_cannot() -> None:
    small = {r.runs: r for r in k_table(15) if r.correlation == 0.8}
    large = {r.runs: r for r in k_table(45) if r.correlation == 0.8}
    assert small[5].half_width - large[5].half_width > 0.08
