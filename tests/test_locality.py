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
    assert_labels_match,
    attribute,
    classify,
    extract_findings,
    ground_truth,
    normalise_path,
    print_report,
    review_floor,
    run_indices,
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


def manifest_two_defects() -> str:
    """`TS-0001` with a second defect, for the rules that cross-product them.

    The corpus holds exactly one fixture with exactly one defect, so `expected`
    and `known` in `assert_labels_match` are otherwise only ever exercised
    against a single-defect answer key — a `defects[:1]` mutation in either
    survives the whole suite. Phase 5 is corpus buildout, which means the first
    multi-defect fixture would be the thing that discovers that.

    The second defect sits in `src/helpers.ts`, which the diff never touches, so
    it is structurally `cross_file` and needs no second hunk.
    """
    second = """\
  - id: TS-0001-d2
    class: missing-guard
    severity: medium
    locality:
      tier: cross_file
    location:
      file: src/helpers.ts
      lines: [2, 2]
    description: >
      Rounds without checking the input is finite, so a NaN propagates.
"""
    defects, marker, distractors = manifest().partition("distractors:")
    return f"{defects}{second}{marker}{distractors}"


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


# --- labels that name nothing ------------------------------------------------


def test_a_label_naming_a_run_the_batch_does_not_have_is_refused(tmp_path: Path) -> None:
    """A label file is a human overruling the matcher; it must not miss quietly.

    Before this check `classify` looked the key up, missed, and fell through to
    the matcher — `hand_labelled` printed 0 and the matcher's verdict was
    published as though nobody had judged the run at all.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[finding("src/shipments.ts", 8, 8)], []])

    with pytest.raises(LocalityError, match="name nothing in this batch"):
        classify(fixture, transcript(runs), labels={"5:TS-0001-d1": True})


def test_a_typoed_defect_id_is_refused_rather_than_silently_dropped(tmp_path: Path) -> None:
    """One keystroke used to invert the published verdict with no error.

    Measured on `TS-0001`'s shipped labels: spelling `-dl` for `-d1` drops all
    ten human judgements, and the crude matcher those labels exist to overrule
    scores the defect 10/10 — turning the published `SURVIVED cross_file 0/10`
    into `REFUTED`. The only trace was `hand_labelled` falling to 0.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[finding("src/shipments.ts", 8, 8)], []])

    with pytest.raises(LocalityError, match=r"0:TS-0001-dl"):
        classify(fixture, transcript(runs), labels={"0:TS-0001-dl": False})


def test_a_label_naming_a_distractor_is_refused(tmp_path: Path) -> None:
    """Labels overrule detection of *defects*; a distractor has no run key.

    The key is the one `ground_truth` really builds for this fixture's only
    distractor — `distractor-1:naming-inconsistency`, from `manifest()` above.
    Spelling the kind wrong instead would pass for the wrong reason: it would be
    refused as an unknown kind, leaving the rule under test — that the distractor
    vocabulary is not a label vocabulary — unpinned. Admitting distractors into
    `expected` must fail this test, and with a misspelled kind it does not.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])

    with pytest.raises(LocalityError, match=r"0:distractor-1:naming-inconsistency"):
        classify(
            fixture,
            transcript(runs),
            labels={"0:distractor-1:naming-inconsistency": True},
        )


def test_every_unmatched_label_is_named_not_just_the_first(tmp_path: Path) -> None:
    """Fixing one typo at a time, a re-score per keystroke, is the slow failure."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])

    with pytest.raises(LocalityError) as caught:
        classify(
            fixture,
            transcript(runs),
            labels={"9:TS-0001-d1": True, "0:TS-0001-dl": False},
        )

    assert "9:TS-0001-d1" in str(caught.value)
    assert "0:TS-0001-dl" in str(caught.value)


