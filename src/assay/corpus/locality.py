"""Settling a defect's locality tag by measurement rather than by argument.

DESIGN makes locality a *measurement*: run the single-shot reviewer against the
fixture with no tools, and a defect it finds is not `cross_file`, whatever the
author intended. The Phase 0 pilot is the reason. Two of its three defects were
authored `cross_file` and both turned out reachable from the review floor — once
because a class comment in the touched file restated the very invariant the diff
broke, once because the new handler was visibly asymmetric with its siblings.
Neither fixture looked wrong on inspection, and the author was actively trying
to avoid exactly that. Since the headline result is reported *broken out by
locality*, a bad tag does not add noise; it produces a confidently wrong answer.

**What this measurement can and cannot say.** It refutes `cross_file` and
nothing else. The floor is the diff plus the full contents of every file the
diff touches, so a reviewer that finds a defect from the floor alone has proved
the evidence was inside that floor — which rules out `cross_file` but does not
choose between `local` and `touched_file`. That distinction is structural (are
the defect's own lines inside a diff hunk?) and `Fixture.structural_locality`
already answers it. So:

- **found** by any no-tools run  →  the tag is not `cross_file`.
- **not found** in `n` runs      →  `cross_file` is *not refuted*. That is a
  failure to refute, not proof, which is why a claim is only reported settled
  once `n` reaches `MIN_RUNS_TO_VERIFY`; below that the verdict is
  `underpowered` and the tag stays unverified.

The same runs answer two other questions at no extra cost, because the expensive
part is the run and re-scoring a stored transcript is free:

- **Saturation.** The pilot found its seeded defect in 34 of 34 runs. A corpus
  at the recall ceiling cannot answer whether tools help, because recall has
  nowhere to climb — so a detection rate of 1.00 is an authoring failure and the
  fixture gets reworked. PLAN calls for the observed rate to be recorded in
  `NOTES.md`; this is where the number comes from.
- **Distractor bites.** Which distractors a reviewer actually flags. A
  distractor nobody ever bites is not doing its job, and precision measured
  against it conveys nothing.

**This module does not edit the manifest.** It prints the `locality:` block to
paste. Writing the answer key from a measurement automatically would put the
matcher, which is crude and deliberately so (below), in charge of ground truth.

**The matcher is a placeholder and is meant to be overruled.** Phase 3 owns the
real proximity gate and the semantic judge. Here, a finding is attributed to the
*nearest* ground-truth item in the same file — defect or distractor — and counts
as a detection only if the nearest one is the defect and it is within `--window`
lines. Nearest-wins rather than a plain window because `TS-0001`'s distractors
sit 7 lines from the defect, and a fixed ±15 window would score a distractor
bite as a detection. Ties go to the defect: over-counting detections can only
*refute* a `cross_file` claim, and a false `cross_file` claim is the failure this
step exists to catch, so the bias points away from it. Pass `--labels` to
overrule the matcher by hand; the verdict records how many runs were labelled.

Run it, then re-score for free::

    .venv/bin/python -m assay.corpus.locality \\
        corpus/ts/TS-0001-reservation-double-release --runs 10
    .venv/bin/python -m assay.corpus.locality \\
        corpus/ts/TS-0001-reservation-double-release \\
        --from results/locality/TS-0001-20260731T120000Z.json --window 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import MessageParam, OutputConfigParam, TextBlockParam

from assay.corpus.loader import Fixture, load_fixture
from assay.corpus.manifest import Location
from assay.corpus.taxonomy import Locality
from assay.cost import cost_usd

#: A `cross_file` claim is only reported settled once this many runs have failed
#: to find the defect. One quiet run is not evidence of anything; the number
#: matches the pilot's per-group K and the evidence string DESIGN sketches
#: ("0/10 single-shot runs found it").
MIN_RUNS_TO_VERIFY = 10

#: Lines of slack when attributing a finding to a ground-truth location. Small
#: on purpose: `TS-0001`'s nearest distractor is 7 lines from the defect, so a
#: wide window would let nearest-wins attribution degrade back into guessing.
DEFAULT_WINDOW = 10

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16_000
DEFAULT_RUNS = MIN_RUNS_TO_VERIFY

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

#: The single-shot reviewer's instructions. Phase 2 owns the real reviewer and
#: will replace this; until then it is copied from the Phase 0 pilot so the
#: measurement reflects the reviewer the sweep actually runs.
#:
#: Locality is a property of *this reviewer against this floor*, not of the
#: defect alone — so the transcript records a digest of the exact prompt, and
#: changing the prompt invalidates the recorded evidence rather than merely
#: aging it.
REVIEWER_INSTRUCTIONS = """\
You are reviewing a code change for correctness defects: logic errors, \
incorrect edge-case handling, broken invariants, race conditions, and \
data-integrity problems.

