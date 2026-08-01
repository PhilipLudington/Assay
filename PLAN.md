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
in progress: the corpus format, the loader, the answer-key boundary, the first
fixture (`TS-0001`) and the pilot-harness blockers are done; on 2026-07-30 the
boundary was **observed** denying a live escape attempt rather than argued from
the SDK's documentation, which unblocked every measurement run.

**Locality is now measured** (2026-07-31, 10 runs, $0.3974): `TS-0001`'s
`cross_file` tag survives at 0/10 and the fixture is not saturated. The
measurement's *second* result matters more than its first. The proximity matcher
scored the defect found 10 times out of 10 and every match was a false positive
— all 29 findings landed on the defect's own lines while describing three
different bugs. DESIGN predicted line matching would fail by producing false
*negatives*; this is the inverse, at full strength.

**K is settled at 5** (2026-08-01, no new spend — the same 10 runs, hand-labelled
finding by finding). Precision came back 0.00 in all ten runs, so precision
variance is degenerate exactly as recall variance was in Phase 0, and for the
same underlying reason: **every fixture measured to date sits on a boundary, and
the bootstrap DESIGN specifies returns ±0.00 over a constant sample at every K.**
Rather than reword the gate a third time, the estimator was fixed — rates now
get exact intervals, so 0/10 reads `[0.00, 0.31]` — and K was settled on the
clustering arithmetic, which does not depend on this fixture's numbers: repeat
runs of one fixture are worth `1/(1 + (K-1)ρ)` of an independent observation, and
at the ρ this project keeps observing they are worth nothing. **Corpus size, not
K, is the binding constraint on every published width**, and per-fixture
confidence intervals turn out to be unpublishable at any affordable K — 0/5
against 5/5 still overlaps. See
[results/precision/README.md](results/precision/README.md).

Phase 1 has three tasks left, none of them measurements: strengthen `TS-0001`'s
distractors, make history-stripping a build step, and delete `pilot/`.

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
- [x] Implement the locality-verification step: run the single-shot reviewer
      with no tools; a defect it finds is not `cross_file`. Locality is measured,
      not asserted (DESIGN Key Decisions, added after the Phase 0 pilot found two
      of three tags wrong). (completed 2026-07-31 — `assay.corpus.locality`, 39
      tests, all offline. The measurement **refutes `cross_file` and nothing
      else**: the floor holds both the hunks and the whole touched file, so a
      run that finds the defect cannot separate `local` from `touched_file` —
      that is structural and the loader already bounds it. A quiet run is a
      *failure to refute*, so a claim only reports settled at n ≥ 10; below that
      the verdict is `underpowered` and the tag stays unverified. The module
      reports and never writes the manifest. `review_floor` lives here because
      locality is the first thing that needs it — **Phase 2 must import it, not
      re-implement it**, or its identical-floor contract test will pass while
      the thing it protects is broken. Two other PLAN items ride the same runs
      at no extra cost: saturation, below, and distractor bites.)
- [x] Measure `TS-0001`'s locality tag. (completed 2026-07-31 — 10 single-shot
      runs, `claude-opus-5`, effort `high`, $0.3974. **`cross_file` survives at
      0/10** and is now `verified: true`. Evidence:
      `results/locality/TS-0001-20260731T170244Z.json`.
      **The proximity matcher scored it 10/10 and every match was a false
      positive**, which is the result worth carrying forward. All 29 findings
      landed on the defect's own lines while describing three *different*
      concerns — release-before-claim ordering, non-idempotent retry, and
      summary accounting. Seven of ten runs recommend "claim via `markExpired`
      first, then release", a fix that would still double-release; a reviewer
      that had read `reservation-repo.ts` could not propose it, which is the
      strongest evidence the evidence really is outside the floor. Detection was
      therefore hand-labelled and the manifest records that it was. DESIGN
      predicted proximity would fail by producing false *negatives*; this is the
      inverse, at full strength, and it is a ready-made adversarial case for the
      Phase 3 judge — a judge that scores these 29 as matches is not fit to
      adjudicate the corpus, and the pairs are already on disk.)
