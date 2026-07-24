# Assay — Implementation Plan

## Overview

Build order for the v1 described in [DESIGN.md](DESIGN.md): a TypeScript
seeded-defect corpus, a scoring harness with a validated judge, and a reference
reviewer panel in two modes, culminating in one published, date-stamped results
table.

The sequencing is driven by one principle: **nothing expensive gets built on an
unvalidated assumption.** The three empirical unknowns are resolved in a
throwaway pilot before any production code exists, and the judge is validated
before any scoring logic is built on top of it.

Scope is v1 only. SARIF output, the fix-commit mining pipeline, and a possible
execute mode live beyond this plan; when v1 ships they move to ROADMAP.md.

**Current status:** Phase 0 not started.

**Budget:** The DESIGN goal of "full sweep under $50" refers to the Phase 6
publication sweep. Development spend across Phases 0–5 is separate and estimated
at roughly $20–25. Total project ceiling ~$75.

**Effort basis:** Estimates are days of directed agent-built work (design,
direction, and review by Philip; implementation by Claude Code under the 8-agent
QA gate), not solo hand-coding days.

---

## Phase 0: Pilot — resolve the empirical unknowns

**Goal:** Answer the three questions that would otherwise be guessed, using
disposable code.

**Estimated Effort:** 1 day (mostly waiting on runs)

### Deliverables
- `pilot/` directory containing throwaway scripts, **explicitly not production
  code and deleted at the end of Phase 1**.
- `pilot/FINDINGS.md` recording the three answers with the evidence behind them.
- Three hand-built scratch fixtures (not corpus-quality, just enough to measure).

### Tasks
- [ ] Build three scratch fixtures at different repo sizes (~8, ~25, ~50 source
      files), each with one known defect.
- [ ] Run a single reviewer prompt against one fixture 10 times; measure
      finding-set variance to determine whether K=5 is sufficient or K must rise.
- [ ] Measure whether `Glob`/`Grep` navigation is non-trivial at each repo size —
      i.e. does the agent actually have to search, or does one call return
      everything?
- [ ] Determine whether the Agent SDK permits fixture-first system-block
      composition with a `cache_control` breakpoint. Record
      `cache_read_input_tokens` across consecutive reviewer runs on one fixture.
- [ ] Record actual cost per agentic and per single-shot run at each repo size.
- [ ] Write `pilot/FINDINGS.md`.

### Testing Strategy
No automated tests — this phase produces knowledge, not software. It is complete
when FINDINGS.md states a chosen K, a chosen fixture repo size range, and a
yes/no on Agent SDK cache control, each with the measurement that justifies it.

### Phase 0 Readiness Gate
Before Phase 1, these must be true:
- [ ] K is chosen and justified by observed variance, not assumed.
- [ ] Fixture repo size range is chosen and justified by observed navigation
      behavior and cost.
- [ ] Agent SDK cache-control question is answered yes or no. If **no**, the
      agentic-reviewer cost estimate is revised and the DESIGN cost-controls
      table is corrected before proceeding.

---

## Phase 1: Corpus format and isolation

**Goal:** Establish the fixture format and prove the answer-key boundary holds.

**Estimated Effort:** 2 days

### Deliverables
- `src/assay/corpus/` — manifest schema, loader, closed defect-class taxonomy,
  locality tagging.
- One corpus-quality fixture, `TS-0001`, with at least one distractor.
- Executor path-boundary enforcement.
- `pilot/` deleted.

### Tasks
- [ ] Define the `fixture.yaml` schema and validate it on load (fail loudly on
      a malformed or incomplete manifest).
- [ ] Write the closed defect-class taxonomy for TypeScript; document why each
      class is in it.
- [ ] Implement the corpus loader with locality tagging.
- [ ] Implement executor working-directory confinement: cwd is `repo/`, no
      parent traversal, no network.
- [ ] Author `TS-0001` end to end, including NOTES.md provenance.
- [ ] Strip git history from fixture repos as a build step, not a manual habit.
- [ ] Delete `pilot/`.

### Testing Strategy
- Unit tests on manifest validation, including rejection of malformed manifests.
- **Isolation test (correctness-critical):** assert that a process confined to
  `repo/` cannot read `fixture.yaml`, cannot traverse to the fixture root, and
  finds no git history. This test failing invalidates every number the project
  will ever produce and is treated accordingly.

---

## Phase 2: Reviewers and the run path

**Goal:** Produce durable transcripts from real reviewer runs.

**Estimated Effort:** 3 days