Report only defects you can point at in the code. For each one give the file, \
the line range, a short class name, a severity, your confidence from 0 to 1, \
and an explanation of what goes wrong and under what conditions.

Do not report style, naming, formatting, or test-coverage opinions. Do not \
report anything you cannot tie to a specific location. If you find nothing, \
return an empty list — an empty list is a valid and sometimes correct answer.\
"""

#: Deliberately not an anticipation of Phase 2's `Finding`. It exists so the
#: reviewer returns something a matcher can read; Phase 2 owns the real schema.
FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Repo-relative path, e.g. src/jobs/sweeper.ts",
                    },
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "claimed_class": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "confidence": {"type": "number"},
                    "message": {"type": "string"},
                },
                "required": [
                    "file",
                    "start_line",
                    "end_line",
                    "claimed_class",
                    "severity",
                    "confidence",
                    "message",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


class LocalityError(RuntimeError):
    """The measurement could not be run, or read, in a state that means anything."""


# --- the review-context floor ------------------------------------------------


def review_floor(fixture: Fixture) -> str:
    """DESIGN's review-context floor: the diff plus every file it touches, whole.

    The floor is what makes the v1 question answerable — single-shot and agentic
    reviewers start from byte-identical context and differ only in tool ceiling,
    so a differing floor would confound context volume with tool access. It is
    defined here because the locality measurement is the first thing that needs
    it. **Phase 2 must import this function rather than assemble its own**: its
    contract test asserts both reviewers receive identical floors, and two
    implementations of "identical" is how that test comes to pass while the
    thing it protects is broken.
    """
    parts = [
        "The change under review:",
        "",
        "```diff",
        fixture.diff.rstrip(),
        "```",
        "",
        "Full current contents of every file the change touches:",
        "",
    ]
    for relative in fixture.touched_files:
        path = fixture.repo / relative
        if not path.is_file():
            # `load_fixture` already refuses this, so reaching it means the tree
            # changed underneath a loaded fixture.
            raise LocalityError(f"{fixture.id}: diff touches missing file {relative}")
        parts += [
            f"--- {relative} ---",
            "```typescript",
            path.read_text(encoding="utf-8").rstrip(),
            "```",
            "",
        ]
    return "\n".join(parts)


def review_task(fixture: Fixture) -> str:
    source_count = len([p for p in fixture.repo.rglob("*.ts") if p.is_file()])
    return (
        f"Review the change below. The repository is a TypeScript project "
        f"({source_count} source files).\n\n" + review_floor(fixture)
    )


def prompt_digest(task: str) -> str:
    """A short digest of the exact prompt a measurement ran against.

    Recorded because locality is measured *relative to a reviewer and a floor*.
    If either changes, the stored verdict describes a reviewer that no longer
    exists, and the honest response is to re-measure rather than to keep quoting
    the old number.
    """
    combined = task + "\n\n" + REVIEWER_INSTRUCTIONS
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


# --- structured-output parsing -----------------------------------------------


def extract_findings(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Pulls the findings list out of a structured-output payload.

    Returns `(findings, parse_error)`. On any failure the list is empty **and**
    `parse_error` is set, and a caller must never read the first value without
    the second: an empty list with no error is a real review that found nothing,
    and an empty list with an error is not a result at all. That conflation is
    the exact bug the pilot shipped — both runners recorded `parse_error` and
    the analyzer never read the field, so a parse failure scored identically to
    a clean empty review.
    """
    if payload is None:
        return [], "no structured output on the response"
    if not isinstance(payload, dict):
        return [], f"structured output is {type(payload).__name__}, not an object"
    if "findings" not in payload:
        # The schema requires this key, so its absence means the constraint did
        # not hold. Defaulting to [] here is the whole failure mode.
        return [], "structured output has no 'findings' key"
    findings = payload["findings"]
    if not isinstance(findings, list):
        return [], f"'findings' is {type(findings).__name__}, not a list"
    malformed = [i for i, item in enumerate(findings) if not isinstance(item, dict)]
    if malformed:
        return [], f"findings at index {malformed} are not objects"
    return findings, None


