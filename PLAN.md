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

**Current status:** Phase 0 complete (34 runs, $7.89) — see
[pilot/FINDINGS.md](pilot/FINDINGS.md). Repo size and caching are settled. The K
condition was found unmeetable in Phase 0 and the gate was reworded on 2026-07-26
to name precision variance, moving the K decision to the end of Phase 1. Phase 1
in progress.

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
- [x] Build three scratch fixtures at different repo sizes (~8, ~25, ~50 source
      files), each with one known defect. (completed 2026-07-24 — 8/25/50 files,
      all typecheck clean, each `change.patch` asserted to reverse against its
      `repo/`)
- [x] Build the measurement harness: `run_singleshot.py`, `run_agentic.py`,
      `analyze.py`. (completed 2026-07-24 — analysis path validated end to end
      against synthetic transcripts)
- [x] Run a single reviewer prompt against one fixture 10 times; measure
      finding-set variance. (completed 2026-07-25 — detection was 1.00 in all 34
      runs, so recall variance is zero and K cannot be chosen from it; finding-set
      Jaccard ranged 0.11–0.81, so the deciding statistic is precision variance,
      which needs distractors. K decision moved to end of Phase 1.)
- [x] Measure whether `Glob`/`Grep` navigation is non-trivial at each repo size.
      (completed 2026-07-25 — share of repo read: 79% at 8 files, 32% at 25, 23%
      at 50. Answer: 25–50 files.)
- [x] Determine whether the Agent SDK permits fixture-first system-block
      composition with a `cache_control` breakpoint. (answered 2026-07-24 — **no**;
      `system_prompt` takes a single string with no `cache_control` surface)
- [x] Record `cache_read_input_tokens` across consecutive reviewer runs on one
      fixture. (completed 2026-07-25 — single-shot cross-reviewer sharing
      confirmed: the second reviewer's first run read the prefix the first wrote.
      Agentic caching is substantial but `model_usage` aggregates across turns,
      so intra-run and cross-run reuse cannot be separated.)
- [x] Correct the DESIGN cost-controls table. (completed 2026-07-25 — table split
      by mode; the Client SDK tool-loop fallback is explicitly **not** triggered,
      since agentic cost came in at $0.28–$0.41/run.)
- [x] Record actual cost per agentic and per single-shot run at each repo size.
      (completed 2026-07-25 — agentic is near-flat 25→50 files; corrected sweep
      model puts K=5 at $18.66 on batch, well inside the $50 goal.)
- [x] Write `pilot/FINDINGS.md`. (completed 2026-07-25)
- [x] Decide how to resolve the failed K gate condition. (decided 2026-07-26 —
      reword the gate to name precision variance and move the K measurement to
      the end of Phase 1, once `TS-0001` carries a distractor. K remains
      provisionally 5 and explicitly unjustified until then.)

### Testing Strategy
No automated tests — this phase produces knowledge, not software. It is complete
when FINDINGS.md states a chosen K, a chosen fixture repo size range, and a
yes/no on Agent SDK cache control, each with the measurement that justifies it.

### Phase 0 Readiness Gate
Before Phase 1, these must be true:
- [x] ~~K is chosen and justified by observed variance, not assumed.~~
      **Reworded 2026-07-26 and moved to the Phase 1 gate.** Recall variance
      measured zero across 34 runs, so the CI is ±0.00 at every K; the statistic
      that actually varies is precision, and precision is not a designed
      measurement until a fixture carries a distractor. Since the first such
      fixture is Phase 1's own deliverable, the condition was circular. The
      replacement condition now reads: *K is chosen and justified by observed
      **precision** variance on a distractor-carrying fixture* — and it gates
      Phase 2, not Phase 1. K is provisionally 5 and explicitly unjustified in
      the interim; no published number may rest on it until the gate clears.
- [x] Fixture repo size range is chosen and justified by observed navigation
      behavior and cost. (2026-07-25 — **25–50 source files**)
- [x] Agent SDK cache-control question is answered yes or no. (2026-07-25 —
      **no**; cost estimate revised upward-but-affordable and the DESIGN
      cost-controls table corrected)

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
- [x] Define the `fixture.yaml` schema and validate it on load (fail loudly on
      a malformed or incomplete manifest). (completed 2026-07-26 — pydantic
      schema, 16 tests / 18 cases, 14 of them rejections. The patch-reverses
      check moves to the loader task below, since it needs the fixture tree and
      not just the manifest.)
