"""The published numbers, re-derived from the artifacts they were published from.

Every other test in this suite runs against a synthetic fixture built in a
tmpdir. That proves the machinery is right; it does not prove the numbers this
project *prints* are still what the machinery produces. Those numbers live in
three prose files — `results/precision/README.md`, the fixture's `NOTES.md`, and
`fixture.yaml`'s own note — and prose does not fail a test run.

The gap this closes is specific. `TS-0001`'s answer key gained a fourth
distractor on 2026-08-01 without a single run being re-run, purely by relabelling
findings that were already on disk. That is a cheap and repeatable move, and it
is exactly the move that can silently change a published tally: rename a
distractor `kind` in `fixture.yaml`, or drop a label, and the shipped label file
and the shipped answer key stop agreeing. `assay.eval.precision` would catch it
the moment a human re-ran the CLI by hand — and nothing made anyone do that.

So this file scores the shipped transcript against the shipped labels and the
shipped answer key, and asserts the results equal what the prose claims. It
makes no model calls; the transcript is on disk.

The bite tallies are asserted *separately for each attributor and deliberately
differ*: proximity reports `1, 0, 0, 5` and labels report `0, 1, 0, 7`. That is
not a discrepancy to be reconciled — it is this fixture's headline result, that
where a finding points and what it argues are different questions. A future
change that quietly made them agree would be erasing the finding, so both are
pinned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from assay.corpus import Fixture, load_fixture
from assay.corpus.locality import classify
from assay.eval.precision import load_labels, score

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "corpus" / "ts" / "TS-0001-reservation-double-release"
TRANSCRIPT = REPO_ROOT / "results" / "locality" / "TS-0001-20260731T170244Z.json"
FINDING_LABELS = (
    REPO_ROOT / "results" / "precision" / "TS-0001-20260731T170244Z.finding-labels.json"
)
DETECTION_LABELS = (
    REPO_ROOT / "results" / "locality" / "TS-0001-20260731T170244Z.labels.json"
)

#: `results/precision/README.md`, "Runs on file". Labels attribute by what a
#: finding argues.
PUBLISHED_BITES_BY_LABEL = {
    "distractor:stale-batch-timestamp": 0,
    "distractor:logged-and-continued-error": 1,
    "distractor:redundant-empty-batch-return": 0,
    "distractor:uncounted-settled-row": 7,
}

#: The same batch through `assay.corpus.locality`, which attributes by where a
#: finding points. Two of the seven uncounted-settled-row findings span the
#: defect's range as well and tie back onto it — see `attribute`.
PUBLISHED_BITES_BY_PROXIMITY = {
    "distractor-1:stale-batch-timestamp": 1,
    "distractor-2:logged-and-continued-error": 0,
    "distractor-3:redundant-empty-batch-return": 0,
    "distractor-4:uncounted-settled-row": 5,
}


@pytest.fixture(scope="module")
def fixture() -> Fixture:
    return load_fixture(FIXTURE_ROOT)


@pytest.fixture(scope="module")
def transcript() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
    return loaded


def test_the_shipped_labels_still_match_the_shipped_answer_key(fixture: Fixture) -> None:
    """A renamed or dropped distractor `kind` must fail here, not in a sweep.

    `load_labels` validates every label against the fixture's own answer key, so
    this is the assertion that binds the two shipped files together.
    """
    labels = load_labels(FINDING_LABELS, fixture)
    assert len(labels) == 29


def test_precision_is_still_zero_over_twenty_nine_findings(
    fixture: Fixture, transcript: dict[str, Any]
) -> None:
    labels = load_labels(FINDING_LABELS, fixture)
    report = score(fixture, transcript, labels)

    assert report.total_findings == 29
    assert report.pooled_precision is not None
    assert report.pooled_precision.point == 0.0
    assert report.scored == 10
    # Not one true positive in the batch: the 10/10 the proximity matcher scored
    # was 29 false positives. This is the fixture's whole point.
    assert sum(r.true_positives for r in report.runs) == 0


def test_the_batch_is_still_degenerate(fixture: Fixture, transcript: dict[str, Any]) -> None:
    """The stated trigger to re-measure K is "the first batch that is not constant".

    That trigger is only enforced while this batch *is* constant. If this ever
    fails, K is no longer settled on the argument PLAN records.
    """
    labels = load_labels(FINDING_LABELS, fixture)
    report = score(fixture, transcript, labels)
    assert report.precision_is_degenerate


def test_label_bite_tally_matches_the_published_table(
    fixture: Fixture, transcript: dict[str, Any]
) -> None:
    labels = load_labels(FINDING_LABELS, fixture)
    report = score(fixture, transcript, labels)
    assert report.distractor_bites == PUBLISHED_BITES_BY_LABEL


def test_locality_verdict_is_still_survived_and_settled(
    fixture: Fixture, transcript: dict[str, Any]
) -> None:
    """`cross_file` at 0/10, hand-labelled over the matcher.

    The manifest records `verified: true` on the strength of this verdict, so a
    change that moved it would leave the answer key asserting a tag the evidence
    no longer supports.
    """
    detection = json.loads(DETECTION_LABELS.read_text(encoding="utf-8"))
    report = classify(fixture, transcript, labels=detection)

    (verdict,) = [v for v in report.verdicts if v.defect_id == "TS-0001-d1"]
    assert verdict.status.name.lower().startswith("survived")
    assert verdict.hits == 0
    assert verdict.scored == 10
    assert verdict.hand_labelled == 10
    assert verdict.claimed.value == "cross_file"


def test_proximity_bite_tally_still_disagrees_with_the_labels(
    fixture: Fixture, transcript: dict[str, Any]
) -> None:
    """Pinned because the disagreement is the result, not a defect.

    `locality.py`'s `attribute` docstring claims it files 5 of the 7
    uncounted-settled-row bites and leaves 2 on the defect through the
    defect-favouring tiebreak. That is a claim about this transcript, and this
    is what checks it.
    """
    detection = json.loads(DETECTION_LABELS.read_text(encoding="utf-8"))
    report = classify(fixture, transcript, labels=detection)

    assert report.distractor_bites == PUBLISHED_BITES_BY_PROXIMITY

    by_label = PUBLISHED_BITES_BY_LABEL["distractor:uncounted-settled-row"]
    by_proximity = PUBLISHED_BITES_BY_PROXIMITY["distractor-4:uncounted-settled-row"]
    assert by_proximity == 5 and by_label == 7