# --- running the reviewer ----------------------------------------------------


def run_once(
    client: anthropic.Anthropic,
    fixture: Fixture,
    task: str,
    *,
    model: str,
    effort: str,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    """One single-shot review of `fixture`. No tools, floor context only."""
    # Fixture first, behind the cache breakpoint, reviewer instructions after —
    # the ordering DESIGN's cost-controls table rests on, and the one Phase 0
    # measured working across reviewers on a shared fixture.
    system: list[TextBlockParam] = [
        {"type": "text", "text": task, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": REVIEWER_INSTRUCTIONS},
    ]
    output_config: OutputConfigParam = {
        "effort": effort,  # type: ignore[typeddict-item]  # validated by argparse choices
        "format": {"type": "json_schema", "schema": FINDING_SCHEMA},
    }
    messages: list[MessageParam] = [
        {"role": "user", "content": "Review the change described in the system context."}
    ]

    started = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
        output_config=output_config,
        system=system,
        messages=messages,
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    findings: list[dict[str, Any]]
    parse_error: str | None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        findings, parse_error = [], f"JSONDecodeError: {error}"
    else:
        findings, parse_error = extract_findings(payload)

    usage = response.usage
    return {
        "mode": "single_shot",
        "fixture": fixture.id,
        "model": response.model,
        "stop_reason": response.stop_reason,
        "findings": findings,
        "parse_error": parse_error,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
            "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
        },
        "cost_usd": cost_usd(
            response.model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_creation_input_tokens or 0,
            usage.cache_read_input_tokens or 0,
        ),
        "wall_seconds": round(time.monotonic() - started, 2),
    }


def run_with_retries(
    run_fn: Callable[[], dict[str, Any]],
    retries: int,
    label: str,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any] | None, str | None]:
    """Calls `run_fn`, retrying transient failures with a linear backoff.

    Returns `(record, None)` on success or `(None, last_error)` once the retries
    are spent — never raises, because the caller's job is to *record* the dead
    run and carry on. A gap in the transcripts would let a later reader see a
    smaller n and read it as the intended number of runs.

    A named function with an injectable `sleep`, rather than an inline `try`,
    because the Phase 0 pilot's version of this bug was an *untested* failure
    path — and a failure path that waits five real seconds does not get tested.
    """
    last_error: str | None = None
    for attempt in range(1, retries + 2):
        try:
            return run_fn(), None
        except Exception as error:  # noqa: BLE001 - deliberately broad
            last_error = f"{type(error).__name__}: {error}"
            print(f"   {label} attempt {attempt} failed: {error}")
            if attempt <= retries:
                sleep(5 * attempt)
    return None, last_error


# --- attributing findings to ground truth ------------------------------------


@dataclass(frozen=True)
class GroundTruth:
    """One thing a finding can legitimately be about."""

    id: str
    location: Location
    is_defect: bool


def ground_truth(fixture: Fixture) -> list[GroundTruth]:
    """Defects and distractors, in the order a verdict reports them."""
    items = [GroundTruth(d.id, d.location, True) for d in fixture.defects]
    items += [
        GroundTruth(f"distractor-{i}:{d.kind}", d.location, False)
        for i, d in enumerate(fixture.distractors, start=1)
    ]
    return items


def normalise_path(raw: Any) -> str:
    """Reviewers cite `./src/x.ts`, `/src/x.ts`, and `src/x.ts` interchangeably.

    Prefixes are stripped one at a time rather than with `lstrip("./")`, which
    strips a *character set* and would eat the leading dot of a legitimate
    dotfile path.
    """
    path = str(raw).strip()
    while path.startswith("./") or path.startswith("/"):
        path = path[2:] if path.startswith("./") else path[1:]
    return path