def test_the_refusal_names_the_vocabulary_the_key_is_built_from(tmp_path: Path) -> None:
    """The error has to be actionable: which runs exist, and which defect ids."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])

    with pytest.raises(LocalityError) as caught:
        classify(fixture, transcript(runs), labels={"7:TS-0001-d1": True})

    message = str(caught.value)
    assert "[0, 1, 2]" in message
    # Asserted with its label, not as a bare id: `"TS-0001-d1" in message` is
    # already satisfied by the rejected key `'7:TS-0001-d1'` echoed in the
    # unmatched list, so it matched for an unrelated reason and deleting the
    # vocabulary clause outright left this test green.
    assert "defects ['TS-0001-d1']" in message


def test_the_refusal_never_names_the_index_it_just_rejected(tmp_path: Path) -> None:
    """A gap in the middle must not be reported as a range that spans it.

    A scored-run index set is not contiguous whenever a run failed or came back
    unparseable, which `partition_runs`' three tiers guarantee recurs. Reported
    as `min-max`, a refusal against this batch told the reader the valid indices
    were `0-2` — naming index 1, which is not scoreable, so the only way to act
    on the error was to disbelieve it. The rejected key here is `9`, a genuine
    nonsense key, because a key naming the *hole* no longer raises at all.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"

    with pytest.raises(LocalityError) as caught:
        classify(fixture, transcript(runs), labels={"9:TS-0001-d1": False})

    message = str(caught.value)
    assert "[0, 2]" in message
    assert "0-2" not in message


def test_the_refusal_says_an_unhonourable_label_is_not_in_its_list(tmp_path: Path) -> None:
    """Naming the set is not enough if the reader cannot tell what is absent from it.

    A reader who sees `[0, 2]` and has a label on run 1 needs to know that run 1
    is not the thing being refused — it is reported separately and did not stop
    the batch. Without that clause they go hunting for a typo in a key that has
    none.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"

    with pytest.raises(LocalityError, match="reported as unhonoured"):
        classify(fixture, transcript(runs), labels={"9:TS-0001-d1": False})


def test_the_refusal_does_not_claim_the_label_was_dropped(tmp_path: Path) -> None:
    """The message must describe what just happened, not what used to.

    "an unmatched label is dropped and the matcher's verdict published in its
    place" is the pre-fix behaviour this check exists to end. Left in the
    refusal it tells the reader their labels were silently discarded, when in
    fact nothing was scored at all.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])

    with pytest.raises(LocalityError) as caught:
        classify(fixture, transcript(runs), labels={"9:TS-0001-d1": True})

    assert "is dropped" not in str(caught.value)


def test_the_refusal_does_not_promise_an_absence_it_cannot_deliver(tmp_path: Path) -> None:
    """The clause about unhonourable labels is printed on keys that *are* listed.

    "A label for a run that failed or did not parse is not in this list" was
    appended unconditionally, and two reachable cases falsify it — here, a record
    that came back unparseable carrying no `run_index`, so it contributes no
    unscored index and its key is refused after all. The reader is sent hunting
    for a nonexistent index error instead of the real cause. Third consecutive
    pass on this branch to ship a false sentence about this check's own boundary,
    which is why the qualifier is pinned rather than the prose reviewed again.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[2]["parse_error"] = "no structured output on the response"
    for record in runs:
        record.pop("run_index")

    with pytest.raises(LocalityError) as caught:
        classify(fixture, transcript(runs), labels={"2:TS-0001-d1": True})

    message = str(caught.value)
    assert "absent from this list only when" in message
    assert "recorded a `run_index`" in message


def test_the_refusal_qualifies_its_clause_for_a_typo_on_an_unscoreable_run(
    tmp_path: Path,
) -> None:
    """The second falsifying case: an unscoreable index with a misspelled defect.

    `1:TS-0001-dl` names a run that really did come back unparseable, so the
    unconditional clause told the reader such a key is not in the list — while
    listing it. The defect id is what refused it, and the qualifier is what says
    so. The suite already built this batch and asserted only that it raises.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"

    with pytest.raises(LocalityError) as caught:
        classify(fixture, transcript(runs), labels={"1:TS-0001-dl": True})

    message = str(caught.value)
    assert "1:TS-0001-dl" in message
    assert "absent from this list only when" in message
    assert "is not in this list" not in message


