# Pilot findings

**Date:** 2026-07-25
**Model:** `claude-opus-5`, effort `high` (decided 2026-07-24; the v1 sweep
publishes against the same model, because neither variance nor cost transfers)
**Harness:** `anthropic` 0.120.0, `claude-agent-sdk` 0.2.127
**Runs:** 34 retained (19 single-shot, 15 agentic) across three fixtures — 8, 25
and 50 source files. **$7.89** attributable to those runs; actual API spend was
a little higher, since failed retry attempts and one discarded smoke run are not
recorded as rows.

The headline: **two of the three questions were answered, one was answered in a
way that invalidates its own premise, and the pilot found a defect in the
fixtures themselves that changes how Phase 5 must author the corpus.** That
last one is the most valuable thing here and it is not something the plan
anticipated.

---

## Q3 — Does the Agent SDK permit fixture-first system-block composition with a `cache_control` breakpoint?

### Answer: no. Determined by inspection, then measured around.

`ClaudeAgentOptions.system_prompt` is `str | SystemPromptPreset |
SystemPromptFile`. There is no list-of-blocks form and no `cache_control` field
anywhere in the options surface, so DESIGN's cost-controls row cannot be
expressed literally through the Agent SDK.

**The Client SDK can, and it works.** `run_singleshot.py` puts the fixture
first behind a breakpoint and the reviewer instructions after. Measured on
`small`:

| Reviewer | Run | `cache_creation` | `cache_read` |
|---|---|---|---|
| correctness | 0 | 2,435 | 2,435 (written by the smoke run a minute earlier) |
| correctness | 1–9 | 0 | 2,435 each |
| **security** | **0** | **0** | **2,435** |

The security reviewer's *first* run read the prefix the correctness reviewer
wrote. Cross-reviewer prefix sharing is real, and DESIGN's claim holds for
single-shot.

**For the agentic reviewer the honest answer is "substantial caching happens,
attribution not isolated."** Agentic runs report 63k–229k `cacheReadInputTokens`,
but `ResultMessage.model_usage` aggregates across the whole run, and an agentic
run is 8–18 turns each of which reads what the previous turn wrote. My
instrumentation cannot separate intra-run caching from cross-run prefix reuse.
Claiming the prefix is shared would be over-reading the instrument.

### What this means for DESIGN

The cost-controls table needs correcting — it describes a mechanism the Agent
SDK does not expose. But the practical consequence is smaller than the Phase 0
gate assumed: agentic cost per run came in at **$0.28–$0.41**, which is not the
blow-up the "fallback to a hand-rolled Client SDK tool loop" contingency was
written to avoid. **Recommendation: correct the table, do not build the
fallback.** Revisit only if agentic cost per run rises materially at Phase 5
corpus scale.

### Bonus, load-bearing for Phase 1

`ClaudeAgentOptions` exposes `sandbox: SandboxSettings` with
`SandboxNetworkConfig` (`deniedDomains`, `allowManagedDomainsOnly`), and
`setting_sources=[]` stops the agent inheriting the operator's `CLAUDE.md`,
settings and skills. The second is not optional for a benchmark: without it the
reviewer reads whatever happens to be on the machine, and the numbers stop
being about the fixture. `run_agentic.py` sets it.

---

## Q1 — Is K=5 sufficient?

### Answer: unanswerable as posed, because recall variance is zero. K must be driven by precision instead.

Detection of the seeded defect was **1.00 in all 34 runs**, every fixture, both
modes, both reviewers. The bootstrap CI half-width on detection rate is
therefore **±0.00 at K=3 and at K=10 alike** — the measurement cannot
discriminate between them, and no amount of extra runs would change that.

But the finding *sets* are far from stable:

| fixture / mode / reviewer | n | findings per run | mean pairwise Jaccard |
|---|---|---|---|
| small / single_shot / correctness | 10 | 3.0 ± 0.0 | **0.51** |
| small / single_shot / security | 3 | 2.0 ± 0.8 | **0.11** |
| medium / read_tools / correctness | 10 | 2.9 ± 0.3 | **0.81** |
| large / read_tools / correctness | 3 | 3.0 ± 0.0 | 0.67 |

Ten single-shot runs on `small` each returned exactly three findings, and yet
only about half of them agreed on *which* three. The security reviewer agreed
with itself on roughly one finding in ten.

**So the quantity that actually moves run to run is the non-seeded findings —
which is precisely what precision counts.** Recall on a defect Opus 5 always
finds is stable by construction; precision is not. DESIGN's K and its
CI-non-overlap regression rule are aimed at the wrong statistic.

