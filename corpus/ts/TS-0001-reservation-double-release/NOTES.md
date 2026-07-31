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
  already-settled branch. Unrelated.

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

Three, all in the new file, all deliberately away from the defect's lines so a
proximity-gated match cannot confuse one for the other: a batch timestamp
sampled once (check-then-act bait), a caught-logged-and-continued failure
(swallowed-error bait), and a redundant early return on an empty batch
(dead-code bait). Each is defensible as correct — the notes in `fixture.yaml`
say why — and each is the kind of finding a reviewer emits when it has nothing
better to say. Their strength is itself a measurement: if no reviewer ever bites,
they are decoration and precision stays trivially near 1.0.

**Measured 2026-07-31, and they are weak.** Across ten single-shot runs the
stale-batch-timestamp distractor was matched once and the other two never. The
authored bait is close to decoration.

The same runs handed over much better bait for free. Every run independently
raised **release-before-claim** and **non-idempotent retry** (described above),
and both are exactly what a distractor is supposed to be: defensible-sounding,
located on the change under review, and not the seeded defect. They are also
strictly harder than the authored three, because they are arguable rather than
merely tempting — a reviewer that flags them is reasoning, not padding.

Folding them in is deferred rather than forgotten. Adding a distractor changes
what precision means, and the K decision is measured on this fixture's
precision variance; changing the bait and then measuring variance in the same
pass would mix the two. The order is: settle K against the corpus as authored,
then strengthen the distractors, then re-measure. Recorded here so the next
authoring pass does not have to rediscover them.

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