def test_a_long_list_of_unmatched_labels_is_truncated_and_counted(tmp_path: Path) -> None:
    """Nine typos must report nine, show eight, and say it withheld the rest.

    The count prefix is the only thing that tells a reader how many keys were
    withheld, and the truncation is what keeps a wholly mis-keyed file from
    printing every key it holds.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])
    labels = {f"{index}:TS-0001-d1": False for index in range(20, 29)}

    with pytest.raises(LocalityError) as caught:
        classify(fixture, transcript(runs), labels=labels)

    message = str(caught.value)
    assert message.startswith("9 label(s)")
    # Counted with the colon so the `defects ['TS-0001-d1']` tail, which is not
    # a key, cannot be mistaken for a ninth listed key.
    assert message.count(":TS-0001-d1'") == 8
    assert " ..." in message


def test_a_label_on_an_unparseable_run_scores_the_rest_and_is_reported(
    tmp_path: Path,
) -> None:
    """The decided behaviour: report the unhonourable label, score the others.

    Refusing the whole batch here was the first shape of the check, and it made
    a re-run coming back unparseable turn a shipped label file into a hard
    error against its own transcript. The run is real and the judgement about it
    is real; only the scoring is impossible.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"
    labels = {f"{index}:TS-0001-d1": True for index in range(3)}

    report = classify(fixture, transcript(runs), labels=labels)

    assert report.unhonourable_labels == ["1:TS-0001-d1"]
    assert report.scored == 2
    assert report.unparseable == 1
    # The two honoured labels still overrule the matcher; the third is counted
    # nowhere, so `hand_labelled` falls short of the file on its own.
    assert report.verdicts[0].hand_labelled == 2
    assert report.verdicts[0].hits == 2


def test_a_whole_file_off_by_one_is_refused_not_absorbed(tmp_path: Path) -> None:
    """A uniform shift is recognised as one, not honoured key by key.

    Reporting an unhonourable key is decided one key at a time, and that is what
    lets a whole-file off-by-one through: numbering the runs from 1, the reader's
    top key lands on the unscoreable index and is *reported* — which reads like a
    clean batch — while every key below it shifts one place inside the scored set
    and is honoured against the wrong run.

    Reproduced on this batch, where only run 0 found the defect: the 1-based keys
    score detection 2/2 where the correct keys score 1/2, and the only trace is
    `hand_labelled` reading 1 — a shortfall `print_report`'s unhonourable warning
    then explains away as a run that could not be scored. The one signal the
    design relies on is consumed by the feature that creates the hazard.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[finding("src/shipments.ts", 8, 8)], [], []])
    runs[2]["parse_error"] = "no structured output on the response"

    with pytest.raises(LocalityError, match="keyed one high"):
        classify(
            fixture,
            transcript(runs),
            labels={"1:TS-0001-d1": True, "2:TS-0001-d1": False},
        )

    # The same two judgements keyed correctly still score, so the refusal is not
    # a revert of the unhonourable-label decision: run 0 is overruled to found,
    # run 1 to not-found, and the unscoreable run carries no label at all.
    report = classify(
        fixture,
        transcript(runs),
        labels={"0:TS-0001-d1": True, "1:TS-0001-d1": False},
    )

    assert report.verdicts[0].hits == 1
    assert report.verdicts[0].hand_labelled == 2
    assert report.unhonourable_labels == []


def test_a_correct_subset_of_labels_is_not_read_as_a_shift(tmp_path: Path) -> None:
    """A shift is a property of the whole key set, not of keys that happen to fit.

    Testing containment — every shifted key lands somewhere in `expected` —
    refuses a *correct* label file whenever its keys sit at the top of the scored
    range with one on the unscoreable run above them. Shifting them down one then
    lands each on some scored index, which containment accepts and a reader would
    never call a whole-file off-by-one.

    Reproduced on the shipped batch's shape: nine scored runs, run 9 unparseable,
    labels for runs 8 and 9 only. Both are keyed correctly; 8 scores and 9 is the
    unhonourable report the 2026-09-10 decision requires. The `len(labelled) > 1`
    gate does not help — two keys are enough to trip it.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(10, [[finding("src/shipments.ts", 8, 8)]] + [[] for _ in range(9)])
    runs[9]["parse_error"] = "no structured output on the response"

    report = classify(
        fixture,
        transcript(runs),
        labels={"8:TS-0001-d1": False, "9:TS-0001-d1": False},
    )

    assert report.unhonourable_labels == ["9:TS-0001-d1"]
    assert report.verdicts[0].hand_labelled == 1

    # The whole-file case is still refused: every scored index is covered, which
    # is what makes it a shift rather than a subset that happens to fit.
    with pytest.raises(LocalityError, match="keyed one high"):
        classify(
            fixture,
            transcript(runs),
            labels={f"{index + 1}:TS-0001-d1": False for index in range(9)},
        )