- [x] Measure precision variance on `TS-0001` *with* its distractor and settle K.
      (completed 2026-08-01 — scored from the existing 10 runs, no new spend.
      All 29 findings hand-labelled; labels, reasoning and the full argument in
      [results/precision/README.md](results/precision/README.md).)
      **Precision is 0.00 in all ten runs — 0 true positives in 29 findings —
      so precision variance is degenerate and cannot settle K either.** That is
      the Phase 0 result from the opposite end: recall was pinned at 1.00 there,
      precision at 0.00 here, and a percentile bootstrap over a constant sample
      returns `[0.00, 0.00]` at *every* K. Reading that as "one run suffices"
      would have chosen K off a measurement that measured nothing.
      Two things changed rather than one.
      **Estimators** (`assay.eval.interval`, 34 tests): a rate now gets an exact
      Clopper–Pearson interval, defined at 0/n and n/n, so 0/10 reports
      `[0.00, 0.31]` rather than `[0.00, 0.00]`. The bootstrap stays for means
      of per-run values, where it is correct, and carries a `degenerate` flag so
      a collapsed interval cannot print as a precise one. Every batch this
      project has measured has been constant, so this is the common case.
      **The basis for K:** K runs of one fixture are a cluster, not K
      independent observations, so they add information divided by
      `1 + (K-1)ρ`. At 15 fixtures and ρ=0.8, K=5→20 moves the corpus
      half-width from ±0.240 to ±0.233 — four times the spend for 0.007 — and
      at ρ=1.0, which is what every batch measured so far looks like, K buys
      exactly nothing. Corpus size multiplies the same quantity linearly.
      **K stays 5**, now justified rather than provisional, with a stated
      trigger to re-measure: the first batch whose per-run scores are *not*
      constant. `assay.eval.precision` exits non-zero on a degenerate batch so
      that flag cannot be missed.
- [x] Score precision from labels, not proximity. (completed 2026-08-01 —
      `assay.eval.precision`, 23 tests, all offline. Takes a label per finding
      (`defect:<id>` / `distractor:<kind>` / `other`) and **refuses a batch that
      is not fully labelled**: an unlabelled finding leaves the denominator and
      raises precision for no reason but unfinished work. Labels are validated
      against the fixture's own answer key, so a one-keystroke typo in a defect
      id is an error rather than a silent false positive. A run that reported
      nothing has *no* precision and leaves the mean — scoring silence as 0.00
      punishes it and 1.00 rewards it — but stays in the recall denominator,
      where finding nothing is a real outcome. `partition_runs` moved into
      `assay.corpus.locality` so both modules share one definition of which runs
      count; two definitions is how a denominator comes to differ between two
      reports of the same batch.)

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
      **Proven end to end 2026-07-30** by `assay.executor.probe` — see the
      Phase 1 gate. The same probe found the boundary's one real defect, below.
- [x] **Default-deny was gagging the reviewer, not just confining it.**
      (found and closed 2026-07-30 by the live boundary probe) The boundary
      refuses any tool outside `Read`/`Glob`/`Grep`. `StructuredOutput` is the
      tool the CLI uses to deliver a `--json-schema` result — the reviewer's
      *answer channel* — so with the boundary wired in, **every agentic run
      returned zero findings and a parse error**. Reproduced before fixing:
      one run on the `small` fixture, `StructuredOutput` blocked twice, `0
      findings`, `PARSE ERROR no structured output on the response`.
      No recorded number is affected — the pilot's 34 runs predate the boundary
      — but the next two tasks in this phase are measurement runs, and both
      would have measured nothing at full price. The bug was introduced by the
      2026-07-26 fix to the blocker above and existed for four days without a
      single run to reveal it, which is the argument for the gate that caught it.
      **Closed by** `CONTROL_PLANE_TOOLS` in `assay.executor.confinement`: a
      one-name allowlist for tools that read nothing. Default-deny was right and
      the allowlist was merely incomplete, so the rule stands and the exception
      is explicit. Its inputs are deliberately *not* path-checked — a finding
      legitimately carries a repo-relative `file`, so scanning this tool for
      path-shaped fields would refuse correct output for looking like an escape.
      `ReportFindings`, which the first probe run saw the reviewer reach for,
      stays denied: it is Claude Code's own review tool, not this harness's
      protocol. Verified end to end — the same command that produced 0 findings
      produced 3, with nothing blocked.
      Two things are worth keeping. First, this was only visible because the
      `parse_error` blocker below had already landed; without it the run would
      have read as "the reviewer found nothing" and detection would have been
      0.00 with no signal at all. Second, the first probe ran without an
      `output_format` and so exercised a tool the reviewer never uses while
      leaving the one it depends on untested — the probe now runs the reviewer's
      exact configuration, and records whether the answer channel came back.