def line_distance(finding_start: int, finding_end: int, location: Location) -> int:
    """Lines between a finding's range and a ground-truth range; 0 if they overlap."""
    low, high = location.lines
    start, end = min(finding_start, finding_end), max(finding_start, finding_end)
    if end < low:
        return low - end
    if start > high:
        return start - high
    return 0


def attribute(
    finding: dict[str, Any], items: list[GroundTruth], window: int
) -> tuple[GroundTruth | None, int | None]:
    """The nearest ground-truth item in the same file, if it is within `window`.

    Nearest-wins rather than a plain proximity window because a fixture's
    distractors are deliberately close to its defect — `TS-0001`'s nearest sits
    7 lines away — so a window wide enough to tolerate a reviewer citing the
    call site instead of the guard would also swallow a distractor bite and
    score it as a detection.

    A tie resolves to the defect. That bias is deliberate and it points in the
    safe direction: an over-counted detection can only *refute* a `cross_file`
    claim, and a false `cross_file` claim is the failure this whole step exists
    to catch.
    """
    path = normalise_path(finding.get("file", ""))
    raw_start = finding.get("start_line", 0)
    raw_end = finding.get("end_line", raw_start)
    if not isinstance(raw_start, int) or not isinstance(raw_end, int):
        return None, None

    candidates = [item for item in items if item.location.file == path]
    if not candidates:
        return None, None

    # `not is_defect` as the tiebreak: False sorts before True, so a defect at
    # the same distance wins.
    best = min(
        candidates,
        key=lambda item: (line_distance(raw_start, raw_end, item.location), not item.is_defect),
    )
    distance = line_distance(raw_start, raw_end, best.location)
    return (best, distance) if distance <= window else (None, distance)


def run_key(index: int, defect_id: str) -> str:
    """The key a `--labels` file uses to overrule the matcher for one run."""
    return f"{index}:{defect_id}"


# --- verdicts ----------------------------------------------------------------


class Verdict(StrEnum):
    #: Claimed `cross_file`, and a no-tools run found it. The tag is wrong.
    REFUTED = "refuted"
    #: Claimed `cross_file`, and enough runs failed to find it. The tag stands.
    SURVIVED = "survived"
    #: Claimed `cross_file`, unfound, but too few runs to call it. Run more.
    UNDERPOWERED = "underpowered"
    #: Not claimed `cross_file`. This measurement can neither confirm nor refute
    #: such a tag; the structural bound already constrains it.
    CONSISTENT = "consistent"
    #: Found, yet the diff never showed the file it lives in. Needs a human.
    CONFLICT = "conflict"
    #: No scoreable runs.
    UNRUN = "unrun"


@dataclass(frozen=True)
class DefectVerdict:
    defect_id: str
    claimed: Locality
    structural: Locality
    hits: int
    scored: int
    hand_labelled: int
    status: Verdict
    evidence: str

    @property
    def detection_rate(self) -> float | None:
        return self.hits / self.scored if self.scored else None

    @property
    def saturated(self) -> bool:
        """Found by every scored run — an authoring failure, not a good result.

        A corpus sitting at the recall ceiling cannot answer whether tools help,
        because recall has nowhere to climb.
        """
        return self.scored > 0 and self.hits == self.scored

    @property
    def settled(self) -> bool:
        return self.status in (Verdict.SURVIVED, Verdict.CONSISTENT) and not self.saturated

    @property
    def resolved(self) -> Locality | None:
        """The tier the measurement supports, or None when a human must decide."""
        if self.status is Verdict.SURVIVED:
            return Locality.CROSS_FILE
        if self.status is Verdict.CONSISTENT:
            return self.claimed
        if self.status is Verdict.REFUTED:
            # Not cross_file; the diff's shape bounds it from the other side.
            return self.structural
        return None


@dataclass(frozen=True)
class LocalityReport:
    fixture_id: str
    model: str
    effort: str
    window: int
    stamp: str
    prompt_sha256: str
    total_runs: int
    failed: int
    unparseable: int
    scored: int
    verdicts: list[DefectVerdict]
    distractor_bites: dict[str, int]
    cost_usd: float

    @property
    def settled(self) -> bool:
        """Whether the fixture's tags are measured and it is not too easy."""
        return bool(self.verdicts) and all(v.settled for v in self.verdicts)


