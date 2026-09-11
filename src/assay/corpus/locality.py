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
sit as close as 1 line from the defect, and a fixed ±15 window would score a
distractor bite as a detection. Ties go to the defect: over-counting detections
can only *refute* a `cross_file` claim, and a false `cross_file` claim is the
failure this step exists to catch, so the bias points away from it. Pass
`--labels` to overrule the matcher by hand; the verdict records how many runs
were labelled.

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
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
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
#: on purpose: `TS-0001`'s nearest distractor is 1 line from the defect, so a
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
    1 line away — so a window wide enough to tolerate a reviewer citing the
    call site instead of the guard would also swallow a distractor bite and
    score it as a detection.

    Attribution is still only a filter. On `TS-0001` it files 5 of the 7
    uncounted-settled-row bites correctly and leaves 2 on the defect, because a
    finding that spans both ranges ties and the tie goes to the defect. The
    label files are what settle a bite; this only narrows where to look.

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


def _key_index(key: str) -> int | None:
    """The run index a label key names, or `None` when its head is not one.

    `str(index) != head` rejects `" 3"`, `"03"` and `"+3"`: a key that only looks
    like an index is a typo, not a run. Catching `ValueError` here is also what
    keeps a key written with no run prefix at all — a plausible hand-edit —
    inside the module's error contract, since `classify` wraps `run_indices` and
    not this path.
    """
    head, _, _ = key.partition(":")
    try:
        index = int(head)
    except ValueError:
        return None
    return index if str(index) == head else None


def _shift_key(key: str, offset: int) -> str | None:
    """The same key with its run index moved by `offset`, or `None` if it has none."""
    index = _key_index(key)
    if index is None:
        return None
    _, _, defect_id = key.partition(":")
    return run_key(index + offset, defect_id)