Two consequences, both of which the plan should absorb before Phase 3:

1. **PLAN's Phase 0 gate wording — "K is chosen and justified by observed
   variance"— must say *which* variance.** On this evidence it is precision
   variance, and K cannot be fixed until fixtures carry distractors, because
   without them there is nothing for a false positive to hit and precision is
   not measurable at all.
2. **K remains provisionally 5, unjustified.** That is an honest status, not a
   result. The measurement that would justify it belongs at the end of Phase 1,
   on `TS-0001` *with* its distractor, not here.

### Why the hand-labelling decision did not change this

The agreed workflow was to hand-label the ten variance runs rather than trust
the proximity heuristic. That remains the right call in general, and
`analyze.py --emit-labels` produces the worksheet. It cannot change this
conclusion: detection is saturated, so relabelling can only move a value that is
already 1.00 across the board, and the CI stays ±0.00 either way. I have not
labelled on your behalf — the worksheet is there if you want to audit the
heuristic, but the K conclusion does not rest on it.

I did read the findings text of every distinct run, which is how the fixture
defect below was caught.

---

## Q2 — How large should a fixture repo be?

### Answer: 25 or more. Eight is definitively too small.

| fixture | source files | tool calls | Read | Glob | Grep | distinct files read | **% of repo read** |
|---|---|---|---|---|---|---|---|
| small | 8 | 9.7 | 6.3 | 1.7 | 0.3 | 6.3 | **79%** |
| medium | 25 | 10.7 | 7.9 | 1.0 | 0.4 | 7.9 | **32%** |
| large | 50 | 15.7 | 11.3 | 0.3 | 2.7 | 11.3 | **23%** |

At 8 files the agent reads four fifths of the repository — the tools are not
navigating, they are performing a slow `cat`, and the agentic ceiling measures
nothing. At 25 and 50 the agent reads a minority and chooses which minority.
`Grep` use rises sharply with size (0.3 → 0.4 → 2.7): at 50 files it genuinely
searches rather than listing.

**Recommendation: 25–50 source files, and DESIGN's "~15–40" working assumption
should have its floor raised.** 15 sits uncomfortably close to the size where
navigation collapses into retrieval. Cost does not argue against the larger
end — see Q4, where large and medium came out within 2% of each other.

> A metric correction made mid-pilot: I originally scored "did one `Glob`
> return everything?" That fires at every repo size, because `**/*.ts` always
> lists the whole tree, and it would have marked all three fixtures trivial.
> Listing filenames is not retrieving content. The column that answers the
> question is percentage of files actually read.

---

## The unplanned finding: locality cannot be asserted by the author

**Both defects I tagged `cross_file` are reachable from the review-context floor,
and single-shot runs with no tool access found them.** These are authoring
errors, and both `ANSWER.md` files are corrected.

- **M-1 (`medium`).** `WorkerPool`'s own class comment states the heartbeat
  invariant — "Membership of `active` is what the heartbeat sweeper uses to tell
  a live job from an orphaned one." `pool.ts` is the touched file, so that
  sentence is in the floor. A single-shot run quoted it back while explaining
  the bug. `heartbeat.ts` was never needed.
- **L-1 (`large`).** `shipments.ts` is a touched file, and every other mutating
  handler in it routes through `shipmentService` while the new one routes
  through `shipmentRepo`. Single-shot found the bug from that asymmetry alone —
  "Every other mutating path goes through ShipmentService" — without reading
  `shipment-repo.ts` and its doc comment.

### Why this matters well beyond the pilot

DESIGN's headline research question is *does giving a reviewer read-only tools
improve recall, broken out by defect locality*. That result is only as good as
the locality tags, and this pilot demonstrates that a locality tag assigned by
the fixture's own author is unreliable — I introduced two bad tags in three
fixtures while actively trying to avoid exactly that.

**Proposed procedure, for Phase 1's fixture format and Phase 5's authoring
standard:** locality is not a field the author fills in. It is a measurement.

> Run the single-shot reviewer against the fixture K times with no tool access.
> If it finds the defect, the defect is not `cross_file`, whatever the author
> intended. Tag `cross_file` only for defects that survive that check; the tag
> is then evidence rather than assertion.

This is cheap — single-shot runs cost $0.05–$0.09 — and it is self-financing,
because it is the same run the sweep needs anyway. It also closes a
contamination path DESIGN does not currently name: a defect can be "leaked" into
the floor by a comment in the touched file, and nothing about the fixture looks
wrong on inspection.