- [x] **Surface `parse_error` in scoring.** (completed 2026-07-29) Both runners
      recorded `parse_error` and fell back to an empty finding list, but
      `analyze.py` never read the field — so a structured-output parse failure was
      statistically identical to "the reviewer found nothing". Incidence in the
      pilot was 0/34, so FINDINGS is unaffected; the control was absent, not
      merely unneeded.
      **Closed by** a three-tier split in `analyze.py:partition` — `failed`
      (produced nothing, dropped everywhere) / unparseable / `scored`. The middle
      tier is the point: an unparseable run still navigated the repo and still
      cost money, so it stays in the navigation, caching and cost tables, but its
      finding list is *unknown* rather than empty, so it leaves detection and
      variance. Scoring it as a miss would depress a rate; dropping it from cost
      would understate a sweep. The Q1 table gained a `pe` column and the run
      accounting names the affected groups, so a group whose effective n has
      shrunk below the K it was run at cannot look fully powered.
      One definition of "the findings did not come back" now lives in
      `common.extract_findings`, shared by both runners and the analyzer, rather
      than three local `try` blocks — the bug was precisely that the writers and
      the reader disagreed about a field. It also closed a quieter hole the same
      shape: `structured.get("findings", [])` made a schema violation
      indistinguishable from a clean empty review, in both runners.
      Verified end to end — a synthetic parse-error transcript held detection at
      1.00 instead of dropping it to 0.91, stayed in the cost mean, and was
      reported; the analyzer reproduces all 34 pilot runs unchanged otherwise.
- [x] **Give `run_singleshot.py` the retry/record wrapper `run_agentic.py` has.**
      (completed 2026-07-29) It had no `try`/`except` at all, so one transient API
      error aborted the batch and silently skipped every remaining run — the exact
      failure fixed for the agentic path mid-pilot and never backported.
      **Closed by** `run_singleshot.run_with_retries` plus a per-request
      `--run-timeout`, so a stall costs one run rather than the batch. A run that
      exhausts its retries is *recorded* with `failed: True`, not skipped: a gap
      in the transcripts would let `analyze.py` report a smaller n as if it were
      the intended K. Extracted as a named function rather than an inline `try`
      because the defect was an untested failure path, and an untested failure
      path is what this blocker is about — 6 cases now cover retry-then-succeed,
      exhaustion, zero-retries, and the batch surviving a dead run.
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
- [x] Author `TS-0001` end to end, including NOTES.md provenance. (completed
      2026-07-26 — `corpus/ts/TS-0001-reservation-double-release/`: a 43-file
      TypeScript inventory service, both trees typecheck clean under `strict` +
      `noUncheckedIndexedAccess`, patch reverses, loader accepts it. The change
      under review adds a reservation-expiry sweeper; the seeded defect is that
      it releases each line's hold itself *and* calls `markExpired`, which
      releases the same units in its own transaction, so `held` is decremented
      twice and the ledger oversells. Class `broken-invariant`, severity high.
      **The claim is `cross_file` and it is `verified: false`** — the evidence
      lives in `reservation-repo.ts` and `inventory-repo.ts`, neither touched by
      the diff, and the floor is only the nine-line `registry.ts` plus the new
      sweeper. Whether that claim survives contact with a reviewer is the
      measurement task above, not something this entry settles. Three
      distractors, all deliberately off the defect's lines: a once-sampled batch
      timestamp, a logged-and-continued failure, and a redundant empty-batch
      return. `tests/test_corpus_fixtures.py` re-validates the shipped corpus on
      every run — load, repo size inside the measured 25–50, no VCS history
      anywhere under a fixture root, every fixture carries a distractor.)