### Deliverables
- `src/assay/executor/` — `Executor` protocol, `AgentSDKExecutor`.
- `src/assay/reviewers/` — `SingleShotReviewer`, `AgentReviewer`, `SarifReviewer`.
- Transcript persistence as JSONL under `results/runs/<run-id>/`.
- `assay run` CLI command.

### Tasks
- [ ] Implement the `Executor` protocol and `AgentSDKExecutor`.
- [ ] Implement the review context floor: diff + full contents of touched files,
      assembled identically for every mode.
- [ ] Implement `SingleShotReviewer` (Client SDK, no tools).
- [ ] Implement `AgentReviewer` (Agent SDK, `Read`/`Glob`/`Grep` only).
- [ ] Implement `SarifReviewer` subprocess adapter with SARIF parsing.
- [ ] Define the `Finding` schema and constrain reviewer output to it via
      structured outputs.
- [ ] Implement transcript persistence: findings, raw messages, tool calls,
      token usage, model ID, timestamp, corpus hash.
- [ ] Wire `assay run` with Batch API submission.
- [ ] Apply the caching strategy chosen in Phase 0.

### Testing Strategy
- Contract test: `SingleShotReviewer` and `AgentReviewer` receive byte-identical
  floor context. Regression here silently confounds the headline result.
- Transcript round-trip test: persist and reload without loss.
- SARIF parser tested against a fixture SARIF file from a real external tool.
- End-to-end smoke: `assay run` against `TS-0001` produces a valid transcript.

---

## Phase 3: Matching, judge, and judge validation

**Goal:** Turn findings into verified matches, and establish how much the
matching itself can be trusted.

**Estimated Effort:** 3 days plus roughly half a day of manual labeling

### Deliverables
- `src/assay/eval/match.py` — proximity gate.
- `src/assay/eval/judge.py` — semantic adjudication on Haiku.
- `adjudication/labeled.jsonl` — human-labeled validation set (~100 pairs).
- Judge agreement rate, computed and reported.

### Tasks
- [ ] Author two more fixtures (`TS-0002`, `TS-0003`) so matching is developed
      against more than one shape of defect.
- [ ] Implement the proximity gate with a configurable window.
- [ ] Implement the judge with a tight structured-output schema returning a
      boolean plus confidence.
- [ ] Generate ~100 candidate pairs from Phase 2 transcripts and **label them by
      hand.** This is Philip's labeling, not an agent's — an agent-labeled
      validation set validates nothing.
- [ ] Implement judge-vs-human agreement measurement as a replayable check.
- [ ] Implement cross-reviewer finding dedup using the same judge.

### Testing Strategy
- Proximity gate unit tests, including the citing-a-nearby-line case that
  motivated it.
- Judge determinism check: repeated adjudication of identical pairs.
- The agreement measurement runs as part of the test suite and prints its number.

### Phase 3 Readiness Gate
Before Phase 4, this must be true:
- [ ] **Judge agreement against human labels is acceptable and its number is
      recorded.** If agreement is poor, stop. Do not build scoring on top of an
      unreliable adjudicator, and do not adjust the labeled set until the number
      improves — revise the judge prompt or the matching strategy instead, then
      re-measure against the *unchanged* labels.

---

## Phase 4: Scoring and reporting

**Goal:** Produce trustworthy numbers from stored transcripts, at zero marginal
cost.

**Estimated Effort:** 2 days

### Deliverables
- `src/assay/eval/score.py` — precision, recall, bootstrap CIs.
- `src/assay/eval/replay.py` — score without re-running.
- Report generator producing a date-stamped, model-stamped Markdown result file.
- `assay score` and `assay report` CLI commands.

### Tasks
- [ ] Implement per-reviewer precision and recall.
- [ ] Implement panel-level metrics over deduplicated findings.
- [ ] Implement bootstrap 95% CIs across K runs.
- [ ] Implement the locality breakdown (`local` / `touched_file` / `cross_file`).
- [ ] Implement regression detection as CI non-overlap between two runs.
- [ ] Implement the report generator, stamping model ID, date, corpus hash, K,
      and judge agreement rate into every output.
- [ ] Verify `assay score` makes zero model calls.

### Testing Strategy
- Metric correctness against hand-computed expected values on synthetic inputs.
- Bootstrap CI sanity: identical inputs produce identical intervals; wider
  inputs produce wider intervals.
- **Zero-spend assertion:** a test fails if `assay score` issues any API call.
- Replay determinism: scoring the same transcripts twice yields identical output.

---