Concretely, this affects PLAN Phase 1 (`fixture.yaml` schema and locality
tagging) and Phase 5 (locality mix ratio — a ratio computed over self-assigned
tags would be measuring the author's intentions).

---

## Q4 — Cost

Per run, at `claude-opus-5` / effort `high`:

| fixture | files | single-shot | agentic | agentic turns |
|---|---|---|---|---|
| small | 8 | $0.052 | $0.284 | 10.7 |
| medium | 25 | $0.082 | $0.407 | 11.7 |
| large | 50 | $0.087 | $0.410 | 16.7 |

Agentic cost is strikingly flat from 25 to 50 files (+0.9%) despite 43% more
turns — prompt caching absorbs most of the growth. **Repo size is close to free
on the cost axis in this range, which removes the main argument for choosing
the small end of DESIGN's size assumption.**

### Projected v1 sweep

DESIGN's three v1 reviewers are `SingleShotReviewer`, `AgentReviewer` and
`SarifReviewer`. They do not cost the same thing, so a sweep is
`15 fixtures × K × (single-shot + agentic + SARIF)`, with SARIF at $0 (it shells
out to an external tool and makes no model calls):

| repo size | one sweep run | K=3 | K=5 | K=7 | K=10 |
|---|---|---|---|---|---|
| 25 files, batch | $0.489 | $11.00 | $18.34 | $25.67 | $36.67 |
| 25 files, list | $0.489 | $22.00 | $36.67 | $51.34 | $73.34 |
| 50 files, batch | $0.498 | $11.20 | $18.66 | $26.13 | $37.32 |
| 50 files, list | $0.498 | $22.39 | $37.32 | $52.25 | $74.65 |

**The $50 goal is comfortable.** At 50 files and K=5 the sweep is **$18.66** on
the Batch API, and even K=10 fits at $37.32. DESIGN's budget is not the binding
constraint the plan treats it as.

Two caveats: the $50 also covers judge adjudication, which is Phase 3 and
unmeasured, so treat these as a floor; and my first projection was wrong by
roughly 3× because it priced all three reviewers at the agentic rate — worth
flagging because a wrong budget model would have distorted the Phase 5 gate.

---

## Operational findings

Both are Phase 2 executor requirements, learned the expensive way:

- **The Agent SDK stalls.** One run hung for 29 minutes against an ~85s median
  before I killed it, and `timeout(1)` on the parent did not reach it. The
  executor needs a per-run wall-clock deadline; `run_agentic.py` now uses
  `asyncio.wait_for` at 300s.
- **Transient failures are common — roughly 1 run in 4.** They surface as
  `Exception: Claude Code returned an error result: success`. Initially one
  failure discarded an entire multi-run batch including runs already paid for.
  `run_agentic.py` now retries per run and records failures as rows;
  `analyze.py` excludes them and reports the count. At sweep scale (225+ runs) a
  batch-abort failure mode would be ruinous.

---

## Phase 0 readiness gate

| Gate condition | State |
|---|---|
| K chosen and justified by observed variance | **Not met, and not meetable here.** Recall variance is zero; the deciding statistic is precision variance, which requires distractors. K stays provisionally 5, explicitly unjustified, until the end of Phase 1. |
| Fixture repo size range chosen and justified | **Met.** 25–50 source files, justified by % of repo read (79% → 32% → 23%) and by agentic cost being flat across that range. DESIGN's "~15–40" floor should rise. |
| Agent SDK cache-control question answered yes or no | **Met — no.** Client SDK does it and cross-reviewer sharing is measured; Agent SDK cannot express it. DESIGN's cost-controls table needs correcting; the fallback does not need building. |

**Resolved 2026-07-26.** The gate did not pass as written, because the K
condition was circular: measuring K needs a distractor, the first
distractor-carrying fixture is Phase 1's own deliverable. The condition was
reworded to name *precision* variance and moved to the Phase 1 readiness gate.
K is provisionally 5 and explicitly unjustified until then, and no published
number may rest on it before that gate clears. Phase 1 proceeds.

Two things carry forward into Phase 1 as a direct result of this pilot:

- **Recall saturation is an authoring failure, not a good score.** Three of
  three defects were found in 34 of 34 runs. If `TS-0001` behaves the same way,
  the fixture gets reworked — a corpus at the recall ceiling cannot answer
  whether tools help, because recall has nowhere to climb.
- **Locality is verified by measurement.** Run single-shot with no tools; a
  defect it finds is not `cross_file`, whatever the author intended.
