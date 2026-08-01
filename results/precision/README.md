# Precision measurements, and the K decision that came out of them

Precision needs a label per finding, not a line distance. The 2026-07-31
locality run established why: on `TS-0001` the proximity matcher scored the
seeded defect found ten times out of ten, and every one of those matches was a
false positive. A matcher that wrong about detection cannot be trusted to sort
true positives from false ones, so everything scored here is scored from hand
labels committed beside the transcript.

Scoring makes no model calls and re-scoring is free:

    .venv/bin/python -m assay.eval.precision \
        corpus/ts/<fixture> \
        --from results/locality/<transcript>.json \
        --labels results/precision/<transcript>.finding-labels.json

The command exits non-zero when the batch cannot settle K — see *the collapse*,
below — so a degenerate result cannot be mistaken for a measurement by a script
that only reads exit codes.

## What precision counts

DESIGN: a reviewer's findings that matched some seeded defect, over all its
findings. A distractor bite is a false positive, which is what distractors are
for. **So is any other finding**, including a real, defensible, unseeded bug — a
corpus cannot tell "found something we did not seed" from "wrong" without a
second answer key. That is a known bias of a hand-authored corpus, it makes
every precision number here a lower bound, and it belongs in the README the
results ship with rather than in a correction factor.

A run that reported nothing has **no** precision and leaves the mean. Scoring
silence as 0.00 punishes it and as 1.00 rewards it; both answer a question the
run did not participate in. It stays in the recall denominator, where "found
nothing" is a real and correct outcome.

Every finding of every scored run must be labelled. A partially labelled batch
is refused rather than scored over what happens to be present — the unlabelled
findings would drop out of the denominator and precision would rise for no
reason but unfinished work.

## Runs on file

| Date | Fixture | Reviewer | Precision | Recall | Distractor bites |
|---|---|---|---|---|---|
| 2026-07-31 | TS-0001 | single-shot, floor, no tools | **0.00**, 0/29 findings, exact `[0.00, 0.12]` | 0.00, 0/10 runs, exact `[0.00, 0.31]` | 1/10, 1/10, 0/10 |

Scored 2026-08-01 from the locality batch; no new runs were bought.

## The collapse, and why it settled K differently than planned

PLAN inherited a condition from the Phase 0 gate: *K is chosen and justified by
observed **precision** variance on a distractor-carrying fixture.* The Phase 0
version had named recall variance and proved unmeetable, because detection was
1.00 in all 34 pilot runs.

Precision was measured here and is unmeetable for the same reason, from the
opposite end. Per-run precision was 0.00 in all ten runs. A percentile bootstrap
— the interval DESIGN specifies — resamples the observed values, so a constant
sample resamples to itself and the interval is `[0.00, 0.00]` at **every** K.
Read as a measurement that says one run is enough. It says nothing of the kind:
zero *sample* variance is not zero *sampling* uncertainty, and 0 successes in 5
runs is consistent with a true rate as high as 0.52.

So two things changed rather than one.

**Estimators.** `assay.eval.interval` reports a rate — a count out of n runs —
with an exact Clopper–Pearson interval, which is defined at 0/n and n/n and
whose zero-success upper bound is the familiar ≈3/n. The bootstrap is kept for a
mean of per-run values, where it is the right tool, and it now carries a
`degenerate` flag so a collapsed interval can never print as a precise one.
Every measurement this project has taken has been constant — 34/34, then 0/10,
then precision 0.00 ×10 — so this is the common case, not the corner case.

**The basis for K.** K runs of one fixture are a cluster, not K independent
observations of the corpus, so what they add is divided by `1 + (K−1)ρ`, where ρ
is how much one run of a fixture tells you about its other runs. Every batch
measured so far has looked like ρ = 1: the fixture's outcome is fixed and repeat
runs add nothing. At 15 fixtures:

| ρ | K=1 | K=3 | K=5 | K=10 | K=20 |
|---|---|---|---|---|---|
| 0.5 | ±0.261 | ±0.218 | ±0.204 | ±0.197 | ±0.190 |
| 0.8 | ±0.261 | ±0.246 | ±0.240 | ±0.240 | ±0.233 |
| 1.0 | ±0.261 | ±0.261 | ±0.261 | ±0.261 | ±0.261 |

Four times the runs and four times the spend, for at most 0.014 of half-width —
and 0.5 is already a generous assumption in favour of a larger K. Corpus size
multiplies the same quantity linearly: 45 fixtures at K=5 reaches ±0.15, which
15 fixtures cannot reach at any K.

**K = 5**, therefore, justified by that arithmetic and not by observed variance,
which is degenerate. The decision is provisional in one specific way, and
`assay.eval.precision` prints the flag that would revoke it: **the first batch
whose per-run scores are not constant is the one to re-measure K on.** Until
then ρ is estimated from batches that could not have shown anything else.

## The other thing the arithmetic says

Corpus size, not K, is the binding constraint on every published width, and at
v1's 15-fixture cap the widths are wide: ±0.24 overall, and roughly ±0.38 for a
locality tier holding five fixtures. DESIGN's headline is *broken out by
locality*, so that is the number the headline claim will actually carry.

It also retires one rule as written. DESIGN defines a difference as CI
non-overlap, which is fine over the corpus and impossible per fixture: at K=5
even 0/5 against 5/5 — the largest effect a five-run cell can show — has
overlapping intervals, and non-overlap does not appear until K=20 *and* a
flawless result. A per-fixture table with intervals would print "no difference"
whatever happened. Per-fixture rates are therefore published as bare counts
(`0/10`) with no interval and no verdict, and difference claims are made only
over the aggregated corpus. A raw count is honest; an interval that is
inconclusive by construction is not.

## Provenance of the labels

The `TS-0001` labels were produced by a coding agent, not by a human, and say so
in the file. Phase 3's judge-validation set is hand-labelled by Philip precisely
because agent labels are not self-validating. These carry the same caveat, and
the reasoning behind every non-obvious call is recorded next to the labels so
they can be checked rather than trusted.

Two of the 29 are the arguable ones — both distractor attributions, and both
low-stakes by construction: a distractor bite and an unseeded finding are *both*
false positives, so moving either to `other` changes the bite tally and leaves
precision at 0/29 exactly.
