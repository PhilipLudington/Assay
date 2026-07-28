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
invariant in a comment. So the tag here is `verified: false` until the
locality-verification step measures it: run the single-shot reviewer with no
tools; if it finds the defect, the defect is not `cross_file`, whatever this
note argues.

Two known ways this claim could fail, recorded now so the measurement is read
honestly rather than defended:

1. A reviewer can *guess* the shape — "does `markExpired` release the hold?" is
   a reasonable question to ask of that call without reading anything. A guess
   that names the defect counts as finding it. That is the correct scoring
   rule, and if it happens often the tag is wrong.
2. `InventoryRepo.release` and `ReservationRepo.markExpired` being called back
   to back is a two-writes-for-one-event pattern that a suspicious reader may
   flag on principle.

## Difficulty: the saturation check

The pilot found the seeded defect in 34 of 34 runs across all three scratch
fixtures. A corpus sitting at the recall ceiling cannot answer whether tools
help, because recall has nowhere to climb, so **a single-shot detection rate of
1.00 makes this fixture an authoring failure and it gets reworked.**

**Observed single-shot detection rate: not yet measured.** It is recorded here,
alongside the run ids and date, when the Phase 1 locality-verification runs
land. Until then this fixture's difficulty is an argument, not a result.

## Distractors

Three, all in the new file, all deliberately away from the defect's lines so a
proximity-gated match cannot confuse one for the other: a batch timestamp
sampled once (check-then-act bait), a caught-logged-and-continued failure
(swallowed-error bait), and a redundant early return on an empty batch
(dead-code bait). Each is defensible as correct — the notes in `fixture.yaml`
say why — and each is the kind of finding a reviewer emits when it has nothing
better to say. Their strength is itself a measurement: if no reviewer ever bites,
they are decoration and precision stays trivially near 1.0.

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