def partition_runs(
    runs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splits a transcript's runs into `(billed, scored)`.

    Three tiers, not two. A run that failed outright produced nothing and is
    excluded everywhere. A run whose structured output would not parse still
    cost money and still has to appear in the spend, but its finding list is
    *unknown* rather than empty — scoring it as "found nothing" would depress
    every rate computed over it.

    Defined once, here, because `assay.eval.precision` scores the same
    transcripts. Two implementations of "which runs count" is how a scored-run
    denominator comes to differ between two reports of the same batch.
    """
    billed = [r for r in runs if not r.get("failed")]
    scored = [r for r in billed if not r.get("parse_error")]
    return billed, scored


def _recorded_run_index(record: dict[str, Any], position: int) -> int | None:
    """The record's `run_index`, refused if present and not an integer.

    `None` when the record carries none, which is not an error here: the two
    callers have different answers for a record that recorded no index, and
    neither of them is "guess".

    The refusal lives in one place because it has to hold for every record on
    file. `run_indices` below validates the records that get *scored*, and
    `classify`'s set of unscoreable indices used to filter a non-integer out with
    `isinstance` and say nothing — so `3.0` was an error on a scored record and
    invisible on the unparseable one beside it, and a label naming that position
    then hard-failed as nonsense instead of being reported as unhonourable. A
    rule enforced in one of two entry points is the shape of bug this module
    keeps closing.
    """
    if "run_index" not in record:
        return None
    raw = record["run_index"]
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(
            f"run_index must be an integer, got {raw!r} at position {position} "
            "— an identity is taken as written or not at all, because coercing "
            "one silently changes which run a label scores"
        )
    return raw


def _unscored_run_indices(runs: list[dict[str, Any]]) -> set[int]:
    """The recorded indices of runs that exist but cannot be scored.

    Only a *recorded* index counts — see `assert_labels_match` on why a record
    that never recorded one is not given an invented position here.
    """
    indices: set[int] = set()
    for position, record in enumerate(runs):
        if not (record.get("failed") or record.get("parse_error")):
            continue
        recorded = _recorded_run_index(record, position)
        if recorded is not None:
            indices.add(recorded)
    return indices


def run_indices(records: list[dict[str, Any]]) -> list[int]:
    """The `run_index` of each record, refusing a batch that repeats one.

    Every hand label in this project is keyed by run index — `<run>:<defect>`
    here, `<run>:<finding>` in `assay.eval.precision` — so a repeated index is
    not a cosmetic duplicate. It makes two runs share one key, and one human
    judgement is then counted once per run that collides with it: a label
    written about run 0 scores run 0's twin as well.

    Neither module's existing guards see it. Precision's "unlabelled finding"
    check finds the key present, and its "label names a finding this batch does
    not have" check builds a *set* of keys, which collapses the duplicates back
    down. So the batch scores clean and reports a rate nobody measured.

    The trigger is mundane: two batches concatenated, which is how a re-run gets
    appended to a transcript. Refused here rather than in either caller for the
    same reason `partition_runs` lives here — one definition of which run is
    which for the two *scorers*, or the two reports of one batch disagree about
    it.

    "For the two scorers" is meant literally, and is not yet the whole story:
    `print_report` below derives its own run numbers, and the number it prints
    is what a human copies into a `--labels` file. It prints the recorded
    `run_index` where there is one — which is every transcript `measure` writes,
    so the two agree in practice — but *falls back* to the record's position
    among **all** runs, where this function falls back to the position among the
    **scored** ones. On a record carrying no `run_index` the two disagree. That
    divergence predates this helper and is queued in PLAN.md; until it is
    closed, this function is the single definition of the keys labels are
    *matched* against, not of the run numbers a reader is *shown*.
    `assert_labels_match` below narrows the blast radius but does **not** close
    it. Which keys that check refuses is stated once, in its docstring under
    "Where a mis-keyed label ends up"; it is not restated here, because
    restating it is how this module's two descriptions of the boundary came to
    disagree. What becomes of a copied *number* is not stated there either — it
    turns on this divergence, not on that boundary. The case that survives the
    narrowing is the silent one. Four records with
    no `run_index`, record 0 unparseable: `print_report` prints runs 0-3, this
    function keys the three scored records 0-2, and a label written for the run
    printed as `2` passes the check and scores the record printed as `3`. One
    human judgement counted against the wrong run, with `hand_labelled` reading
    1 as though it had been honoured. Only closing the divergence fixes that.

    Falls back to position when a record carries no `run_index` at all, which is
    what both callers did before this check existed. Mixed presence is exactly a
    way to collide, and it is caught by the same rule.

    An index that is present but is not an integer is **refused, not coerced**.
    Coercion is what makes a wrong number silent: `int(3.0)` re-keys the run from
    `3.0` to `3`, so a label file written `"3.0:TS-0001-d1"` stops matching. That
    now raises through `assert_labels_match` rather than dropping the human's
    judgement in silence, but the rule stays reject-not-coerce: an identity that
    is re-keyed under the reader's feet is a wrong key made to look right, and
    the point is to keep it as written. `True` keying as `1` is the same hazard —
    `bool` is an `int` subclass,
    so it is excluded explicitly. Refusing also keeps a JSON `null` inside each
    caller's error contract, where a bare `TypeError` from `int()` would escape
    both wraps.
    """
    indices: list[int] = []
    for position, record in enumerate(records):
        recorded = _recorded_run_index(record, position)
        indices.append(position if recorded is None else recorded)
    counts = Counter(indices)
    repeated = sorted(index for index, count in counts.items() if count > 1)
    if repeated:
        raise ValueError(
            f"run_index repeated in this batch: {repeated} — labels are keyed by "
            "run index, so one label would score every run that shares it"
        )
    return indices


def assert_labels_match(
    labels: dict[str, bool],
    indices: list[int],
    defects: list[GroundTruth],
    unscored: set[int] | None = None,
) -> list[str]:
    """Refuses a nonsense label key; reports one that is merely unhonourable.

    Returns the keys that name a real run this batch could not score — a run
    that failed or came back unparseable. Those are *not* errors: the batch
    still scores every run it can, and the caller surfaces them so the reader
    learns their judgement went unused. Everything else raises.

    `classify` used to look each key up, miss, and fall through to the matcher,
    so a `--labels` file that named nothing changed nothing and *said* nothing.
    That is the quiet half of every keying mismatch this module has had: a
    repeated index or a coerced one is only dangerous because the label it
    displaces disappears without a word.

    Measured on `TS-0001`'s own shipped labels, which is why a nonsense key
    raises rather than warns. Typing `-dl` for `-d1` drops all ten human
    judgements and turns
    the published `SURVIVED cross_file 0/10` into `REFUTED 10/10` — the crude
    matcher's verdict, which the same ten labels exist to overrule. Numbering the
    runs from 1, as a reader copying them off a report would, drops nine and
    reports `REFUTED 1/10`. In both cases the only trace is `hand_labelled`
    falling below the number of labels the file holds, and nothing reads it.

    `assay.eval.precision` splits this check in two, because its keys and its
    values carry different things: `load_labels` validates a label against the
    fixture's answer key, and `score` refuses keys naming findings the batch does
    not have. A locality key carries both halves at once
    (``<run_index>:<defect_id>``), so one set difference answers both.

    Keys prefixed with `_` are commentary and are skipped, the same convention
    `assay.eval.precision.load_labels` documents: a label file is where the
    reasoning behind a hand judgement lives, and it has to sit beside the labels
    it explains. The skip belongs here rather than only in `main`, which strips
    them on the way in, because the shipped label files carry commentary and
    every other caller — `tests/test_shipped_results.py` included — hands
    `classify` the file as read. A rule enforced in one of two entry points is
    the shape of bug this module keeps closing.

    **Why an unhonourable key is not an error.** Refusing every unmatched key
    was the first shape of this check, and it was too blunt: `partition_runs`'
    third tier says a run can be billed and still unscoreable, so one re-run
    coming back unparseable made the *shipped* label file refuse its own
    transcript, and nine good runs with nine good labels produced nothing. A
    key naming such a run is not a typo — the run is real, the human's
    judgement about it is real, and only the scoring is impossible. So it is
    returned, counted nowhere, and printed; `hand_labelled` falls short on its
    own, which is the signal the reader already knows how to read.

    **Where a mis-keyed label ends up.** This is the module's one statement of
    this check's boundary; the other sites point here instead of restating it,
    because every restatement so far has drifted from the code. A key that does
    not name the run it was written about reaches exactly one of three
    outcomes, and the conditions are what separate them:

    1. **Absorbed silently.** Its index is a *scored* index and its defect id is
       in the answer key, so it matches as written and scores the wrong run. It
       never becomes a candidate, so nothing below sees it. This is the open
       case recorded in `PLAN.md` under the `print_report` numbering line, and
       the only outcome that is silent.
    2. **Reported as unhonourable.** Its index is not scored, a failed or
       unparseable record *recorded* that index, and its defect id is in the
       answer key. All three conditions bind, and the middle one is narrower
       than it looks: `_unscored_run_indices` above contributes an index only
       for a record that recorded one, because inventing a position for a
       record that did not is the guesswork that makes `print_report`'s
       numbering diverge from this module's, and one such divergence is enough.
    3. **Refused as nonsense.** Everything else — which is the whole remainder,
       not only a key past the end: an index that neither the scored set nor
       the recorded unscoreable set holds, *or* a defect id outside the answer
       key at any index whatsoever.

    Those three conditions are the whole boundary, and they are stated over key
    *values*. Where a number a reader *copied off the report* lands is a
    different question, and this list does not answer it: `print_report`
    numbers a record that recorded no `run_index` by its position among **all**
    runs, where `run_indices` above keys by position among the **scored** ones,
    so from the first such record onward the printed number runs ahead of the
    key. A copied one reaches whichever of the three outcomes its value earns
    — outcome 1, the silent one, included. Which one it earns is not enumerable
    here while that divergence is open (`PLAN.md`, the `print_report` numbering
    line); closing it is what would make a copied number safe, and nothing in
    this function can.

    Over those sits one raise decided on the key set rather than the key: a
    label file whose keys, shifted by one, reproduce the scored index set
    exactly — every scored index claimed and nothing else. A file off by one
    over only *part* of the batch is not that set, so it is not refused **as a
    shift** — which is not the same as being accepted, since each of its keys
    still lands in one of the three outcomes above.

    **Why the uniform shift is a case of its own.** It is a property of the key
    set, not of any key in it, so deciding absorption one key at a time cannot
    see it. Numbering the runs from 1 — the hazard this check was built for —
    can put the displaced top key on an index that could not be scored, where
    reporting that one as unhonourable leaves every key below it honoured
    against the run next to the one it was written about, and the shortfall in
    `hand_labelled` explained away by the warning the report prints for it. So
    the set is tested for a constant ±1 shift before anything is absorbed, and
    only when something failed to match as written: a file whose keys all match
    is a file that is not shifted. The shifted keys must cover the scored index
    set *exactly* — a proper subset is not evidence of a shift, because a correct
    file labelling the top of the range plus the unscoreable run above it also
    shifts wholly into the accepted set, and refusing that would override
    outcome 2. Two keys are the least that can show a *constant* shift; a
    lone key cannot be told apart from a judgement about a run that could not be
    scored, and that one is reported.

    **That rescue is partial, and where it fails is the honest part.** It holds
    while the shifted keys fall short of the scored set — some scored index left
    unclaimed, or a shifted key that is not an expected key at all. When they
    reproduce the scored set *entire*, the two readings are indistinguishable
    here, and the code resolves the ambiguity against the correct file: it
    raises. The discriminator is coverage of the scored set, not the size or
    the shape of the batch. Probed: scored `[0,1]` with run 2 unscoreable and
    keys `1,2` raises `keyed one high`, and
    `test_a_whole_file_off_by_one_is_refused_not_absorbed` pins that identical
    input as the hazard this check exists to refuse; keys `2,3` over scored
    `[0,1,2]` leave index 0 unclaimed and are accepted with the top key
    reported, and so are keys `2,3` over a *holed* scored `[0,2]`, where the
    shift lands on an index the batch never scored. Both readings of the
    refused shape are real; what this docstring must not do is promise the
    correct one is always rescued. Typing `-dl` for
    `-d1` still raises on its own, because no shift makes a defect id known.

    An index is only matched against `unscored` when it round-trips through
    `str(int(...))`; a key whose head does not is outcome 3 like any other.
    """
    labelled = [key for key in labels if key[:1] != "_"]
    expected = {run_key(index, defect.id) for index in indices for defect in defects}
    candidates = sorted(key for key in labelled if key not in expected)
    if not candidates:
        return []

    if len(labelled) > 1:
        for offset in (1, -1):
            shifted = [_shift_key(key, offset) for key in labelled]
            if any(key is None or key not in expected for key in shifted):
                continue
            # Containment is not enough: a correct label file whose keys sit at
            # the top of the scored range, with one on the unscoreable run above
            # them, also shifts wholly *into* `expected`. Requiring the shifted
            # keys to reproduce the scored set *entire* is what tells the two
            # apart, and is the only thing the message below can honestly claim.
            # It does not tell them apart in every batch — see the docstring's
            # "That rescue is partial" for the shape it still refuses.
            if {_key_index(key) for key in shifted if key is not None} != set(indices):
                continue
            raise LocalityError(
                f"every one of these {len(labelled)} label(s) is keyed one "
                f"{'high' if offset == -1 else 'low'}: adding {offset:+d} to each "
                f"index reproduces this batch's scored indices {sorted(indices)} "
                "exactly — every one of them, and nothing else. That is the "
                "whole-file off-by-one this check exists for."
                + (
                    " Numbering the runs from 1, as a reader copying them off the "
                    "report would, is how it usually arises."
                    if offset == -1
                    else ""
                )
                + " It is refused as a set because key by key it is invisible: at "
                "least one key falls outside the scored set, where it is reported "
                "as unhonourable or refused as nonsense depending on what it "
                "names, while every other key is honoured against the run next to "
                "the one it was written about."
            )

    known = {defect.id for defect in defects}
    unscored = unscored or set()
    unhonourable: list[str] = []
    unmatched: list[str] = []
    for key in candidates:
        _, _, defect_id = key.partition(":")
        index = _key_index(key)
        names_a_real_run = index is not None and index in unscored
        if names_a_real_run and defect_id in known:
            unhonourable.append(key)
        else:
            unmatched.append(key)

    if not unmatched:
        return unhonourable

    # The *set*, never `min-max`. A scored-run index set has a hole in it
    # whenever a run failed or came back unparseable, which `partition_runs`'
    # three tiers guarantee recurs — and a range printed over that hole names
    # the very index it is rejecting, leaving the reader nothing to act on.
    scored = f"{sorted(indices)}" if indices else "none — no run scored"
    raise LocalityError(
        f"{len(unmatched)} label(s) name nothing in this batch: {unmatched[:8]}"
        + (" ..." if len(unmatched) > 8 else "")
        + f" — a key is '<run_index>:<defect_id>' over scored run indices "
        f"{scored} and defects {sorted(defect.id for defect in defects)}. Each "
        "key listed above names an index that is in neither list, or a defect "
        "that is not in the answer key. A label for a run that failed or did "
        "not parse is absent from this list only when that run recorded a "
        "`run_index` and the key's defect id is in the answer key — that one is "
        "reported as unhonoured and the rest of the batch still scores. "
        "Otherwise it is listed above like any other, and the defect id or the "
        "missing index is why."
    )


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
    #: Label keys naming a real run this batch could not score. Not an error and
    #: not counted in `hand_labelled` — reported so a judgement never goes
    #: unused in silence, which is the hole this module keeps closing.
    unhonourable_labels: list[str] = field(default_factory=list)

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

    # Three tiers, not two — see `partition_runs`. Scoring an unparseable run as
    # "found nothing" would depress detection and could turn a refutable
    # cross_file claim into a surviving one.
    billed, scored = partition_runs(runs)
    try:
        indices = run_indices(scored)
        # The runs that exist — billed, or failed — but cannot be scored. The
        # same integer refusal applies to them: a rule that held only for the
        # scored records would make `3.0` an error on one record and invisible
        # on the unparseable one beside it.
        unscored = _unscored_run_indices(runs)
    except ValueError as error:
        raise LocalityError(str(error)) from error

    # `run_indices` de-duplicates within the scored records only, which leaves
    # one index claimed by both a scored run and an unscoreable one. Both build
    # the same label key, so a judgement about the run that produced nothing is
    # honoured against the one that scored — silently, because the key is in
    # `expected` and never reaches the unhonourable list.
    shared = sorted(unscored & set(indices))
    if shared:
        raise LocalityError(
            f"run_index {shared} names both a scored run and one that failed or "
            "did not parse — labels are keyed by run index, so a judgement about "
            "the run that produced nothing would be honoured against the one "
            "that scored, and reported nowhere. Two batches concatenated is how "
            "this arises."
        )

    items = ground_truth(fixture)
    defects = [item for item in items if item.is_defect]
    unhonourable = assert_labels_match(labels, indices, defects, unscored)

    hits: dict[str, int] = {item.id: 0 for item in defects}
    labelled: dict[str, int] = {item.id: 0 for item in defects}
    bites: dict[str, int] = {item.id: 0 for item in items if not item.is_defect}

    for index, record in zip(indices, scored, strict=True):
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
            key = run_key(index, target_defect.id)
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
        unhonourable_labels=unhonourable,
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
    if report.unhonourable_labels:
        # Loud, next to the run accounting that explains it, because the whole
        # point is that a human judgement must never go unused in silence.
        print(
            f"  ⚠ {len(report.unhonourable_labels)} hand label(s) could not be "
            "honoured — the run they name failed or did not parse, so it is "
            "scored nowhere:"
        )
        for key in report.unhonourable_labels:
            print(f"      {key}")
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
