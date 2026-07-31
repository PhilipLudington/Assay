# Locality-verification transcripts

Evidence that a fixture's `locality` tag was **measured**, not argued.

DESIGN makes locality a measurement because the Phase 0 pilot proved author
judgement insufficient: two of its three defects were authored `cross_file` and
both turned out reachable from the review floor — once via a class comment in
the touched file restating the broken invariant, once via a visible asymmetry
with sibling handlers. Neither fixture looked wrong on inspection, and the
author was actively trying to avoid exactly that. Because the headline result is
reported *broken out by locality*, a bad tag does not add noise; it produces a
confidently wrong answer.

Each file is one batch of single-shot reviewer runs against one fixture: floor
context only (the diff plus the full contents of every file it touches), no
tools. Produced by:

    .venv/bin/python -m assay.corpus.locality corpus/ts/<fixture> --runs 10

Re-scoring is free and makes no model calls, so a changed matcher or window
never costs a re-run:

    .venv/bin/python -m assay.corpus.locality corpus/ts/<fixture> \
        --from results/locality/<file>.json --window 6

## What the measurement can and cannot say

It refutes `cross_file` and nothing else.

- **Found** by any no-tools run → the evidence was inside the floor, so the tag
  is not `cross_file`. It does **not** distinguish `local` from `touched_file`;
  the floor contains both the hunks and the whole touched file. That distinction
  is structural and `Fixture.structural_locality` already bounds it.
- **Not found** in *n* runs → `cross_file` is *not refuted*. That is a failure
  to refute, not proof, which is why a claim is only reported settled once *n*
  reaches `MIN_RUNS_TO_VERIFY` (10). Below that the verdict is `UNDERPOWERED`
  and the tag stays `verified: false`.

## Verdicts

Only `SURVIVED` and `CONSISTENT` exit 0, and only when the defect is not
saturated.

| Verdict | Means |
|---|---|
| `SURVIVED` | Claimed `cross_file`, and enough runs failed to find it. The tag stands, on a failure to refute. |
| `CONSISTENT` | Not claimed `cross_file`. This measurement can neither confirm nor refute such a tag; the structural bound already constrains it. |
| `REFUTED` | Claimed `cross_file`, and a no-tools run found it. The tag is wrong and the fixture's `NOTES.md` should record what leaked. |
| `CONFLICT` | A finding matched a defect in a file the diff never showed. Read the transcript before touching the tag — the matcher is the likelier culprit. |
| `UNDERPOWERED` | Claimed `cross_file`, unfound, but too few scored runs to call it. Run more. |
| `UNRUN` | No scoreable runs. |

## The saturation check, which rides along for free

The pilot found its seeded defect in 34 of 34 runs. A corpus at the recall
ceiling cannot answer whether tools help, because recall has nowhere to climb —
so a **detection rate of 1.00 is an authoring failure** and the fixture gets
reworked, regardless of what the locality verdict says. The observed rate is
copied into the fixture's `NOTES.md` alongside its provenance.

Distractor bites are reported for the same reason: bait no reviewer ever takes
is not doing its job, and precision measured against it conveys nothing.

## Reading a transcript

- `runs[].findings` — what each run reported. Re-attributed to ground truth on
  every scoring pass, so the stored file never carries a verdict of its own.
- `runs[].parse_error` — the finding list is **unknown**, not empty. Such a run
  leaves the detection rate but stays in the spend: it cost money, and scoring
  it as "found nothing" would depress a rate.
- `runs[].failed` — the run produced nothing and is excluded everywhere. It is
  *recorded* rather than skipped, because a gap in the transcript would let a
  later reader mistake a shrunken *n* for the intended number of runs.
- `prompt_sha256` — a digest of the exact floor and reviewer instructions.
  Locality is a property of *this reviewer against this floor*; if either
  changes, the stored verdict describes a reviewer that no longer exists and the
  honest response is to re-measure rather than keep quoting the old number.

## Overruling the matcher

The matcher is deliberately crude — Phase 3 owns the real proximity gate and the
semantic judge. A finding is attributed to the *nearest* ground-truth item in
the same file, defect or distractor, and counts as a detection only if the
nearest one is the defect. Nearest-wins rather than a plain window because
`TS-0001`'s distractors sit seven lines from its defect, so a fixed ±15 window
would score a distractor bite as a detection.

Pass `--labels labels.json` — a map of `"<run_index>:<defect_id>"` to a boolean —
to overrule it by hand. The verdict reports how many runs were labelled, so a
hand-labelled result never reads the same as a matched one.

## Runs on file

| Date | Fixture | Verdict | Detection | Notes |
|---|---|---|---|---|
| 2026-07-31 | TS-0001 | SURVIVED | 0.00 (0/10) | `cross_file` verified. **Hand-labelled — the matcher scored 10/10 and every match was a false positive.** All 29 findings landed on the defect's own lines while describing ordering, retry-idempotency and summary-accounting concerns; none identified that `markExpired` releases the same units. $0.3974. |

### The matcher's 10/10, and why it is a Phase 3 input

DESIGN predicted line matching would fail by producing **false negatives** — "a
reviewer can correctly identify a defect while citing the call site rather than
the guard". TS-0001 produced the inverse and produced it at full strength: ten
runs out of ten described a *different* bug at the right lines, and proximity
alone could not tell the difference. Nearest-wins attribution did not help,
because the competing ground-truth items (the distractors) were further away
than the defect the findings were not about.

Two things follow. Locality verification cannot rest on proximity alone, which
is why `--labels` exists and why this fixture's tag records that it was
hand-labelled. And Phase 3's judge has a concrete, adversarial validation case
waiting for it: a semantic judge that scores these 29 findings as matches is not
fit to adjudicate the corpus, and the pairs are already on disk.