- [ ] Implement the locality-verification step: run the single-shot reviewer
      with no tools; a defect it finds is not `cross_file`. Locality is measured,
      not asserted (DESIGN Key Decisions, added after the Phase 0 pilot found two
      of three tags wrong).
- [ ] Measure precision variance on `TS-0001` *with* its distractor and settle K.
      Carried over from the Phase 0 gate.

#### Blockers raised by the 2026-07-26 QA review
These gate Phase 1 completion. The first is the project's stated highest-severity
failure mode; the other two corrupt the measurements Phase 1 itself depends on,
because Phase 1 reuses the pilot harness for locality verification and the K run.

- [x] **Enforce the answer-key boundary, do not assume it.** (completed 2026-07-26)
      `pilot/run_agentic.py` confined the reviewer with `cwd` alone, under
      `permission_mode="bypassPermissions"`, with no path check on
      `Read`/`Glob`/`Grep`. Nothing prevented `Read("../ANSWER.md")`. Audit of all
      34 pilot transcripts found **no** escape (135 paths inside `repo/`, 0
      outside, 0 references to the answer key), so no published number is
      contaminated — but 22 calls did attempt absolute paths outside the working
      directory and failed only because those paths did not exist. The control was
      absent, not merely untested.
      **Closed by** `assay.executor.confinement` (default-deny path boundary,
      resolution-before-comparison so symlinks and `..` cannot slip through) plus
      `assay.executor.hooks` (a `PreToolUse` hook — *not* `can_use_tool`, which
      the Agent SDK never invokes under `bypassPermissions` or a whole-tool
      `allowed_tools` entry, and which would therefore have been a control that
      silently never fired; see DESIGN Key Decisions). 56 isolation cases across
      34 tests. Wired into `run_agentic.py`, which now runs under the project
      venv and records blocked attempts per run under `boundary_violations`.
      **Hardened 2026-07-26 after QA review**, which found three gaps in the
      first implementation: the hook could raise and be reduced by the SDK to an
      unlogged protocol error of undocumented effect (it now fails closed and
      records the failure); `Grep`'s `glob` field was declared checked but had no
      test proving it (it does now); and "fixtures ship no symlinks" was a README
      convention with nothing enforcing it (`assert_isolated` now refuses
      symlinks and surviving VCS history before a run starts — these are the two
      leak channels a per-call path check cannot see, since `Glob`/`Grep` expand
      patterns themselves).
      **Not yet proven end to end:** that the SDK honours a `PreToolUse` deny at
      runtime rests on the SDK's own documentation, not on an observed refusal.
      The first confined run must include a deliberate bait call and confirm it
      is refused — see the Phase 1 gate.
- [ ] **Surface `parse_error` in scoring.** Both runners record `parse_error` and
      fall back to an empty finding list, but `analyze.py` never reads the field —
      so a structured-output parse failure is statistically identical to "the
      reviewer found nothing". Incidence in the pilot was 0/34, so FINDINGS is
      unaffected, but the Phase 4 scorer must not reproduce the pattern.
- [ ] **Give `run_singleshot.py` the retry/record wrapper `run_agentic.py` has.**
      It has no `try`/`except` at all, so one transient API error aborts the batch
      and silently skips every remaining run — the exact failure fixed for the
      agentic path mid-pilot and never backported.
- [x] Write the closed defect-class taxonomy for TypeScript; document why each
      class is in it. (completed 2026-07-26 — 7 classes with per-class rationale
      and an explicit distinguished-from, plus 5 recorded exclusions)
- [x] Implement the corpus loader with locality tagging. Loader validation
      asserts `change.patch` reverses cleanly against `repo/` — the pilot caught
      two patches that had silently drifted from their tree. (completed
      2026-07-26 — `assay.corpus.loader`, 30 tests / 31 cases, 21 of them
      rejections. `load_manifest` proves the answer key is well-formed; the
      loader proves it is *true of this tree*: the patch reverses, every defect
      and distractor location names a real file and a line range inside it, the
      diff's touched files exist, and no copy of `fixture.yaml` or `NOTES.md`
      sits inside `repo/` — the one leak the per-call path boundary cannot see,
      since a reviewer reading it never crosses the boundary. `assert_isolated`
      is reused rather than reimplemented, so authoring-time and run-time
      isolation are the same definition. Also closed a schema gap the loader
      exposed: `diff:` accepted `../../anything`, which would have fed an
      arbitrary file to a reviewer as the change under review.
      **Locality tagging here is structural only** — `structural_locality`
      returns the *closest* tier the diff's shape permits, so a `local` claim on
      a defect outside every hunk is refused while a `cross_file` claim on one
      inside a hunk is allowed. Settling a tag is the measurement task below;
      this bounds it, it does not decide it.)
