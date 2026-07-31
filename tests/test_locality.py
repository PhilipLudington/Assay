"""Locality verification: the matcher, and the rules that read a verdict from it.

Everything here runs without an API key. That is the point of the split — the
expensive half is one run of a reviewer, and every judgement made about that run
is re-derivable from the stored transcript for free, so it can be tested rather
than trusted.

The heaviest tests are the ones about what a *quiet* run means. A defect nobody
found does not prove the tag is `cross_file`; it fails to refute it. Getting
that backwards would let a single run bless a tag that the headline result is
then broken out by.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from assay.corpus import Locality, load_fixture
from assay.corpus.locality import (
    MIN_RUNS_TO_VERIFY,
    LocalityError,
    Verdict,
    attribute,
    classify,
    extract_findings,
    ground_truth,
    normalise_path,
    review_floor,
    run_with_retries,
)
from assay.cost import UnknownModelError, cost_usd, price_for

# Post-change state. Line 8 carries the seeded defect; lines 2-3 carry a
# distractor five lines away, which is what makes nearest-wins attribution
# load-bearing rather than decorative.
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

# Never touched by the diff, so anything located here is structurally cross_file.
HELPERS_TS = """\
export function round2(value: number): number {
  return Math.round(value * 100) / 100;
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


def manifest(tier: str = "cross_file", defect_file: str = "src/shipments.ts") -> str:
    lines = "[8, 8]" if defect_file == "src/shipments.ts" else "[2, 2]"
    return f"""\
id: TS-0001
title: Off-by-one in the shipment weight total
language: typescript
diff: change.patch
defects:
  - id: TS-0001-d1
    class: boundary-error
    severity: high
    locality:
      tier: {tier}
    location:
      file: {defect_file}
      lines: {lines}
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


def build(root: Path, *, text: str | None = None) -> Path:
    src = root / "repo" / "src"
    src.mkdir(parents=True)
    (src / "shipments.ts").write_text(SHIPMENTS_TS, encoding="utf-8")
    (src / "helpers.ts").write_text(HELPERS_TS, encoding="utf-8")
    (root / "fixture.yaml").write_text(
        textwrap.dedent(text if text is not None else manifest()), encoding="utf-8"
    )
    (root / "change.patch").write_text(CHANGE_PATCH, encoding="utf-8")
    (root / "NOTES.md").write_text("Provenance: hand-authored for locality tests.\n", "utf-8")
    return root


def finding(file: str, start: int, end: int, message: str = "something is wrong here") -> dict:
    return {
        "file": file,
        "start_line": start,
        "end_line": end,
        "claimed_class": "boundary-error",
        "severity": "high",
        "confidence": 0.8,
        "message": message,
    }


def transcript(runs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "measurement": "locality-verification",
        "fixture": "TS-0001",
        "model": "claude-opus-5",
        "effort": "high",
        "stamp": "20260731T120000Z",
        "prompt_sha256": "deadbeefdeadbeef",
        "runs": runs,
    }
    base.update(extra)
    return base


def clean_runs(count: int, findings_per_run: list[list[dict]] | None = None) -> list[dict]:
    out = []
    for index in range(count):
        payload = findings_per_run[index] if findings_per_run else []
        out.append(
            {
                "run_index": index,
                "findings": payload,
                "parse_error": None,
                "cost_usd": 0.05,
                "usage": {"input_tokens": 100, "output_tokens": 10},
            }
        )
    return out


# --- the review-context floor ------------------------------------------------


def test_floor_is_the_diff_plus_every_touched_file_whole(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    floor = review_floor(fixture)

    assert "for (let i = 0; i <= shipments.length" in floor
    assert "--- src/shipments.ts ---" in floor
    # The whole file, not just the hunk: line 12's `return total;` sits outside
    # the diff's context and must still be present.
    assert "export interface Shipment" in floor
    # Untouched files stay out. A floor that leaked them would make every
    # cross_file defect trivially reachable and the tools question unanswerable.
    assert "round2" not in floor


def test_floor_is_byte_stable(tmp_path: Path) -> None:
    """Phase 2's contract test asserts both reviewers get identical floors.

    That assertion is only worth something if the floor is deterministic, so the
    property is pinned here rather than assumed there.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    assert review_floor(fixture) == review_floor(fixture)


def test_floor_refuses_a_tree_that_lost_a_touched_file(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    (fixture.repo / "src" / "shipments.ts").unlink()

    with pytest.raises(LocalityError, match="missing file"):
        review_floor(fixture)


# --- attribution -------------------------------------------------------------


def test_a_finding_on_the_defect_attributes_to_the_defect(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, distance = attribute(finding("src/shipments.ts", 8, 8), items, 10)

    assert target is not None and target.id == "TS-0001-d1"
    assert distance == 0


def test_the_nearer_distractor_wins_over_the_defect(tmp_path: Path) -> None:
    """The reason this module does not use a plain proximity window.

    A finding at line 5 is 3 lines from the defect and 2 from the distractor.
    Under a ±15 window both match and the defect would be reported found —
    scoring a distractor bite as a detection, which is exactly how a real
    `cross_file` tag gets refuted by a reviewer that never saw the evidence.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, _ = attribute(finding("src/shipments.ts", 5, 5), items, 15)

    assert target is not None and target.id.startswith("distractor-1")


def test_a_tie_resolves_to_the_defect(tmp_path: Path) -> None:
    """Deliberate bias, and it points away from the failure being hunted.

    An over-counted detection can only refute a `cross_file` claim. A missed one
    can let a false claim stand, and a false `cross_file` tag produces a
    confidently wrong headline rather than a noisy one.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    # Range 5-6: two lines below the defect at 8, two above the distractor at 3.
    target, distance = attribute(finding("src/shipments.ts", 5, 6), items, 10)

    assert target is not None and target.id == "TS-0001-d1"
    assert distance == 2


def test_a_finding_outside_the_window_attributes_to_nothing(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, distance = attribute(finding("src/shipments.ts", 40, 40), items, 10)

    assert target is None
    # The distance still comes back, so a near-miss is visible in the printout
    # rather than looking the same as a finding in an unrelated file.
    assert distance == 32


def test_a_finding_in_another_file_attributes_to_nothing(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, distance = attribute(finding("src/helpers.ts", 8, 8), items, 10)

    assert target is None and distance is None


def test_a_backwards_line_range_is_a_formatting_slip_not_a_new_observation(
    tmp_path: Path,
) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, _ = attribute(finding("src/shipments.ts", 9, 7), items, 10)

    assert target is not None and target.id == "TS-0001-d1"


@pytest.mark.parametrize(
    "cited", ["src/shipments.ts", "./src/shipments.ts", "/src/shipments.ts"]
)
def test_path_spellings_a_reviewer_actually_emits_all_match(tmp_path: Path, cited: str) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, _ = attribute(finding(cited, 8, 8), items, 10)

    assert target is not None and target.id == "TS-0001-d1"


def test_normalise_path_keeps_a_leading_dot_directory() -> None:
    """`lstrip("./")` strips a character set and would eat this."""
    assert normalise_path("./.config/x.ts") == ".config/x.ts"


def test_a_non_integer_line_number_attributes_to_nothing(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    items = ground_truth(fixture)

    target, distance = attribute(
        {"file": "src/shipments.ts", "start_line": "eight", "end_line": "eight"}, items, 10
    )

    assert target is None and distance is None


# --- verdicts ----------------------------------------------------------------


def test_a_found_cross_file_defect_is_refuted(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(10, [[finding("src/shipments.ts", 8, 8)] for _ in range(10)])

    report = classify(fixture, transcript(runs))

    verdict = report.verdicts[0]
    assert verdict.status is Verdict.REFUTED
    assert verdict.resolved is Locality.LOCAL  # the diff's shape bounds it
    assert not report.settled


def test_an_unfound_cross_file_defect_survives_once_there_are_enough_runs(
    tmp_path: Path,
) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    report = classify(fixture, transcript(clean_runs(MIN_RUNS_TO_VERIFY)))

    verdict = report.verdicts[0]
    assert verdict.status is Verdict.SURVIVED
    assert verdict.resolved is Locality.CROSS_FILE
    assert report.settled
    assert f"0/{MIN_RUNS_TO_VERIFY} single-shot runs found it" in verdict.evidence
    assert "claude-opus-5" in verdict.evidence


def test_too_few_quiet_runs_is_underpowered_not_proof(tmp_path: Path) -> None:
    """A quiet run fails to refute a tag; it does not establish one.

    Treating three silent runs as verification is how an unverified tag reaches
    a published table that is broken out by locality.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    report = classify(fixture, transcript(clean_runs(MIN_RUNS_TO_VERIFY - 1)))

    assert report.verdicts[0].status is Verdict.UNDERPOWERED
    assert report.verdicts[0].resolved is None
    assert not report.settled


def test_a_non_cross_file_claim_is_consistent_whatever_the_runs_show(tmp_path: Path) -> None:
    """This measurement refutes `cross_file` and nothing else.

    The floor holds both the hunks and the whole touched file, so a run that
    finds the defect cannot distinguish `local` from `touched_file` — that
    distinction is structural and the loader already bounds it.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001", text=manifest(tier="local")))
    runs = clean_runs(3, [[finding("src/shipments.ts", 8, 8)], [], []])

    report = classify(fixture, transcript(runs))

    verdict = report.verdicts[0]
    assert verdict.status is Verdict.CONSISTENT
    assert verdict.resolved is Locality.LOCAL
    assert report.settled


def test_finding_a_defect_in_a_file_the_diff_never_showed_is_a_conflict(
    tmp_path: Path,
) -> None:
    """Reported, never resolved. Our matcher is the more likely culprit."""
    fixture = load_fixture(
        build(tmp_path / "TS-0001", text=manifest(defect_file="src/helpers.ts"))
    )
    runs = clean_runs(10, [[finding("src/helpers.ts", 2, 2)] for _ in range(10)])

    report = classify(fixture, transcript(runs))

    assert report.verdicts[0].status is Verdict.CONFLICT
    assert report.verdicts[0].resolved is None
    assert not report.settled


def test_no_scoreable_runs_is_unrun(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    report = classify(fixture, transcript([]))

    assert report.verdicts[0].status is Verdict.UNRUN
    assert report.verdicts[0].detection_rate is None
    assert not report.settled


# --- saturation --------------------------------------------------------------


def test_a_defect_found_by_every_run_is_an_authoring_failure(tmp_path: Path) -> None:
    """A corpus at the recall ceiling cannot show whether tools help."""
    fixture = load_fixture(build(tmp_path / "TS-0001", text=manifest(tier="local")))
    runs = clean_runs(10, [[finding("src/shipments.ts", 8, 8)] for _ in range(10)])

    report = classify(fixture, transcript(runs))

    verdict = report.verdicts[0]
    assert verdict.detection_rate == 1.0
    assert verdict.saturated
    # Consistent on locality and still not settled — the fixture gets reworked.
    assert verdict.status is Verdict.CONSISTENT
    assert not report.settled


def test_a_defect_found_by_some_runs_is_not_saturated(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001", text=manifest(tier="local")))
    runs = clean_runs(4, [[finding("src/shipments.ts", 8, 8)], [], [], []])

    report = classify(fixture, transcript(runs))

    assert report.verdicts[0].detection_rate == 0.25
    assert not report.verdicts[0].saturated


# --- run accounting ----------------------------------------------------------


def test_an_unparseable_run_leaves_detection_but_stays_in_the_spend(tmp_path: Path) -> None:
    """Its finding list is unknown, not empty.

    Scoring it as "found nothing" would depress detection — and here that could
    turn a refutable `cross_file` claim into a surviving one. Dropping it from
    the spend would understate what the measurement cost.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[finding("src/shipments.ts", 8, 8)], [], []])
    runs[1]["parse_error"] = "structured output has no 'findings' key"
    runs[1]["findings"] = []

    report = classify(fixture, transcript(runs))

    assert report.scored == 2
    assert report.unparseable == 1
    assert report.verdicts[0].hits == 1
    assert report.verdicts[0].detection_rate == 0.5
    assert report.cost_usd == pytest.approx(0.15)


def test_a_failed_run_is_excluded_from_everything_including_spend(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2)
    runs.append({"run_index": 2, "failed": True, "error": "APIStatusError: 529"})

    report = classify(fixture, transcript(runs))

    assert (report.total_runs, report.failed, report.scored) == (3, 1, 2)
    assert report.cost_usd == pytest.approx(0.10)


# --- hand labels -------------------------------------------------------------


def test_a_hand_label_overrules_the_matcher_and_says_so(tmp_path: Path) -> None:
    """The whole tag rests on a matcher this module calls crude on purpose.

    A human has to be able to overrule it, and the verdict has to disclose that
    it was overruled — otherwise a labelled result and a matched one read the
    same.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    # The matcher sees nothing: this finding is nowhere near the defect.
    runs = clean_runs(10, [[finding("src/shipments.ts", 40, 40)]] + [[] for _ in range(9)])

    unlabelled = classify(fixture, transcript(runs))
    labelled = classify(fixture, transcript(runs), labels={"0:TS-0001-d1": True})

    assert unlabelled.verdicts[0].status is Verdict.SURVIVED
    assert unlabelled.verdicts[0].hand_labelled == 0
    assert labelled.verdicts[0].status is Verdict.REFUTED
    assert labelled.verdicts[0].hand_labelled == 1


def test_a_label_can_also_withdraw_a_match(tmp_path: Path) -> None:
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(
        MIN_RUNS_TO_VERIFY, [[finding("src/shipments.ts", 8, 8)]] + [[] for _ in range(9)]
    )

    report = classify(fixture, transcript(runs), labels={"0:TS-0001-d1": False})

    assert report.verdicts[0].hits == 0
    assert report.verdicts[0].status is Verdict.SURVIVED


# --- distractors -------------------------------------------------------------


def test_distractor_bites_are_counted(tmp_path: Path) -> None:
    """Bait nobody takes is a measurement too: precision against it says nothing."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[finding("src/shipments.ts", 2, 3)], [], []])

    report = classify(fixture, transcript(runs))

    assert list(report.distractor_bites.values()) == [1]
    assert report.verdicts[0].hits == 0


def test_a_run_that_flags_a_distractor_twice_counts_one_bite(tmp_path: Path) -> None:
    """Per-run incidence, not per-finding. Otherwise one chatty run dominates."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(
        1, [[finding("src/shipments.ts", 2, 2), finding("src/shipments.ts", 3, 3)]]
    )

    report = classify(fixture, transcript(runs))

    assert list(report.distractor_bites.values()) == [1]


# --- structured-output parsing ----------------------------------------------


def test_a_clean_empty_review_is_a_result_and_a_parse_failure_is_not() -> None:
    """The distinction the pilot lost: both produced `[]`, only one is an answer."""
    assert extract_findings({"findings": []}) == ([], None)
    assert extract_findings({}) == ([], "structured output has no 'findings' key")


@pytest.mark.parametrize(
    "payload",
    [None, "not an object", {"findings": "nope"}, {"findings": [{"ok": 1}, "bad"]}],
)
def test_malformed_structured_output_always_reports_why(payload: Any) -> None:
    findings, error = extract_findings(payload)

    assert findings == []
    assert error


# --- retry -------------------------------------------------------------------


def test_a_transient_failure_costs_an_attempt_not_the_run() -> None:
    """The pilot saw `Claude Code returned an error result` in ~1 run in 4."""
    attempts = {"n": 0}

    def flaky() -> dict:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("Claude Code returned an error result")
        return {"findings": []}

    record, error = run_with_retries(flaky, retries=1, label="run 0", sleep=lambda _: None)

    assert record == {"findings": []} and error is None
    assert attempts["n"] == 2


def test_retries_zero_means_exactly_one_attempt() -> None:
    attempts = {"n": 0}

    def always_fails() -> dict:
        attempts["n"] += 1
        raise RuntimeError("boom")

    run_with_retries(always_fails, retries=0, label="run 0", sleep=lambda _: None)

    assert attempts["n"] == 1


def test_an_exhausted_run_returns_its_error_rather_than_raising() -> None:
    """The caller records the dead run. A gap in the transcript would let a
    later reader mistake a shrunken n for the intended number of runs."""

    def always_fails() -> dict:
        raise RuntimeError("boom")

    record, error = run_with_retries(
        always_fails, retries=2, label="run 0", sleep=lambda _: None
    )

    assert record is None
    assert error is not None and "boom" in error


# --- cost --------------------------------------------------------------------


def test_cost_prices_cache_reads_and_writes_apart_from_fresh_input() -> None:
    # 1M fresh input at $5, 1M cache write at 1.25x, 1M cache read at 0.1x,
    # 1M output at $25.
    assert cost_usd("claude-opus-5", 1_000_000, 0) == pytest.approx(5.0)
    assert cost_usd("claude-opus-5", 0, 0, 1_000_000, 0) == pytest.approx(6.25)
    assert cost_usd("claude-opus-5", 0, 0, 0, 1_000_000) == pytest.approx(0.5)
    assert cost_usd("claude-opus-5", 0, 1_000_000) == pytest.approx(25.0)


def test_an_unpriced_model_raises_rather_than_costing_nothing() -> None:
    """A missing price that silently became zero would make a budget look met."""
    with pytest.raises(UnknownModelError):
        price_for("some-future-model")


# --- transcript round trip ---------------------------------------------------


def test_a_stored_transcript_rescores_identically(tmp_path: Path) -> None:
    """Re-scoring is free, which is the point: the matcher and the window can
    change later without re-spending, and historical runs stay comparable."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(10, [[finding("src/shipments.ts", 8, 8)] for _ in range(10)])
    path = tmp_path / "t.json"
    path.write_text(json.dumps(transcript(runs)), encoding="utf-8")

    reloaded = json.loads(path.read_text(encoding="utf-8"))

    assert classify(fixture, reloaded) == classify(fixture, transcript(runs))