def classify(
    fixture: Fixture,
    transcript: dict[str, Any],
    window: int = DEFAULT_WINDOW,
    labels: dict[str, bool] | None = None,
) -> LocalityReport:
    """Reads a verdict out of a stored transcript, making no model calls.

    Separate from the run so the judgement can be re-derived months later, and
    so every rule below is testable without an API key. Re-scoring with a
    different window, or with hand labels, costs nothing.
    """
    labels = labels or {}
    runs = list(transcript.get("runs", []))

    # Three tiers, not two. A run that failed outright produced nothing. A run
    # whose structured output would not parse still cost money and still has to
    # be reported, but its finding list is *unknown* rather than empty — scoring
    # it as "found nothing" would depress detection and could turn a refutable
    # cross_file claim into a surviving one.
    billed = [r for r in runs if not r.get("failed")]
    scored = [r for r in billed if not r.get("parse_error")]

    items = ground_truth(fixture)
    defects = [item for item in items if item.is_defect]

    hits: dict[str, int] = {item.id: 0 for item in defects}
    labelled: dict[str, int] = {item.id: 0 for item in defects}
    bites: dict[str, int] = {item.id: 0 for item in items if not item.is_defect}

    for index, record in enumerate(scored):
        matched: set[str] = set()
        for finding in record.get("findings", []):
            if not isinstance(finding, dict):
                continue
            target, _ = attribute(finding, items, window)
            if target is not None:
                matched.add(target.id)
        for name in matched:
            if name in bites:
                bites[name] += 1
        for target_defect in defects:
            key = run_key(record.get("run_index", index), target_defect.id)
            if key in labels:
                labelled[target_defect.id] += 1
                was_found = bool(labels[key])
            else:
                was_found = target_defect.id in matched
            if was_found:
                hits[target_defect.id] += 1

    model = str(transcript.get("model", DEFAULT_MODEL))
    effort = str(transcript.get("effort", "high"))
    stamp = str(transcript.get("stamp", ""))

    verdicts: list[DefectVerdict] = []
    for defect in fixture.defects:
        found = hits.get(defect.id, 0)
        n = len(scored)
        structural = fixture.structural_locality(defect.location)
        status = _status(defect.locality.tier, structural, found, n)
        verdicts.append(
            DefectVerdict(
                defect_id=defect.id,
                claimed=defect.locality.tier,
                structural=structural,
                hits=found,
                scored=n,
                hand_labelled=labelled.get(defect.id, 0),
                status=status,
                evidence=(
                    f"{found}/{n} single-shot runs found it "
                    f"({stamp[:8] or 'unstamped'}, {model}, effort={effort}, "
                    f"floor+no tools, window=±{window})"
                ),
            )
        )

    return LocalityReport(
        fixture_id=fixture.id,
        model=model,
        effort=effort,
        window=window,
        stamp=stamp,
        prompt_sha256=str(transcript.get("prompt_sha256", "")),
        total_runs=len(runs),
        failed=len(runs) - len(billed),
        unparseable=len(billed) - len(scored),
        scored=len(scored),
        verdicts=verdicts,
        distractor_bites=bites,
        cost_usd=sum(float(r.get("cost_usd") or 0.0) for r in billed),
    )


def _status(claimed: Locality, structural: Locality, hits: int, scored: int) -> Verdict:
    if scored == 0:
        return Verdict.UNRUN
    if hits > 0:
        if structural is Locality.CROSS_FILE:
            # The reviewer named a defect in a file the floor never contained.
            # Either it inferred the path, or the matcher is wrong. Neither is
            # something this module should resolve on its own.
            return Verdict.CONFLICT
        return Verdict.REFUTED if claimed is Locality.CROSS_FILE else Verdict.CONSISTENT
    if claimed is Locality.CROSS_FILE:
        # Failure to refute, not proof — and a handful of quiet runs is not even
        # much of a failure to refute.
        return Verdict.SURVIVED if scored >= MIN_RUNS_TO_VERIFY else Verdict.UNDERPOWERED
    return Verdict.CONSISTENT


# --- reporting ---------------------------------------------------------------


