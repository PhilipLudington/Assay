# TS-0001 — provenance and authoring record

**Authored:** 2026-07-26, by hand. Not mined from a real repository — see
*Bias* below, which the corpus README repeats for every fixture.

## The repository

`@acme/stockroom`, an invented warehouse inventory and reservation service:
43 TypeScript source files, `strict` plus `noUncheckedIndexedAccess`, no
runtime dependencies. Size was chosen from the Phase 0 pilot, which measured
how much of a repo an agentic reviewer actually reads: 79% at 8 files, 32% at
25, 23% at 50. Below ~25 files tool use degenerates into reading everything,
and the agentic ceiling stops measuring navigation.

The domain matters for the defect: the ledger counts **units**, not promises.
An inventory row knows twelve units are held; it does not know *which*
reservation holds them. That asymmetry is stated in
`src/repositories/inventory-repo.ts` and it is what makes a duplicated release
silent rather than loud.

## The change under review

Adds a background job that expires reservations nobody confirmed inside their
TTL, and registers it. Two files: the new `src/jobs/reservation-sweeper.ts`,
and one import plus one array entry in `src/jobs/registry.ts`.

## The defect

The sweeper returns each line's held units with `InventoryRepo.release`, then
calls `ReservationRepo.markExpired`, which releases those same units again in
its own transaction. `held` is decremented twice per expired reservation, so
availability (`onHand - held`) is overstated from then on and the row
oversells. It never throws, no test that exercises the sweeper in isolation
fails, and the symptom surfaces days later as an oversell with no obvious
cause.

**Why this is realistic.** It is the ordinary shape of a compensating action
that someone else already owns. The sweeper's author read `markExpired` as "set
the status" — which is what the name says — and did the stock movement they
believed was missing. The code they wrote is what a careful person writes when
they have not read the repository they are calling. The three real-world
families this stands in for: releasing a lock a helper already released,
refunding in a handler when the payment service refunds on cancel, and
decrementing a counter that a trigger also decrements.

**Why it is not conspicuous.** The sweeper reads as complete and deliberate:
it takes a bounded batch, releases stock, marks the row, meters both outcomes,
and survives a bad row. Nothing in it is a smell in its own right. The
duplication is only visible against a fact that is not in the file.

## Locality: why `cross_file` is claimed, and what would refute it

The review-context floor is the diff plus the full contents of every file it
touches — here, `reservation-sweeper.ts` and `registry.ts`. The claim is that
neither contains the evidence:

- `registry.ts` is a nine-line factory. It names the sweeper and nothing else.
- The sweeper never mentions what `markExpired` does, and its doc comment
  states the *goal* (units must not stay held) rather than the mechanism, which
  is exactly the misconception that produced the bug.
- The evidence lives in `src/repositories/reservation-repo.ts` (`markExpired`
  releases every line in the same transaction, and says callers must not) and
  is corroborated from the other side by
  `src/repositories/inventory-repo.ts` (`releaseWithin` cannot distinguish a
  duplicate release from a real one). Neither file is touched.

The Phase 0 pilot mis-tagged two of three defects `cross_file` while the author
was actively trying not to, in both cases because the touched file leaked the
invariant in a comment. So the tag here stayed `verified: false` until the
locality-verification step measured it: run the single-shot reviewer with no
tools; if it finds the defect, the defect is not `cross_file`, whatever this
note argues.

Two known ways this claim could fail were recorded before the measurement, so
that it would be read honestly rather than defended:

1. A reviewer can *guess* the shape — "does `markExpired` release the hold?" is
   a reasonable question to ask of that call without reading anything. A guess
   that names the defect counts as finding it. That is the correct scoring
   rule, and if it happens often the tag is wrong.
2. `InventoryRepo.release` and `ReservationRepo.markExpired` being called back
   to back is a two-writes-for-one-event pattern that a suspicious reader may
   flag on principle.

**Measured 2026-07-31: the claim survives. 0/10.** Ten single-shot runs
(`claude-opus-5`, effort `high`, floor context, no tools) and not one named the
double release. Transcript, labels and per-run reasoning:
`results/locality/TS-0001-20260731T170244Z.json`.