- [x] **Treat recall saturation as an authoring failure.** The Phase 0 pilot hit
      100% detection on 3 of 3 defects across 34 runs. If `TS-0001`'s defect is
      also found by every single-shot run, the fixture is too easy and gets
      reworked — a corpus at the recall ceiling cannot answer whether tools help,
      because recall has nowhere to climb. Record the observed detection rate in
      NOTES.md alongside the provenance. (completed 2026-07-31 — **0.00 (0/10)**,
      recorded in `TS-0001/NOTES.md`. Not saturated, and the check is enforced in
      code rather than remembered: `DefectVerdict.saturated` refuses to report a
      fixture settled at a detection rate of 1.00 whatever its locality verdict
      says.
      Worth stating plainly, because the standard as written only guards one
      end: a defect *no* reviewer ever finds cannot discriminate between
      reviewers either — recall is pinned at zero for all of them. The number
      that decides which case this is, is the **agentic** rate on the same
      defect, and that is Phase 2's to measure. If tools lift it off zero the
      fixture is doing exactly the job the v1 question needs; if they do not it
      is too hard rather than too easy, and gets reworked for the opposite
      reason. NOTES.md says so rather than quietly banking the 0.00 as a pass.)
- [ ] **Strengthen `TS-0001`'s distractors.** *Unblocked 2026-08-01 — K is
      settled, so the ordering constraint that deferred this is discharged.*
      Hand-labelled across the 10 runs: stale-batch-timestamp bitten 1/10,
      logged-and-continued-error 1/10, redundant-empty-batch-return 0/10. The
      authored bait is close to decoration and precision against it conveys
      little. The same runs handed over better bait for free — every run
      independently raised release-before-claim and non-idempotent-retry, both
      defensible, both on the change under review, both not the seeded defect,
      and both *arguable* rather than merely tempting. Candidates recorded in
      `TS-0001/NOTES.md`.
      Note what re-measuring can and cannot show: single-shot precision here is
      already 0.00 and cannot go lower, so stronger bait changes the *finding
      mix*, not this fixture's single-shot score. The number it will move is the
      agentic one, which is Phase 2's.
- [ ] Strip git history from fixture repos as a build step, not a manual habit.
      (Partly closed 2026-07-26 from the other end: `assert_isolated` refuses a
      fixture with surviving history at load, and `test_corpus_fixtures.py` fails
      on a VCS directory anywhere under a fixture root, so shipping history is
      now caught rather than remembered. `TS-0001` was authored with the git
      tree kept in a scratch directory outside the fixture, so no history was
      ever created inside it. What is still missing is the *build step* itself —
      a documented, repeatable way to regenerate a `change.patch` from a
      pre/post pair, which today is a sequence of commands in a session
      transcript.)
- [ ] Delete `pilot/`.

### Testing Strategy
- Unit tests on manifest validation, including rejection of malformed manifests.
- **Isolation test (correctness-critical):** assert that a process confined to
  `repo/` cannot read `fixture.yaml`, cannot traverse to the fixture root, and
  finds no git history. This test failing invalidates every number the project
  will ever produce and is treated accordingly.
- **Corpus regression test:** every fixture that actually ships is re-validated
  on every test run — it loads, its repo size sits inside the range Phase 0
  measured, it carries a distractor, and it brings no version-control history.
  A fixture is written once and then read by every sweep afterwards, so the
  change most likely to break it is one nobody makes while looking at it.