def test_a_file_keyed_one_low_is_refused_without_the_1_based_gloss(tmp_path: Path) -> None:
    """The other direction of the shift, and the clause true in one direction only.

    Both other refusal sites match `keyed one high`, so the `offset == +1` branch
    is unpinned: flipping the ternary, or emitting the gloss unconditionally,
    passes the suite either way. The gloss explains a file numbered from 1, which
    is the `high` case alone — on a file keyed one *low* it would name a cause
    that cannot produce it, which is the half of the message that was verified by
    hand and never tested.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3)

    with pytest.raises(LocalityError, match="keyed one low") as excinfo:
        classify(
            fixture,
            transcript(runs),
            labels={f"{index - 1}:TS-0001-d1": False for index in range(3)},
        )

    assert "Numbering the runs from 1" not in str(excinfo.value)


def test_a_single_label_on_an_unscoreable_run_is_still_reported(tmp_path: Path) -> None:
    """One key is not a set, so it cannot be read as a whole-file shift.

    The shift refusal above and the unhonourable report decided on 2026-09-10
    meet here: a lone label on a run that failed is indistinguishable from a lone
    label written one too low, and the decision is to report it. Two keys are the
    least that can show a *constant* shift, which is why the refusal needs them.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])
    runs[0].update({"failed": True, "error": "timeout"})

    report = classify(fixture, transcript(runs), labels={"0:TS-0001-d1": True})

    assert report.unhonourable_labels == ["0:TS-0001-d1"]


def test_a_label_on_a_failed_run_is_unhonourable_not_nonsense(tmp_path: Path) -> None:
    """A failed run is as real as an unparseable one; it just produced nothing."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])
    runs[0].update({"failed": True, "error": "timeout"})

    report = classify(fixture, transcript(runs), labels={"0:TS-0001-d1": True})

    assert report.unhonourable_labels == ["0:TS-0001-d1"]
    assert report.failed == 1 and report.scored == 1


def test_print_report_shows_an_unhonourable_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returning the key is only half of it; the reader has to see it.

    The whole reason an unhonourable label is not an error is that it is
    reported instead. If it reaches no output, this is a silent drop wearing a
    field name — the exact hole this module keeps closing.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"
    tr = transcript(runs)

    report = classify(fixture, tr, labels={"1:TS-0001-d1": True})
    print_report(fixture, report, tr)

    out = capsys.readouterr().out
    assert "1:TS-0001-d1" in out
    assert "could not be honoured" in out


def test_the_two_hazards_this_check_exists_for_still_raise(tmp_path: Path) -> None:
    """The boundary that matters: neither headline hazard names a real run.

    Softening the unscoreable case must not soften these. Numbering the runs
    from 1 walks off the end of the batch, and `-dl` for `-d1` names a defect
    that is not in the answer key — the two mistakes measured on `TS-0001`'s own
    shipped labels, and the reason this check raises at all.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"

    # One-based numbering: run 3 is one past the last record in the batch.
    with pytest.raises(LocalityError, match="name nothing in this batch"):
        classify(fixture, transcript(runs), labels={"3:TS-0001-d1": True})

    # The typo, on an index that *is* unscoreable — the defect id still decides.
    with pytest.raises(LocalityError, match="name nothing in this batch"):
        classify(fixture, transcript(runs), labels={"1:TS-0001-dl": True})