Failure mode 2 turned out to be the interesting one, and in a sharper form than
this note anticipated. Every run *did* flag those exact lines — 29 findings
across 10 runs, all in `reservation-sweeper.ts:47-73` — and the proximity
matcher scored the defect found 10/10. Reading the text, all 29 are false
positives. They converge on three concerns, none of which is the seeded defect:

- **Release-before-claim.** Units are released before `markExpired` is called,
  so a concurrent confirm makes `markExpired` return `null` after the stock is
  already back. A real ordering concern — and *not* this defect, because that
  `null` path returns at the status check before `releaseLines` runs, making it
  the one path that releases exactly once.
- **Non-idempotent retry.** A throw partway through the release loop leaves the
  reservation pending, so the next tick re-releases the lines that succeeded.
  Says "double release", but the mechanism is retry-after-partial-failure and
  it needs an exception; the seeded defect fires on the happy path.
- **Summary accounting.** `processed`/`failed` are not incremented on the
  already-settled branch. Unrelated to the defect — and, unlike the other two,
  it survives the defect's fix, which is why it became a declared distractor on
  2026-08-01. See *Distractors* below.

Seven of ten runs recommend "claim via `markExpired` first, then release the
lines" as the fix. Under the seeded defect that reordering still decrements
`held` twice, so a reviewer that had read `reservation-repo.ts` could not
propose it. That is the strongest single piece of evidence that the evidence
really does sit outside the floor.

Failure mode 1 — guessing the shape — did not occur once in ten runs.

## Difficulty: the saturation check

The pilot found the seeded defect in 34 of 34 runs across all three scratch
fixtures. A corpus sitting at the recall ceiling cannot answer whether tools
help, because recall has nowhere to climb, so **a single-shot detection rate of
1.00 makes this fixture an authoring failure and it gets reworked.**

**Observed single-shot detection rate: 0.00 (0/10), 2026-07-31.** The fixture
is not at the recall ceiling. It is at the other end, which is its own thing to
watch: a defect no reviewer ever finds cannot discriminate between reviewers
either, since recall is pinned at zero for all of them. The number worth having
is the agentic rate on the same defect — if tools lift it off zero, this fixture
is doing exactly the job the v1 research question needs. If they do not, it is
too hard rather than too easy and gets reworked for the opposite reason.

That measurement belongs to Phase 2, which owns `AgentReviewer`. Until it
lands, this fixture's *difficulty* is measured only from below.

## Distractors

Four. Three were authored with the fixture; the fourth was declared on
2026-08-01, after measurement showed the code had been carrying it all along.
Each is defensible as correct — the notes in `fixture.yaml` say why — and each
is the kind of finding a reviewer emits when it has nothing better to say.
Their strength is itself a measurement: if no reviewer ever bites, they are
decoration and precision stays trivially near 1.0.

### The authored three are weak

**Measured 2026-07-31.** Across ten single-shot runs, hand-labelled finding by
finding: stale-batch-timestamp **0/10**, logged-and-continued-error **1/10**,
redundant-empty-batch-return **0/10**. All three sit deliberately away from the
defect's lines so a proximity-gated match cannot confuse one for the other, and
all three are close to decoration.

The proximity matcher scored those first two the other way round — 1/10 and 0/10
— and where it agreed on a total it was right by luck rather than by reading.
Neither bite it could see was the one a reader attributes:

- The logged-and-continued bite (run 5) argues that failed reservations are left
  pending with no backoff or dead-letter path — the swallowed-error bait, taken
  squarely — while citing lines 38–46 rather than the catch block at 65–74.
  Proximity filed it nowhere.
- The stale-timestamp "bite" (run 6) sits on the bait's own lines but argues
  that `findDueForExpiry` selects rows without locking them, so two sweepers
  both release the same lines. That is the ordering concern in multi-worker
  dress, not a stale clock, and it was demoted to `other` on 2026-08-01 by the
  test below.

Same lesson as the 10/10 detection false positive, in miniature: where a finding
points and what it is about are different questions.

### The fourth was already in the code

Seven of ten runs objected that a row `markExpired` reports already settled is
counted in neither `processed` nor `failed`. It is the most-bitten piece of bait
in the fixture by a wide margin, and the manifest said nothing about it. It is
now declared as `uncounted-settled-row`. Nothing in `repo/` changed; the answer
key was incomplete, not the tree.