def manifest_block(verdict: DefectVerdict) -> str:
    """The `locality:` block to paste into `fixture.yaml`, or why there isn't one.

    Printed rather than written. A measurement whose matcher is explicitly crude
    should not be editing the answer key it is measured against.
    """
    if verdict.status is Verdict.REFUTED:
        return (
            f"    # {verdict.defect_id}: cross_file is REFUTED — a no-tools reviewer\n"
            f"    # found it {verdict.hits}/{verdict.scored} times, so the evidence was\n"
            f"    # inside the floor. The diff's shape allows no closer than\n"
            f"    # {verdict.structural.value!r}; choose that or 'touched_file' by hand and\n"
            f"    # say in NOTES.md what leaked, so the next fixture avoids it."
        )
    if verdict.status is Verdict.CONFLICT:
        return (
            f"    # {verdict.defect_id}: CONFLICT — matched by a reviewer that was never\n"
            f"    # shown {verdict.defect_id}'s file. Read the transcript before touching\n"
            f"    # the tag; the matcher is the more likely culprit."
        )
    if verdict.status in (Verdict.UNDERPOWERED, Verdict.UNRUN):
        return (
            f"    # {verdict.defect_id}: not settled — {verdict.scored} scored run(s), "
            f"{MIN_RUNS_TO_VERIFY} needed.\n"
            f"    # Leave verified: false and run more."
        )
    if verdict.saturated:
        return (
            f"    # {verdict.defect_id}: every run found it ({verdict.hits}/"
            f"{verdict.scored}). The fixture is\n"
            f"    # too easy and gets reworked; do not record a tag from this run."
        )
    tier = verdict.resolved
    if tier is None or tier is not verdict.claimed:
        return f"    # {verdict.defect_id}: claimed tier not supported; decide by hand."
    return (
        "    locality:\n"
        f"      tier: {tier.value}\n"
        "      verified: true\n"
        f"      evidence: {verdict.evidence}"
    )


def print_report(
    fixture: Fixture, report: LocalityReport, transcript: dict[str, Any]
) -> None:
    print(f"\nRun accounting — {report.fixture_id}")
    print("─" * 40)
    print(f"{report.total_runs:>4} run(s) on file")
    print(f"{report.failed:>4} failed outright — excluded everywhere")
    print(f"{report.unparseable:>4} returned unparseable output — findings unknown, not empty")
    print(f"{report.scored:>4} scored")
    print(f"  spend: ${report.cost_usd:.4f}   model: {report.model}   effort: {report.effort}")
    print(f"  prompt digest: {report.prompt_sha256 or 'unrecorded'}")

    print("\nPer-run findings")
    print("─" * 40)
    items = ground_truth(fixture)
    for index, record in enumerate(transcript.get("runs", [])):
        if record.get("failed"):
            print(f"  run {record.get('run_index', index):>2}: FAILED {record.get('error')}")
            continue
        if record.get("parse_error"):
            print(
                f"  run {record.get('run_index', index):>2}: "
                f"PARSE ERROR {record['parse_error']}"
            )
            continue
        findings = record.get("findings", [])
        print(f"  run {record.get('run_index', index):>2}: {len(findings)} finding(s)")
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            target, distance = attribute(finding, items, report.window)
            where = (
                f"→ {target.id} (±{distance})" if target is not None else "→ unattributed"
            )
            print(
                f"        {normalise_path(finding.get('file'))}:"
                f"{finding.get('start_line')}-{finding.get('end_line')} "
                f"{where}\n"
                f"          {str(finding.get('message', ''))[:120]}"
            )

    print("\nLocality verdicts")
    print("─" * 40)
    for verdict in report.verdicts:
        rate = verdict.detection_rate
        rate_text = "n/a" if rate is None else f"{rate:.2f}"
        print(
            f"  {verdict.defect_id}: {verdict.status.value.upper()}  "
            f"claimed={verdict.claimed.value} structural={verdict.structural.value} "
            f"detection={rate_text} ({verdict.hits}/{verdict.scored})"
        )
        if verdict.hand_labelled:
            print(f"      {verdict.hand_labelled} run(s) hand-labelled, overriding the matcher")
        if verdict.saturated:
            print(
                "      ⚠ SATURATED — found by every run. A fixture at the recall ceiling\n"
                "        cannot show whether tools help. Rework it."
            )
        print(manifest_block(verdict))

    print("\nDistractor bites")
    print("─" * 40)
    if not report.distractor_bites:
        print("  none declared")
    for name, count in sorted(report.distractor_bites.items()):
        # Only worth saying once there are enough runs for silence to mean
        # something. At n=2 every distractor looks inert.
        note = (
            "  ← never bitten; it is not doing its job"
            if count == 0 and report.scored >= MIN_RUNS_TO_VERIFY
            else ""
        )
        print(f"  {name}: {count}/{report.scored}{note}")

    print("\n" + ("SETTLED" if report.settled else "NOT SETTLED"))