## Phase 5: Corpus buildout

**Goal:** Reach a corpus large and varied enough for the v1 numbers to mean
something.

**Estimated Effort:** 4–5 days — the grind phase

### Deliverables
- 15 corpus-quality fixtures, stratified across defect locality and class.
- `corpus/README.md` documenting the taxonomy, the locality mix, and the
  authoring standard.

### Tasks
- [ ] Decide and document the target locality mix ratio (open question from
      DESIGN) before authoring resumes.
- [ ] Author fixtures `TS-0004` through `TS-0015`.
- [ ] Ensure every fixture carries at least one distractor.
- [ ] Write `corpus/README.md`, stating the authoring standard and the known
      bias of a hand-authored corpus plainly.
- [ ] Run the isolation test across all fixtures.

### Testing Strategy
- Every fixture passes manifest validation and the isolation test.
- Locality distribution matches the documented target ratio, asserted by a test
  rather than checked by eye.
- Spot-check: a fixture's defect is genuinely reachable from the stated
  locality tier and no lower.

### Phase 5 Readiness Gate
Before Phase 6, these must be true:
- [ ] 15 fixtures pass validation and isolation.
- [ ] Locality mix matches the documented ratio.
- [ ] A dry-run cost projection for the full sweep is under $50.

---

## Phase 6: First published sweep

**Goal:** Produce and publish the result that makes the repo citable.

**Estimated Effort:** 1–2 days

### Deliverables
- A complete sweep: 3 reviewers × 15 fixtures × K runs.
- `results/<date>-<model>.md` — the published results table.
- `README.md` leading with results.
- Public repository under Apache 2.0.

### Tasks
- [ ] Run the full sweep via Batch API.
- [ ] Generate the results file.
- [ ] Write the README: results table first, then method, then the
      tools-vs-no-tools finding broken out by locality.
- [ ] State corpus size, n, and hand-authored bias **before** any percentage
      appears.
- [ ] Publish the judge agreement rate alongside the reviewer scores.
- [ ] Disclose the circularity (Anthropic models, judged by an Anthropic model).
- [ ] Add Apache 2.0 LICENSE and contribution guidance for new fixtures.
- [ ] Move deferred work to ROADMAP.md.

### Testing Strategy
Full suite green; sweep completes within budget; every number in the README
traces to a stored transcript and is reproducible by `assay score` on the
published run ID.

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Answer-key leakage into reviewer context | Critical — all numbers invalid, silently | Low | Executor path confinement; history-free fixtures; isolation test treated as correctness-critical; re-verified whenever executor or layout changes |
| Judge agreement too low to trust | Critical — blocks the project | Medium | Phase 3 readiness gate stops work; revise judge, never the labels |
| Run-to-run variance swamps signal; K must rise | High — cost scales with K | Medium | Measured in Phase 0 before anything is built on an assumed K |
| Agent SDK blocks prefix caching | Medium — agentic cost rises | Medium | Measured in Phase 0; fallback is a Client SDK tool loop for the agentic reviewer |
| Corpus too small or biased for numbers to mean much | Medium — limits claims, not correctness | High | Stated plainly in README before any percentage; contribution path for external fixtures |
| Fixture authoring expands without limit | Medium — v1 never ships | High | 15 is a hard v1 cap; further fixtures are post-v1 work |
| Published results go stale on model release | Low — expected | Certain | Date-stamp and model-stamp every result; re-running is routine |
| Scope creep into auto-fix or a hosted service | High — different project | Medium | Both are explicit non-goals in DESIGN.md |

---

## Timeline

```
Phase 0  Pilot                 1d      ─┐
                                        ├─ gate: K, repo size, caching answered
Phase 1  Corpus format         2d      ─┘
Phase 2  Reviewers + run       3d
Phase 3  Match + judge       3.5d      ─── gate: judge agreement acceptable
Phase 4  Scoring + report      2d
Phase 5  Corpus buildout     4–5d      ─── gate: 15 fixtures, mix, cost projection
Phase 6  Published sweep     1–2d
                            ───────
                            ~17–19d directed work
```

**Dependencies.** Phases are strictly sequential; each gate exists because
proceeding past a failed one wastes the work that follows it. The two
parallelizable stretches are fixture authoring (Phase 5 work can begin during
Phase 4, since scoring does not change the fixture format) and README drafting
(can begin during Phase 5).

**Critical path** runs through Phase 3. If judge agreement fails its gate, the
project stalls until matching is reworked — which is why the labeled set is
built early and by hand rather than deferred to the end.