It is also the best distractor here for the question v1 asks, because its
exculpatory evidence is **outside the review floor**. `JobRunSummary` in
`src/jobs/job.ts` defines `processed` as "rows the job successfully dealt with"
and `failed` as "rows it tried and could not" — a row somebody else settled is
neither, and `sweep.completed` already logs `due` beside both counters so the
gap is recoverable. A single-shot reviewer cannot open that file and can only
argue from shape. An agentic one can open it and decline the bait. The bait
mirrors the seeded defect, whose *inculpatory* evidence is out of the floor the
same way.

### Why release-before-claim and non-idempotent retry are *not* distractors

Every run raised both, and an earlier reading of these results (recorded in PLAN)
proposed folding them in as stronger bait. That was wrong, and the reason is
worth keeping as an authoring rule for the rest of the corpus.

**The test: apply the stated fix and see what is left.** The fix is deleting the
sweeper's release loop.

| Concern | After the fix | Verdict |
|---|---|---|
| Release-before-claim | markExpired returning `null` releases nothing; no ordering left to get wrong | dies with the fix |
| Non-idempotent retry | no partial release to retry over; markExpired is one transaction | dies with the fix |
| Uncounted settled rows | the branch still counts nothing | **survives** |

A concern that dies with the fix is the seeded defect's own harm under a
different description — not an independent fact about the code. Declaring it a
distractor would assert in the answer key that a reviewer flagging that line is
*wrong*, when it is right about the line and wrong about the mechanism. `other`
says exactly that and is the correct label. Only a concern that survives the fix
can carry a not-a-defect argument of its own, which is what a distractor is.

The rule also demotes run 6's stale-timestamp attribution, which the labels file
had already flagged as its most arguable call: the double release it names is
the release loop's, so it dies with the fix too.

Neither relabelling moves precision. A distractor bite and an unseeded finding
are both false positives, so this fixture stays at 0/29 exactly; only the bite
tally moves. Labels and the full argument:
`results/precision/TS-0001-20260731T170244Z.finding-labels.json`.

### What is still not known

Single-shot precision here is 0.00 and cannot go lower, so no rework of the bait
can move this fixture's single-shot score. The number that will move is the
agentic one, which Phase 2 owns. If agentic precision comes back near 1.0 — the
reviewer declining every bait — the bait is too weak after all and authored bait
gets added to `repo/`, which is a tree change and re-opens the locality
measurement. Nothing is added speculatively before that number exists.

## Precision: measured 2026-08-01, and it is the floor

Over the same ten runs, hand-labelled finding by finding:
**0 true positives in 29 findings.** Per-run precision was 0.00 in all ten, so
the mean is 0.00 with no run-to-run variation at all; pooled and given an exact
interval it is `[0.00, 0.12]`. Labels and their reasoning:
`results/precision/TS-0001-20260731T170244Z.finding-labels.json`.

This is the mirror of the saturation problem and deserves the same suspicion. A
fixture where the single-shot reviewer scores zero on *both* axes cannot
discriminate between reviewers on its own — there is nothing below zero for a
worse reviewer to reach. What makes it useful rather than useless is entirely
the agentic number, which Phase 2 owns: if tools lift recall off zero here, the
fixture is doing exactly the job the v1 question needs, and precision has
somewhere to move too. If they do not, this fixture is too hard and gets
reworked, and the fact that its precision was also pinned at zero is part of the
evidence for that.

## Authoring checks

- Both trees typecheck clean under the fixture's own `tsconfig.json`: the
  post-change tree in `repo/`, and the pre-change tree reconstructed by
  reversing `change.patch`.
- `change.patch` reverses cleanly against `repo/` (`git apply --reverse
  --check`), which is what the loader asserts on every load.
- `repo/` carries no VCS history, no symlinks, and no copy of this file or of
  `fixture.yaml`; `assay.corpus.loader` refuses the fixture otherwise.

## Bias

Hand-authored by the same person who wrote the harness, which is the corpus's
main known weakness: the defects are the ones I thought to seed, expressed in
the code I would write. The README states this before any percentage appears.