def test_an_unscoreable_record_with_no_run_index_is_not_given_one(
    tmp_path: Path,
) -> None:
    """No invented position for a record that never recorded one.

    `print_report` numbering by position and this module numbering by scored
    position is the divergence still queued in PLAN.md. Guessing an index for an
    unscoreable record would add a second one, so such a key stays an error.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    # The *last* record is the unscoreable one, so its position (2) is not also
    # a scored index. With the records numbered by position it would be run 2;
    # the two scored records fall back to 0 and 1, so `2:` names nothing and
    # must raise. Put the hole in the middle instead and this test cannot tell
    # the two behaviours apart, because position 1 is a scored index too.
    runs[2]["parse_error"] = "no structured output on the response"
    for record in runs:
        record.pop("run_index")

    with pytest.raises(LocalityError, match="name nothing in this batch"):
        classify(fixture, transcript(runs), labels={"2:TS-0001-d1": True})


def test_a_key_that_only_looks_like_an_index_is_a_typo(tmp_path: Path) -> None:
    """`" 1"` and `"01"` are not run 1; a near-miss key must not be excused."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], []])
    runs[1]["parse_error"] = "no structured output on the response"

    # `"TS-0001-d1"` has no numeric head at all — a label file written without
    # run prefixes, which is the case that keeps a bare `ValueError` from `int()`
    # inside the module's error contract. Every other key in this suite parses,
    # so without it the `except ValueError` arm is dead and `classify`, which
    # wraps `run_indices` and not this helper, would let the `ValueError` escape.
    for key in ("01:TS-0001-d1", " 1:TS-0001-d1", "+1:TS-0001-d1", "TS-0001-d1"):
        with pytest.raises(LocalityError, match="name nothing in this batch"):
            classify(fixture, transcript(runs), labels={key: True})


def test_commentary_keys_are_not_labels_and_are_not_refused(tmp_path: Path) -> None:
    """`_`-prefixed keys carry the reasoning behind the judgements beside them.

    The convention is `assay.eval.precision.load_labels`'s, and the shipped
    label files use it. Enforcing it only in `main`, which strips such keys on
    the way in, would leave every other caller — the shipped-results test
    included — handing `classify` a file it refuses to read.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(MIN_RUNS_TO_VERIFY, [[finding("src/shipments.ts", 8, 8)]] + [[]] * 9)

    report = classify(
        fixture,
        transcript(runs),
        labels={"_README": True, "_why_run_0_counts": False, "0:TS-0001-d1": False},
    )

    assert report.verdicts[0].hand_labelled == 1
    assert report.verdicts[0].status is Verdict.SURVIVED


def test_labels_against_a_batch_that_scored_nothing_say_so(tmp_path: Path) -> None:
    """The empty case must not divide by an empty index range.

    The key is `5`, which names no run at all: `0` now names the failed run and
    is reported as unhonourable rather than refused.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(1, [[]])
    runs[0].update({"failed": True, "error": "timeout"})

    with pytest.raises(LocalityError, match="no run scored"):
        classify(fixture, transcript(runs), labels={"5:TS-0001-d1": True})