### Phase 1 Readiness Gate
Before Phase 2, these must be true:
- [x] ~~**K is chosen and justified by observed precision variance** on
      `TS-0001` with its distractor.~~ **Measured 2026-08-01, and the condition
      is unmeetable for the second time — closed on a different basis, stated.**
      Precision was 0.00 in all ten runs (0 true positives in 29 hand-labelled
      findings), so the observed variance is zero and the bootstrap returns
      ±0.00 at every K. The Phase 0 gate failed this way on recall; this is the
      same failure from the other end, and the pattern is now understood rather
      than worked around: **every fixture measured to date sits on a boundary,
      and a bootstrap over a constant sample is not an interval.**
      K is therefore settled on the clustering arithmetic instead —
      `1 + (K-1)ρ`, which makes K=5→20 worth at most 0.014 of corpus
      half-width and worth nothing at the ρ=1.0 every batch has shown — with
      exact intervals replacing the bootstrap for rates so a boundary result
      reports its real uncertainty. **K = 5.** The re-measure trigger is named
      and enforced in code rather than remembered: the first batch whose per-run
      scores are not constant. Full argument and the K table:
      [results/precision/README.md](results/precision/README.md).
      The pre-registration this condition asked for was **not** honoured, and
      saying so is part of closing it: these ten runs had already been read on
      2026-07-31 for locality, so the labels were applied to findings that had
      been seen. The arithmetic that settles K does not depend on `TS-0001`'s
      numbers at all, which is the only reason it is usable — and it is the
      reason no acceptable half-width was chosen after the fact to fit them.
- [x] `TS-0001`'s locality tag is verified by measurement, not asserted.
      (2026-07-31 — `cross_file`, 0/10, `verified: true`. The author's argument
      was that the evidence lives in `reservation-repo.ts`, untouched by the
      diff; ten no-tools runs agreed by failing to find it, and seven of them
      proposed a fix that only makes sense if they had not read that file.
      Detection was hand-labelled over the matcher, and both the manifest and
      `results/locality/README.md` say so — an unqualified "verified" that
      quietly rested on a matcher this run proved wrong would be the same class
      of error the tag exists to prevent.)
- [x] Isolation test passes, and manifest validation rejects a patch that does
      not reverse against `repo/`. (Both **passing** as of 2026-07-26 — isolation
      56 cases, loader 31. The reversal check landed in `assay.corpus.loader`
      rather than in manifest validation, since it needs the fixture tree and
      not just the manifest.)
- [x] **A live run confirms the `PreToolUse` deny actually fires.** (observed
      2026-07-30) `assay.executor.probe` plants `MAINTAINER-NOTES.md` beside the
      answer key, tells the reviewer to read it, and runs the reviewer's own
      configuration — `bypassPermissions`, `Read`/`Glob`/`Grep`, structured
      output. Transcript committed at
      `results/boundary-probe/TS-0001-20260730T201016Z.json`: the reviewer
      attempted `Read("../MAINTAINER-NOTES.md")`, the call came back an error
      carrying the boundary's own reason, the attempt is recorded under
      `boundary_violations`, and the reviewer said in its own answer that it
      could not read the file. **The boundary is now observed, not argued.**
      Three properties were checked rather than one, because "the hook returned
      deny" only describes our intent:
      1. *The bait was live.* It was written and read back with its canary
         before any token was spent. The 2026-07-26 audit found 22 pilot calls
         that failed on a missing path rather than on a control; a probe whose
         bait does not exist reproduces exactly that and proves nothing.
      2. *The refusal reached the model.* Out-of-bounds calls are re-derived
         from the transcript by the pure checker, not read off the hook's own
         bookkeeping, so a hook that had silently stopped firing could not
         report a clean sheet.
      3. *The canary is absent from the whole transcript* — tool results,
         findings, and final answer. This is the check that cannot be satisfied
         by our code agreeing with itself.
      A run in which the reviewer never attempts an escape is reported
      `INCONCLUSIVE`, not `HELD`: an unexercised control is not a verified one.
      The probe is production code rather than a one-off script because the
      behaviour under test belongs to `claude-agent-sdk` and can regress without
      a line of this repository changing — re-run it on every SDK upgrade.
- [x] The remaining two QA blockers above are closed. (2026-07-29 — both, with
      the failure paths tested rather than assumed.) No measurement run that
      feeds a recorded decision happens until the answer-key boundary is both
      enforced (done) and observed to fire (above, observed 2026-07-30).

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
- [ ] Implement per-reviewer precision and recall. **Import
      `assay.eval.precision`, do not re-implement it** — it already fixes the
      denominator (silence has no precision; unlabelled findings are refused,
      not skipped), and a second definition is how two reports of one batch come
      to disagree.