- [x] Implement executor working-directory confinement: cwd is `repo/`, no
      parent traversal. (completed 2026-07-26 — `src/assay/executor/`; see the
      QA-blocker entry above for the mechanism and the one remaining
      end-to-end check. Network confinement is not implemented: the reviewer's
      toolset has no network tool, so there is nothing to confine until
      `SarifReviewer` shells out in Phase 2, where it belongs.)
- [ ] Author `TS-0001` end to end, including NOTES.md provenance.
- [ ] **Treat recall saturation as an authoring failure.** The Phase 0 pilot hit
      100% detection on 3 of 3 defects across 34 runs. If `TS-0001`'s defect is
      also found by every single-shot run, the fixture is too easy and gets
      reworked — a corpus at the recall ceiling cannot answer whether tools help,
      because recall has nowhere to climb. Record the observed detection rate in
      NOTES.md alongside the provenance.
- [ ] Strip git history from fixture repos as a build step, not a manual habit.
- [ ] Delete `pilot/`.

### Testing Strategy
- Unit tests on manifest validation, including rejection of malformed manifests.
- **Isolation test (correctness-critical):** assert that a process confined to
  `repo/` cannot read `fixture.yaml`, cannot traverse to the fixture root, and
  finds no git history. This test failing invalidates every number the project
  will ever produce and is treated accordingly.

### Phase 1 Readiness Gate
Before Phase 2, these must be true:
- [ ] **K is chosen and justified by observed precision variance** on `TS-0001`
      with its distractor. Inherited from the Phase 0 gate, which could not meet
      it — see FINDINGS. Choose the acceptable CI half-width *before* reading the
      numbers.
- [ ] `TS-0001`'s locality tag is verified by measurement, not asserted.
- [x] Isolation test passes, and manifest validation rejects a patch that does
      not reverse against `repo/`. (Both **passing** as of 2026-07-26 — isolation
      56 cases, loader 31. The reversal check landed in `assay.corpus.loader`
      rather than in manifest validation, since it needs the fixture tree and
      not just the manifest.)
- [ ] **A live run confirms the `PreToolUse` deny actually fires.** The isolation
      test proves the boundary's logic; it does not prove the Agent SDK honours
      the refusal. The first confined run on `TS-0001` carries a bait file
      outside `repo/` and a prompt inviting the reviewer to read it; the gate
      clears when the transcript shows the call refused and recorded under
      `boundary_violations`. Until then the boundary is argued, not observed.
- [ ] The remaining two QA blockers above are closed. No measurement run that
      feeds a recorded decision happens until the answer-key boundary is both
      enforced (done) and observed to fire (above).

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
- [ ] Implement the `Executor` protocol and `AgentSDKExecutor`, with a per-run
      wall-clock deadline and per-run retry. Both are required, not defensive
      polish: the Phase 0 pilot saw one run stall for 29 minutes against an ~85s
      median (a parent `timeout` did not reach it), and transient
      `Claude Code returned an error result` failures in roughly 1 run in 4. A
      failure must cost one run, never a batch.
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
| Answer-key leakage into reviewer context | Critical — all numbers invalid, silently | Low **→ raised, then lowered again 2026-07-26**: the pilot harness enforced nothing beyond `cwd` and reviewers were observed attempting absolute paths outside it; `assay.executor` now denies those calls by default and records them | Executor path confinement (default-deny, symlink- and `..`-resolving); history-free fixtures; isolation test treated as correctness-critical and re-run whenever executor or layout changes. **Keep auditing transcripts for out-of-`repo/` paths after every run batch** — the boundary is enforced but not yet observed firing against a live SDK, and the audit is what established the pilot's own numbers were clean |
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