def test_every_defect_in_the_answer_key_gets_a_label_key(tmp_path: Path) -> None:
    """`expected` and `known` are both cross products, and one defect hides it.

    Both the accepted set (`expected`) and the known-defect set (`known`) are
    built from every defect in the fixture, and the corpus holds one fixture with
    one defect — so a `defects[:1]` mutation in either line survived the whole
    suite. Phase 5 is corpus buildout: the first multi-defect fixture is when that
    would surface, as a second defect's labels refused for naming nothing.

    The two lines fail differently and so need separate cases. Truncating
    `expected` refuses a valid key outright, which the labels below catch.
    Truncating `known` is quieter: the key still fails to match, so it reaches the
    unhonourable/nonsense fork, and a defect id that is real but not in the
    truncated `known` is reclassified from *reported* to *raised* — the
    2026-09-10 decision broken for every defect but the first. Only a label on an
    unscoreable run discriminates that line, which is the last case here.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001", text=manifest_two_defects()))
    runs = clean_runs(2, [[], []])

    report = classify(
        fixture,
        transcript(runs),
        labels={"0:TS-0001-d1": True, "0:TS-0001-d2": False, "1:TS-0001-d2": True},
    )

    assert report.verdicts[0].hand_labelled == 1
    assert report.verdicts[1].hand_labelled == 2
    assert report.verdicts[1].hits == 1

    # A third defect id is still refused: the cross product is over the answer
    # key, not over whatever the label file names.
    with pytest.raises(LocalityError, match="name nothing in this batch"):
        classify(fixture, transcript(runs), labels={"0:TS-0001-d3": True})

    # `known` is the line this discriminates. The second defect, labelled on a run
    # that exists but cannot be scored, is *reported* — and is refused as nonsense
    # the moment `known` stops covering every defect in the answer key.
    unscoreable = clean_runs(2, [[], []])
    unscoreable[1]["parse_error"] = "no structured output on the response"

    report = classify(
        fixture,
        transcript(unscoreable),
        labels={"1:TS-0001-d2": True},
    )

    assert report.unhonourable_labels == ["1:TS-0001-d2"]


def test_a_malformed_run_index_is_refused_on_an_unscoreable_record_too(
    tmp_path: Path,
) -> None:
    """One integer rule for every record, not one for the records that score.

    `run_indices` refuses a non-integer `run_index` on a scored record; the set
    of unscoreable indices filtered one out with `isinstance` and said nothing.
    So `3.0` was an error on a scored record and invisible on the unparseable one
    beside it — and a label naming that position then hard-failed with "name
    nothing in this batch" rather than being reported as unhonourable, which is
    the whole point of recording the index. A rule enforced in one of two entry
    points is the shape of bug this module keeps closing.

    `True` is in the list because `bool` is an `int` subclass: the guard
    excluding it was the only type check such a record ever got, and nothing
    pinned it — removing it left all 322 tests green while downgrading a refusal
    to a report, since `1 in {True}`.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))

    for bad in (3.0, None, True, "first"):
        runs = clean_runs(2, [[], []])
        runs[1]["parse_error"] = "no structured output on the response"
        runs[1]["run_index"] = bad

        with pytest.raises(LocalityError, match="run_index must be an integer"):
            classify(fixture, transcript(runs))

        failed = clean_runs(2, [[], []])
        failed[1].update({"failed": True, "error": "timeout", "run_index": bad})

        with pytest.raises(LocalityError, match="run_index must be an integer"):
            classify(fixture, transcript(failed))


def test_assert_labels_match_accepts_exactly_the_keys_run_key_builds(tmp_path: Path) -> None:
    """The check is a set difference, so it is pinned directly as well."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    defects = [item for item in ground_truth(fixture) if item.is_defect]

    assert_labels_match({"0:TS-0001-d1": True, "1:TS-0001-d1": False}, [0, 1], defects)

    with pytest.raises(LocalityError):
        assert_labels_match({"2:TS-0001-d1": True}, [0, 1], defects)


# --- run identity ------------------------------------------------------------


def test_a_repeated_run_index_is_refused(tmp_path: Path) -> None:
    """One label must not score two runs.

    Reproduced before the guard existed: with both runs stamped `run_index: 0`,
    the single label `0:TS-0001-d1` counted as two hits out of two scored runs
    and `hand_labelled` read 2 — a detection rate of 1.00 derived from one human
    judgement, with nothing raised.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[finding("src/shipments.ts", 40, 40)], []])
    runs[1]["run_index"] = 0

    with pytest.raises(LocalityError, match="run_index repeated"):
        classify(fixture, transcript(runs), labels={"0:TS-0001-d1": True})