# --- cli ---------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure a fixture's locality tags.")
    parser.add_argument("fixture", type=Path, help="fixture root (the dir holding repo/)")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high", choices=EFFORT_LEVELS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--run-timeout",
        type=float,
        default=300.0,
        help="per-request deadline; a stall must cost one run, not the batch",
    )
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument(
        "--from",
        dest="from_transcript",
        type=Path,
        help="re-score a stored transcript instead of running. Costs nothing.",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help=(
            "JSON map of '<run_index>:<defect_id>' -> bool, overruling the matcher "
            "for those runs. The verdict records how many were labelled."
        ),
    )
    parser.add_argument("--out", type=Path, default=Path("results/locality"))
    return parser.parse_args(argv)


def measure(fixture: Fixture, args: argparse.Namespace) -> dict[str, Any]:
    """Runs the reviewer `args.runs` times and returns the transcript."""
    client = anthropic.Anthropic()
    task = review_task(fixture)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    print(
        f"measuring locality on {fixture.id}: {args.runs} single-shot run(s), "
        f"{args.model}, effort={args.effort}, no tools"
    )
    records: list[dict[str, Any]] = []
    for index in range(args.runs):
        record, error = run_with_retries(
            lambda: run_once(
                client,
                fixture,
                task,
                model=args.model,
                effort=args.effort,
                max_tokens=args.max_tokens,
                timeout=args.run_timeout,
            ),
            args.retries,
            f"run {index}",
        )
        if record is None:
            # Recorded, not skipped: a gap would let a later reader mistake a
            # shrunken n for the intended number of runs.
            records.append({"run_index": index, "failed": True, "error": error})
            print(f"   run {index}: FAILED after {args.retries} retries")
            continue
        record["run_index"] = index
        records.append(record)
        print(
            f"   run {index}: {len(record['findings']):2d} finding(s)  "
            f"${record['cost_usd']:.4f}"
            + (f"  PARSE ERROR {record['parse_error']}" if record["parse_error"] else "")
        )

    return {
        "measurement": "locality-verification",
        "fixture": fixture.id,
        "fixture_root": str(fixture.root),
        "model": args.model,
        "effort": args.effort,
        "max_tokens": args.max_tokens,
        "reviewer": "single-shot correctness, floor context, no tools",
        "prompt_sha256": prompt_digest(task),
        "stamp": stamp,
        "runs": records,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = load_fixture(args.fixture)

    if args.from_transcript:
        transcript = json.loads(args.from_transcript.read_text(encoding="utf-8"))
        # Re-scoring is free, which makes it easy to point at the wrong pair.
        # Scoring one fixture's runs against another's answer key would produce
        # a full, plausible report about nothing.
        recorded = transcript.get("fixture")
        if recorded and recorded != fixture.id:
            raise LocalityError(
                f"{args.from_transcript} holds runs for {recorded}, not {fixture.id}"
            )
        path = args.from_transcript
    else:
        transcript = measure(fixture, args)
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"{fixture.id}-{transcript['stamp']}.json"
        path.write_text(
            json.dumps(transcript, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )

    labels: dict[str, bool] = {}
    if args.labels:
        raw = json.loads(args.labels.read_text(encoding="utf-8"))
        labels = {k: bool(v) for k, v in raw.items() if not k.startswith("_")}

    report = classify(fixture, transcript, window=args.window, labels=labels)
    print_report(fixture, report, transcript)
    print(f"transcript: {path}")
    return 0 if report.settled else 1


if __name__ == "__main__":
    sys.exit(main())