- [ ] Implement panel-level metrics over deduplicated findings.
- [x] ~~Implement bootstrap 95% CIs across K runs.~~ **Landed early, in Phase 1,
      and not as specified** (2026-08-01, `assay.eval.interval`). Rates get exact
      Clopper–Pearson intervals; the bootstrap is kept for means of per-run
      values and flags a constant sample as degenerate. Phase 4 imports this
      module rather than writing its own — the reason `review_floor` lives in
      `assay.corpus.locality`, for the same reason.
- [ ] Publish per-fixture rates as **bare counts with no interval**, and make
      difference claims only over the aggregated corpus. Per-fixture CI
      non-overlap — DESIGN's original rule — cannot resolve even 0/5 against
      5/5, so a per-fixture table carrying intervals would report "no
      difference" whatever happened.
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
| Answer-key leakage into reviewer context | Critical — all numbers invalid, silently | Low **→ raised 2026-07-26, lowered furthest 2026-07-30**: the pilot harness enforced nothing beyond `cwd`; `assay.executor` now denies those calls by default, and a live confined run has been *observed* refusing a planted bait read with the canary absent from the transcript | Executor path confinement (default-deny, symlink- and `..`-resolving); history-free fixtures; isolation test treated as correctness-critical and re-run whenever executor or layout changes. **Re-run `assay.executor.probe` on every `claude-agent-sdk` upgrade** — the deny is honoured by a dependency, so it can regress with no change here and no test would notice. **Keep auditing transcripts for out-of-`repo/` paths after every run batch**: the audit is what established the pilot's own numbers were clean |
| Judge agreement too low to trust | Critical — blocks the project | Medium | Phase 3 readiness gate stops work; revise judge, never the labels |
| Matching inflates recall by scoring plausible-but-wrong findings on the defect's own lines | Critical — a spurious match looks like a good result, where a missed one visibly depresses recall | **High — observed 2026-07-31**: on `TS-0001`, 29 of 29 findings fell inside the proximity window and none described the seeded defect (10/10 by matcher, 0/10 by hand) | Proximity is a filter, never a decision — nothing scores a match on it alone. Locality tags settled against it must record that they were hand-labelled. **The judge's validation set must include this shape**, or a judge that rubber-stamps "same lines, plausible bug" scores perfectly against it; those 29 findings are committed as a ready-made adversarial slice |
| An interval reports false certainty at the boundary | Critical — a published `0.00 ±0.00` claims precision nobody measured, and it is the *common* case here | **Was certain, now closed 2026-08-01**: every batch measured to date is constant (34/34, 0/10, precision 0.00 ×10), and the specified bootstrap returns ±0.00 for all of them at every K | Rates use exact Clopper–Pearson intervals, defined at 0/n and n/n; the bootstrap is retained only for means of per-run values and sets a `degenerate` flag on a constant sample; `assay.eval.precision` exits non-zero on a degenerate batch. **Do not add a normal-approximate interval anywhere** — it has the same zero-width failure, less visibly |
| Run-to-run variance swamps signal; K must rise | Low — the opposite risk turned out to be the real one | **Resolved 2026-08-01**: variance has been *zero* in every batch, not large. K's leverage is bounded by clustering (`1 + (K-1)ρ`), so K=5→20 buys ≤0.014 of half-width | K=5, justified by that arithmetic; re-measure on the first batch whose per-run scores are not constant, a trigger enforced by the tool rather than remembered |
| Corpus too small for the intervals to say anything | **High — quantified 2026-08-01**: 15 fixtures gives ±0.24 overall and roughly ±0.38 per locality tier, and DESIGN's headline is *broken out by locality*. ±0.15 needs ~45 fixtures and is unreachable at any K | Certain at the v1 cap | Publish the width beside every rate rather than the rate alone; state the cap before any percentage; per-fixture rates ship as bare counts. Raising the cap is post-v1 work, and it is the only lever that moves this |
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