def test_a_failed_run_may_not_share_an_index_with_a_scored_one(tmp_path: Path) -> None:
    """The rationale that blessed this batch is one this branch falsified.

    It read: "a failed run is dropped everywhere and never carries a label, so
    refusing a batch over its index would reject transcripts that score
    correctly". A failed run is now exactly what a label may name — that is the
    unhonourable-label rule — and with the index shared the key is in `expected`,
    so the judgement about the *failed* run is honoured against the *scored* one
    and `unhonourable_labels` stays empty. Reproduced: `hand_labelled=1`,
    `hits=0`, nothing printed, no error.

    Such a batch does not score correctly, so the exemption no longer buys
    anything. The trigger is the one `run_indices`' own docstring names: two
    batches concatenated, which is how a re-run gets appended.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(2, [[], []])
    runs[0].update({"failed": True, "error": "timeout"})
    runs[1]["run_index"] = 0

    with pytest.raises(LocalityError, match="names both a scored run"):
        classify(fixture, transcript(runs), labels={"0:TS-0001-d1": True})

    # Refused with no labels as well: the identity is wrong whether or not this
    # invocation happens to pass a label file, and a transcript that re-scores
    # months later must not become an error the moment one is written.
    with pytest.raises(LocalityError, match="names both a scored run"):
        classify(fixture, transcript(runs))


def test_run_indices_falls_back_to_position_and_still_catches_a_collision() -> None:
    """Mixed presence is a way to collide, not an escape from the check."""
    assert run_indices([{}, {}, {}]) == [0, 1, 2]
    assert run_indices([{"run_index": 7}, {"run_index": 3}]) == [7, 3]

    # Position 1 has no `run_index`, so it falls back to 1 — which the first
    # record already claims.
    with pytest.raises(ValueError, match=r"run_index repeated in this batch: \[1\]"):
        run_indices([{"run_index": 1}, {}])


def test_labels_are_keyed_by_recorded_run_index_not_by_position(tmp_path: Path) -> None:
    """A failed run leaves a gap, and the gap must not shift every later label.

    `classify` keys hand labels by the *recorded* `run_index`, not by the run's
    position among the scored runs. `measure` writes a record for a failed run
    too, so a batch whose first run died has scored runs numbered 1 and 2 sitting
    at positions 0 and 1 — and keying by position would apply each label to the
    wrong run and move the detection rate with nothing raised.

    `assay.eval.precision` has pinned this since it was written; locality did
    not, so the keying line could be rewritten to `enumerate(scored)` with the
    whole suite still green.
    """
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(3, [[], [], [finding("src/shipments.ts", 40, 40)]])
    runs[0].update({"failed": True, "error": "timeout"})

    # Run 2 is the one the human labelled; it sits at position 1 among the
    # scored runs, so position-keying would credit run 1 instead.
    report = classify(fixture, transcript(runs), labels={"2:TS-0001-d1": True})

    assert report.scored == 2
    assert report.verdicts[0].hand_labelled == 1
    assert report.verdicts[0].hits == 1


@pytest.mark.parametrize(
    "value",
    [
        None,  # JSON null — `int()` raises TypeError, which no caller catches
        "first",  # non-numeric — `int()` raises, naming the wrong problem
        3.0,  # JSON float — truncates, silently re-keying the run
        True,  # bool is an int subclass in Python, so `int(True)` is 1
    ],
    ids=["null", "text", "float", "bool"],
)
def test_a_run_index_that_is_not_an_integer_is_refused(value: Any) -> None:
    """The field is an identity, so it is taken as written or not at all.

    Coercing it is what makes a wrong number silent. `3.0` truncating to `3`
    re-keys the run: a label file written `"3.0:TS-0001-d1"` matched before the
    coercion existed and misses after it, and because `classify` does not
    validate label keys the human's judgement is dropped without a word and the
    crude matcher's verdict is published instead. `True` keying as `1` is the
    same hazard wearing a different hat.

    Rejecting rather than coercing also puts `None` inside the module's error
    contract: a bare `TypeError` from `int()` escapes both callers' wraps.
    """
    with pytest.raises(ValueError, match="run_index"):
        run_indices([{"run_index": value}])


def test_a_malformed_run_index_reaches_the_caller_as_its_own_error(tmp_path: Path) -> None:
    """`classify` promises `LocalityError`; a raw `TypeError` breaks that."""
    fixture = load_fixture(build(tmp_path / "TS-0001"))
    runs = clean_runs(1, [[]])
    runs[0]["run_index"] = None

    with pytest.raises(LocalityError, match="run_index"):
        classify(fixture, transcript(runs))


def test_every_repeated_index_is_named_not_just_the_first() -> None:
    with pytest.raises(ValueError, match=r"\[2, 5\]"):
        run_indices(
            [
                {"run_index": 5},
                {"run_index": 2},
                {"run_index": 5},
                {"run_index": 2},
                {"run_index": 9},
            ]
        )


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
