# Assay — Design

Resolves the open questions in [IDEA.md](IDEA.md).

## Overview

Assay measures how good a code-review agent actually is.

It ships a corpus of TypeScript fixtures containing deliberately seeded defects
with documented ground truth, a scoring harness that computes per-reviewer
precision and recall with confidence intervals, and a reference panel of
specialized reviewer agents that serves as both a usable review gate and the
first thing the harness measures.

The reviewer panel is useful. The measurement is the product. Anyone can write
a "review my code" prompt; almost nobody can tell you their reviewer's recall
on null-dereference defects, or whether it regressed when they changed models.
Assay exists to make that number cheap to obtain and honest to publish.

The harness is Python. The corpus is TypeScript. Those are independent axes and
the split is deliberate — see Key Decisions.

## Goals

- [ ] Compute per-reviewer precision and recall over the corpus, reported as a
      mean across K runs with a bootstrap 95% confidence interval, not a point
      estimate.
- [ ] Publish the **judge's own** agreement rate against human-labeled pairs in
      the same README as the reviewer scores. A benchmark that hides the
      reliability of its scoring mechanism is not a benchmark.
- [ ] Score any third-party reviewer that emits SARIF, with no bespoke
      integration code.
- [ ] Re-score an existing run without spending money — changing the matcher,
      the judge, or the scoring rules must not require re-running reviewers.
- [ ] Answer one substantive research question in the v1 README: **does giving a
      reviewer read-only filesystem tools improve recall enough to justify the
      cost?** — reported broken out by defect locality, not only in aggregate.
- [ ] Demonstrate reviewer isolation: a test asserts no reviewer can reach a
      fixture's answer key from inside the repo it is reviewing.
- [ ] Detect regressions across model versions as CI non-overlap between runs,
      and date-stamp every published result.
- [ ] Complete a full v1 sweep (3 reviewers × 15 fixtures × 5 runs, plus judge
      adjudication) for under $50 in API spend.

## Non-Goals / Out of Scope

The fence. Everything here is a deliberate omission, not an oversight.

- **Auto-fix.** Proposing or applying patches is a different, much larger
  product, and it destroys the measurement story — you cannot cleanly score a
  reviewer that also edits the code it is reviewing.
- **Any hosted component.** No service, no dashboard, no database, no accounts.
  Assay is a library and a CLI that writes files.
- **A provider abstraction.** Anthropic models only. Bedrock, Vertex, and
  Foundry are reachable because the Agent SDK already reads their environment
  variables — that is the entire extent of the support. No OpenAI, no
  provider-neutral model interface.
- **IDE or editor integration.**
- **Languages other than TypeScript** in the corpus. The harness is Python and
  will stay language-agnostic internally, but bug taxonomies are not portable
  and v1 ships exactly one.
- **Mined or agent-generated fixtures** in v1. Both are planned; neither ships
  until the scoring harness is proven against hand-authored ground truth.
- **SARIF output** in v1. SARIF is an *input* format in v1 (how third-party
  reviewers get measured). Emitting SARIF so Assay's own findings appear in
  GitHub code scanning is v1.1.
- **A leaderboard, submission process, or any public ranking of vendors.**
- **Scoring human reviewers**, however tempting.
- **Being a production CI gate.** The panel is usable in CI and documented as
  such, but Assay is not competing with commercial AI code review, and the
  README will not pitch it that way.

## Design

### Data model

Four types carry the whole system.

**Fixture** — a self-contained review target with known ground truth. On disk:

```
corpus/ts/TS-0004-cache-eviction-race/
├── repo/              # ← reviewer's cwd. HARD BOUNDARY. Post-change state,
│                      #   bug present, no .git history.
├── change.patch       # the diff under review
├── fixture.yaml       # ANSWER KEY — must be unreachable from repo/
└── NOTES.md           # why this bug is realistic; provenance (author-facing)
```

The manifest sits deliberately *outside* `repo/`. An agentic reviewer whose
working directory were the fixture root could read the answer key and post a
perfect score — the benchmark equivalent of train/test contamination. See
Review context contract below.

```yaml
id: TS-0004
title: Null deref when eviction races a cache read
language: typescript
diff: change.patch
defects:
  - id: TS-0004-d1
    class: null-dereference          # from a closed taxonomy
    severity: high
    locality: cross_file             # local | touched_file | cross_file
    location: { file: src/cache.ts, lines: [42, 47] }
    description: >
      `entry` may be undefined if eviction runs between the has()
      check and the get() call.
distractors:
  - kind: naming-inconsistency
    location: { file: src/cache.ts, lines: [12, 14] }
    note: bait for low-value style findings
```

**Distractors are load-bearing.** Without something a reviewer can plausibly but
wrongly flag, precision is trivially near 1.0 and the metric is meaningless.
Every fixture carries at least one.

**Finding** — what a reviewer emits: `reviewer`, `file`, `line_range`,
`claimed_class`, `severity`, `confidence`, `message`.

**Transcript** — the full record of one reviewer's execution against one
fixture: findings, raw model messages, tool calls, token usage, model ID,
timestamp. Persisted as JSONL. This is the unit that costs money.

**Score** — the output of matching a set of transcripts against fixture ground
truth. Costs nothing and is reproducible from stored transcripts.

### Pipeline

```
  corpus/          reviewers/         executor/
     │                 │                  │
     └────────► run ◄──┴──────────────────┘        ← spends money
                 │
                 ▼
        results/runs/<run-id>/*.jsonl               ← durable transcripts
                 │
     ┌───────────┴───────────┐
     ▼                       ▼
  match  ──► judge ──►    score  ──►  report        ← free, re-runnable
```

The hard boundary between `run` and `score` is the single most important
structural decision in the system. Everything downstream of a transcript is
free, deterministic, and re-runnable. Changing the matcher, swapping the judge,
fixing a scoring bug, or adding a new metric costs nothing and does not
invalidate historical runs.

### Review context contract

What a reviewer sees is two separate settings, not one. Conflating them is what
makes this question feel harder than it is.

**Floor** — handed to every reviewer in its prompt, identical across all modes:
the diff, plus the **full contents of every file the diff touches**.

**Ceiling** — what an agentic reviewer may additionally reach with tools:
read-only navigation of `repo/` via `Read`, `Glob`, `Grep`.

The floor is identical across modes by design. If the single-shot reviewer
started with less context than the agentic one, the comparison would measure
context volume and tool access simultaneously and could separate neither.

A raw-diff-only floor was rejected: defects introduced by *removing* a guard
appear in a diff as a deletion and nothing else, so a diff-only baseline would
crater on anything non-local and make tools look enormously valuable. That
result would be an artifact of starving the baseline, not a finding about tools.
A whole-repo-in-context floor was rejected from the other side — it leaves tools
nothing to add.

**Modes are an enum, not a boolean:**

```python
class ReviewMode(StrEnum):
    SINGLE_SHOT = "single_shot"   # floor only, no tools
    READ_TOOLS  = "read_tools"    # floor + read-only repo navigation
    # EXECUTE   = "execute"       # v2+, gated — see Key Decisions
```

Reserving the third value now costs nothing and turns a binary result into a
three-point curve later.

**Isolation is enforced, not assumed.** The executor sets the reviewer's working
directory to `repo/` and refuses, per tool call, any path that resolves outside
it — traversal, absolute, or through a symlink. Two leak channels the per-call
check cannot see are refused as *preconditions*, before a run starts: surviving
version-control history (a defect is recoverable from commit messages) and
symlinks anywhere in the fixture (`Glob` and `Grep` expand patterns across them
themselves, so only the declared path is ever visible to the boundary). A test
in the suite asserts that a reviewer cannot reach `fixture.yaml` from inside
`repo/`; that test failing invalidates every number in the repo, so it is
treated as a correctness test, not a nicety.

Network confinement is **not** implemented and is not needed yet: the reviewer's
toolset contains no network tool. It becomes real work when `SarifReviewer`
shells out to a third-party binary in Phase 2, and belongs there.

### Reviewer interface

```python
class Reviewer(Protocol):
    name: str
    mode: ReviewMode

    async def review(self, fixture: Fixture, executor: Executor) -> Transcript: ...
```

Three implementations ship in v1:

- **`SingleShotReviewer`** — one Client SDK call. Sees the diff and the touched
  files. Cheap, fully cacheable, no tool loop.
- **`AgentReviewer`** — Agent SDK. Can `Read`, `Glob`, `Grep` across the fixture
  repo, so it can chase a call site or check whether a guard exists elsewhere.
  Expensive.
- **`SarifReviewer`** — subprocess adapter. Shells out to any external command,
  parses SARIF from stdout or a file. This is how a third-party tool gets
  measured without anyone writing an integration for it.

Shipping the first two is what makes the tools-vs-no-tools research question
answerable, and that question is the README's headline result.

### Matching: proximity gate, then judge

Matching findings to seeded defects is the hardest correctness problem here. A
reviewer may correctly identify a defect while citing the call site rather than
the guard, or describe it in entirely different vocabulary. Line matching alone
is far too brittle; a judge alone is expensive and unaccountable.

Two stages:

1. **Proximity gate (free).** A `(finding, defect)` pair becomes a candidate if
   it is in the same file and the line ranges are within `±proximity_window`
   lines (default 10). Cheap, deterministic, discards the overwhelming majority
   of pairs.
2. **Semantic judge (cheap model).** For each candidate, a judge decides: does
   this finding describe this defect? Returns a boolean plus a confidence. Runs
   on Haiku with a tight structured-output schema.

**The gate's failure direction is the opposite of the one assumed above.**
Measured 2026-07-31 on `TS-0001` (see `results/locality/`): across ten
single-shot runs, all 29 findings fell inside the proximity window of the seeded
defect and **none of them described it**. They converged on three other
concerns — an ordering race, a retry-idempotency hole, and a counter bug — that
happen to live on the defect's own lines. Proximity scored 10/10; hand labelling
scored 0/10.

So the paragraph above is right that line matching is too brittle and wrong
about how. The anticipated failure was a false *negative* (right defect, wrong
line). The observed failure is a false *positive* at full strength, and it is
the more dangerous of the two: a missed match depresses recall visibly, while a
spurious match inflates it and looks like a good result. Two consequences:

- **The proximity gate is a filter, never a decision.** Nothing may score a
  match on proximity alone. `assay.corpus.locality` therefore reports its
  matcher's verdict and requires hand labels to overrule it, and any tag settled
  that way records that it was hand-labelled.
- **The judge's validation set must contain this shape.** A set built only from
  clean hits and obvious misses would let a judge that rubber-stamps "same
  lines, plausible bug" score perfectly. Those 29 findings are committed and are
  a ready-made adversarial slice: a judge that calls them matches is not fit to
  adjudicate the corpus.

**The judge is itself validated.** A one-time human-labeled adjudication set of
~100 candidate pairs is labeled by hand and committed to the repo. Every scoring
run replays the judge against it and reports agreement. That number is published
next to the reviewer scores. If the judge's agreement is poor, every reviewer
number in the repo is suspect — which is exactly the fact a reader is entitled
to know, and exactly the fact most eval harnesses quietly omit.

### Scoring

Per reviewer, per defect class:

- **Recall** = seeded defects matched by ≥1 finding from that reviewer.
- **Precision** = that reviewer's findings that matched some seeded defect,
  over all its findings. Distractor hits count against precision, as intended.

Panel-level metrics are computed separately. Panel recall treats a defect as
caught if any reviewer caught it. Panel precision requires deduplicating
findings across reviewers, which reuses the same judge to decide whether two
findings describe the same thing.

**Nondeterminism.** A score is defined over K runs (default K=5). Reported
values are the mean with a bootstrap 95% CI. A regression is CI non-overlap
between two runs, never a point-to-point comparison. All K transcripts are
retained; nothing is averaged away at write time.

### Executor

Deliberately thin — under a hundred lines.

```python
class Executor(Protocol):
    async def run(self, spec: AgentSpec) -> RawTranscript: ...
```

`AgentSDKExecutor` is the default and the only one that ships. Bedrock, Vertex,
and Foundry work through it by setting the environment variables the Agent SDK
already honors. The abstraction exists so the harness is not welded to one
deployment path, and because a reader evaluating this repo will ask how it runs
against their own infrastructure. It does not exist to avoid cost — see Key
Decisions.

### Cost controls

All four are structural, not afterthoughts.

| Lever | Mechanism |
|---|---|
| Replay | `score` never calls a model. Re-scoring is free by construction. |
| Batch API | Sweeps are non-latency-sensitive; runs submit as batches at 50% off. |
| Model tiering | Judge and dedup run on Haiku. Reviewers run on the model under test. |
| Prompt caching | **Single-shot only:** fixture content is placed first in the system block with a cache breakpoint, reviewer-specific instructions after it, so all reviewers on a fixture share a prefix — the first pays the write and the rest read at ~0.1×. **Agentic:** the Agent SDK exposes no breakpoint; caching is automatic and not steerable. |

That last one inverts the intuitive ordering (instructions first, then content)
and is worth calling out to anyone reading the code, because it looks wrong
until you know why.

**Corrected 2026-07-25 after the Phase 0 pilot.** The row originally claimed
this ordering for every reviewer. It is not available to the agentic reviewer:
`ClaudeAgentOptions.system_prompt` takes a single string, with no list-of-blocks
form and no `cache_control` field anywhere in the options surface. The
single-shot claim was measured and holds — a second reviewer's *first* run read
the prefix the first reviewer wrote. For the agentic reviewer, caching is
substantial but its attribution is not measurable through
`ResultMessage.model_usage`, which aggregates across all turns of a run.

This does not trigger the "fall back to a Client SDK tool loop" contingency
below: measured agentic cost is $0.28–$0.41 per run and near-flat from 25 to 50
source files, so the cost blow-up that contingency existed to prevent did not
materialise. See [pilot/FINDINGS.md](pilot/FINDINGS.md).

### Repo layout

```
assay/
├── README.md                  # leads with the results table
├── DESIGN.md  IDEA.md
├── src/assay/
│   ├── corpus/                # loader, manifest schema, taxonomy
│   ├── reviewers/             # single_shot, agentic, sarif adapter
│   ├── executor/
│   ├── eval/
│   │   ├── match.py           # proximity gate
│   │   ├── judge.py           # semantic adjudication
│   │   ├── score.py           # metrics, bootstrap CI
│   │   └── replay.py
│   └── cli.py                 # assay run | score | report
├── corpus/ts/…                # fixtures
├── adjudication/labeled.jsonl # human-labeled judge validation set
└── results/
    ├── runs/<run-id>/         # transcripts (gitignored if large)
    └── 2026-08-sonnet-5.md    # published, date-stamped
```

## Key Decisions

- **Decision:** Eval-first, single repo. README leads with measurement; the
  panel is the reference implementation.
  **Alternatives considered:** Panel-first (lead with the CI gate); two
  separable packages.
  **Rationale:** The panel competes with funded commercial products and would
  be judged on polish. The measurement is uncontested, produces citable
  numbers, and is the harder thing to fake. Two packages was the cleanest
  boundary but roughly 1.5× the packaging work before any result exists, and
  the split can still be made later if `assay-bench` finds an audience.

- **Decision:** TypeScript corpus, Python harness.
  **Alternatives considered:** Python fixtures (self-hosting); C# fixtures;
  multi-language from v1.
  **Rationale:** These are independent axes, and treating them as one was the
  mistake worth avoiding. The corpus language determines whether the seeded bugs
  are *credible*: authoring a realistic bug taxonomy demands deep language
  knowledge, and that depth is in TypeScript. Self-hosting was the prettier
  story but would have meant authoring a Python bug taxonomy without that depth
  — a shallow corpus undermines every number downstream.

- **Decision:** Hand-authored fixtures for v1; fix-commit mining deferred to v2.
  **Alternatives considered:** Mining from day one; agent-injected at scale.
  **Rationale:** Mining is the most defensible long-term source but is a
  substantial subsystem with licensing questions, and it would delay any
  published result by months. Agent injection is rejected as a primary source
  outright: bugs written by an agent risk being artificially legible to another
  agent, which would silently inflate every recall number in the repo. The
  failure would be invisible and the numbers would still get cited.

- **Decision:** Every fixture carries distractors.
  **Alternatives considered:** Seeded defects only.
  **Rationale:** With nothing plausible to wrongly flag, precision approaches
  1.0 for any reviewer and the metric conveys nothing. Distractors are what make
  precision a real measurement.

- **Decision:** Two-stage matching, and the judge is validated against a
  committed human-labeled set whose agreement rate is published.
  **Alternatives considered:** Line-overlap only; judge only.
  **Rationale:** Line overlap misses correct findings that cite a nearby line.
  An unvalidated judge just relocates the trust problem one layer down and
  hides it. Publishing the judge's agreement rate is the difference between a
  benchmark and a marketing number, and it is cheap — one afternoon of labeling,
  replayed free forever after.

- **Decision:** Hard `run` / `score` split with durable transcripts.
  **Alternatives considered:** Single-pass pipeline.
  **Rationale:** Cost, reproducibility, and honesty all point the same way.
  Scoring rules will change; re-spending to apply them would create pressure to
  leave bad rules in place. It also means historical runs stay comparable
  against new scoring logic.

- **Decision:** K=5 runs, bootstrap CI, regressions defined as CI non-overlap.
  **Alternatives considered:** Single run; point-estimate comparison.
  **Rationale:** Reviewer output is nondeterministic. A single run cannot
  distinguish a real regression from sampling noise, and point comparison would
  generate false regression alarms that erode trust in the whole harness.

- **Decision:** Both single-shot and agentic reviewers ship in v1.
  **Alternatives considered:** Agentic only (matches the SDLC being codified).
  **Rationale:** Shipping both converts a cost problem into the repo's headline
  research question. "Tools raise recall by X points at Y× the cost" is a
  genuinely useful public finding and is more interesting than either mode alone.

- **Decision:** Review floor is the diff plus the full contents of every touched
  file, identical across modes; the agentic ceiling is read-only navigation.
  **Alternatives considered:** Diff-only floor; whole-repo-in-context floor;
  different floors per mode.
  **Rationale:** See Review context contract. The load-bearing constraint is
  that a differing floor would confound context volume with tool access and
  render the headline comparison uninterpretable.

- **Decision:** Execution (running tests, executing code) is deferred, and
  deferred against a **stated trigger** rather than indefinitely.
  **Alternatives considered:** Shipping an execute mode in v1; leaving it as an
  open "maybe later."
  **Rationale:** Bundling execution into "tools" would leave the v1 result
  unable to distinguish recall gains from *navigation* versus from *observation*,
  and it drags in sandboxing work with no evidence yet that it is needed. An
  open-ended "later" quietly becomes a permanent maybe, so the trigger is
  written down: **build execute mode when error analysis shows that a material
  share of `cross_file` misses are behavioral rather than navigational** — i.e.
  defects a careful reader could not have found by reading, only by running.
  Until that evidence exists, execution stays out.

- **Decision:** Every defect carries a `locality` tag (`local`, `touched_file`,
  `cross_file`), and the corpus is deliberately mixed across all three.
  **Alternatives considered:** Untagged defects; tagging only by defect class.
  **Rationale:** Locality is what makes the tools question answerable per-class
  instead of only in aggregate, and it doubles as a self-check on the harness.
  The expected shape is a large tools benefit on `cross_file` and roughly none
  on `local`. If tools appear to help on `local` defects, something is wrong in
  the matcher or the floor, and that needs discovering before publication rather
  than after.

- **Decision:** A defect's `locality` tag is **measured, not asserted by the
  fixture author**, added 2026-07-25.
  **Alternatives considered:** The author assigns the tag when writing the
  fixture (the original design); a second author reviews the tag.
  **Rationale:** The Phase 0 pilot disproved author-assigned tagging on its own
  fixtures — two of three defects were authored as `cross_file` and both were
  found by a single-shot reviewer with no tool access, because the evidence had
  leaked into the touched file (once as a class comment restating the broken
  invariant, once as a visible asymmetry with sibling handlers). Neither fixture
  looked wrong on inspection, and the author was actively trying to avoid that
  failure. Since the headline result is reported *broken out by locality*, bad
  tags yield a confidently wrong finding rather than a noisy one.
  **The procedure:** run the single-shot reviewer against the fixture with no
  tools; if it finds the defect, the defect is not `cross_file`, whatever was
  intended. `cross_file` is claimed only for defects that survive. This is
  nearly free — single-shot runs cost ~$0.05–$0.09 — and it is the same run the
  sweep performs anyway, so it is self-financing.

- **Decision:** Reviewer isolation is enforced by the executor and asserted by a
  test, with the manifest stored outside `repo/` and fixtures shipped without
  git history.
  **Alternatives considered:** Convention alone (manifest is a sibling; just
  don't read it).
  **Rationale:** A reviewer that can read the answer key scores perfectly and
  the failure is silent. This is the contamination failure mode that has
  invalidated real benchmarks, and convention is not a control.

- **Decision:** The boundary is enforced by an Agent SDK **`PreToolUse` hook**,
  not by the `can_use_tool` permission callback. Added 2026-07-26.
  **Alternatives considered:** `can_use_tool`, which is the obvious surface and
  reads as the intended one.
  **Rationale:** The SDK auto-approves a tool call *before* `can_use_tool` runs
  whenever `permission_mode="bypassPermissions"` is set or `allowed_tools` grants
  a whole tool — and the reviewer configuration does both. The callback would
  never have been invoked. That is worse than having no control, because the
  code would read as enforced in review; the SDK emits a `CanUseToolShadowedWarning`
  for exactly this mistake and names the hook as the remedy. Recorded here
  because the next person to touch the executor will reach for `can_use_tool`
  first, as this implementation did.

- **Decision:** The hook fails closed on its own internal errors, not just on
  recognised violations. Added 2026-07-26 after QA review.
  **Rationale:** The SDK catches an exception raised inside a hook, replies to
  the CLI with a protocol-level error, and logs nothing. Whether the CLI then
  proceeds under `bypassPermissions` is undocumented. A boundary whose
  correctness depends on an unverified answer to that question is not a
  boundary, so any internal failure denies the call and is recorded as a
  violation — a run in which the control broke must never be indistinguishable
  from a clean one.

- **Decision:** Default-deny carries one explicit exception — a `CONTROL_PLANE_TOOLS`
  allowlist for tools that read nothing. Added 2026-07-30 after the live probe.
  **Alternatives considered:** Weakening default-deny to "allow any tool with no
  path-bearing fields", which would have fixed the same symptom.
  **Rationale:** `StructuredOutput` is how the CLI returns a `--json-schema`
  result, so denying it left every agentic run with zero findings and a parse
  error — the boundary was confining the reviewer *and* gagging it. The general
  rule was not wrong; the allowlist was incomplete. A category-based exemption
  would re-open the hole default-deny exists to close, because the next tool
  that happens to carry no path would be admitted without anyone deciding to
  admit it. A name list forces that decision to be made and written down.
  The exempted tool's inputs are deliberately not path-checked: a finding
  legitimately cites a repo-relative file, and treating those citations as
  attempted accesses would reject correct output.

- **Decision:** The live boundary probe is production code, not a one-off script.
  Added 2026-07-30.
  **Rationale:** What it tests — that the Agent SDK honours a `PreToolUse` deny
  under `bypassPermissions` — is a *dependency's* behaviour. It can regress on
  an SDK upgrade with no change to this repository, and no unit test would
  notice, because unit tests can only exercise our side of the boundary. So the
  probe ships, is re-run on upgrade, and its transcript is committed as evidence
  under `results/boundary-probe/`. It also reports a run in which the reviewer
  never attempted an escape as `INCONCLUSIVE` rather than as a pass: a control
  that was never exercised has not been verified, and recording it as verified
  is the failure this whole line of work started from.

- **Decision:** The probe also judges its own harness, reporting `MISCONFIGURED`
  when the answer channel returned nothing or the SDK flagged the run as errored.
  Added 2026-07-31 after QA review.
  **Alternatives considered:** Leaving the rule in prose — `results/boundary-probe/README.md`
  already told a human reader that a run with a null `structured_output` proves
  nothing — and relying on transcripts being read before being cited.
  **Rationale:** The incident that created this module was not a boundary
  failure. On 2026-07-30 the bait was refused and the canary never appeared, so
  every boundary signal looked perfect, while `StructuredOutput` was denied twice
  and the run ended in a parse error. Judging only the boundary would have
  certified that run as `HELD` with exit 0. A rule that lives only in prose is
  enforced exactly as often as someone reads the prose, and the exit code is what
  CI will actually consult on the next SDK upgrade. A real breach still outranks
  a broken harness in the verdict order: a leak happened whether or not the
  answer channel worked, and burying it under `MISCONFIGURED` would report the
  less urgent fact.

- **Decision:** The reviewer's tool policy lives in one importable module,
  `assay.executor.policy`. Added 2026-07-31 after QA review.
  **Alternatives considered:** Keeping the lists at each call site and adding a
  test that asserts the copies agree.
  **Rationale:** They were duplicated between `assay.executor.probe` and
  `pilot/run_agentic.py`, and had already drifted: the probe did not deny
  `TodoWrite`. That matters more than ordinary duplication because the probe's
  entire evidentiary claim is that it runs *the reviewer's exact configuration* —
  a claim this design repeats — so a drifted copy means the run certifying the
  boundary measured a configuration nothing else uses. This is the second
  instance of that exact shape; the first was the probe running without an
  `output_format`. A consistency test would catch the next drift, but only after
  it was written; one definition makes the drift unrepresentable.

- **Decision:** SARIF as an input format in v1; output deferred to v1.1.
  **Rationale:** Parsing SARIF is cheap and immediately delivers the eval-first
  promise that any reviewer can be measured. Emitting it is an adoption feature
  for the panel, which is not what v1 is selling.

- **Decision:** Thin executor abstraction in v1.
  **Rationale:** Its original justification — developing against a subscription
  to avoid API spend — was invalidated by the terms review (Agent SDK is
  governed by Commercial Terms; Consumer Terms §3 bars scripted access without
  an API key). It survives on a narrower basis: it is the answer to "how does
  this run against our infrastructure," and retrofitting an executor through a
  codebase that assumed one is precisely the kind of rework this project should
  not be caught modeling.

- **Decision:** The name is **Assay**, settled 2026-07-24.
  **Alternatives considered:** Leaving it provisional; renaming to something
  more literal about benchmarking or code review.
  **Rationale:** An assay is a test of composition and purity that reports a
  measured quantity rather than a verdict — which is exactly what this does, and
  the metaphor holds without explanation. It is unclaimed in this space, short,
  and pronounceable. The decision was also made cheap-now-expensive-later by
  publication: the repository is public at that URL, so a rename costs a
  redirect and every external link already shared. Settling it at the first
  moment the cost was still near zero was the point.

- **Decision:** FSL-1.1-ALv2 (Functional Source License), converting to Apache
  2.0 two years after each version is published. Supersedes an earlier decision
  for plain Apache 2.0, revised 2026-07-24.
  **Alternatives considered:** Apache 2.0 or MIT outright; all rights reserved
  (no license); BUSL-1.1; PolyForm Noncommercial; a copyleft license.
  **Rationale:** Two requirements pull against each other — the benchmark must
  be legally runnable by others or "reproducible" is a word rather than a
  property, and the possibility of this becoming a product should not be spent
  before any code exists. Licenses are one-way: a permissive grant cannot be
  withdrawn from versions already published, so granting one on day zero spends
  an option for nothing. All rights reserved preserves the option but blocks
  adoption entirely — corporate legal will not clear unlicensed code for CI,
  which would defeat the SARIF input path whose whole purpose is letting others
  measure their own reviewers. BUSL-1.1 and PolyForm Noncommercial were rejected
  for the same reason in subtler form: BUSL bars *production* use by default and
  PolyForm bars commercial use, either of which stops a company running Assay in
  its own CI. FSL draws the line at *competing* use instead, which is the line
  actually worth defending, and its two-year conversion is an irrevocable grant
  in the license text rather than a stated intention. Cost: Assay is
  source-available, not open source, and the README says so rather than claiming
  "open."

## Tradeoffs & Risks

**The corpus is small and reflects one person's idea of a bug.** Fifteen
hand-authored fixtures cannot represent the space of real defects. Mitigation:
publish the taxonomy and the count prominently, never report a bare percentage
without an n, and structure the fixture format so external contributions are
straightforward. This is a real limitation, and the README should say so before
a reader has to work it out.

**Everything rests on the judge.** If judge agreement is low, every number is
noise. Mitigated by measuring and publishing it, but not eliminated — and if the
agreement rate comes back poor, the honest response is to say so rather than
tune the adjudication set until it looks better.

**K=5 may not be enough.** If run-to-run variance is high, confidence intervals
will be too wide to detect anything and K has to rise, with cost rising in step.
This is the most likely reason the budget estimate proves wrong.

**~~Prompt-cache prefix sharing may not survive the Agent SDK.~~ Resolved
2026-07-25.** It does not survive as an *explicit* breakpoint — the Agent SDK
exposes no such control — but the feared consequence did not follow. Agentic
runs still cache heavily and cost $0.28–$0.41 per run, roughly flat across 25
and 50 source files. Single-shot keeps full, measured prefix sharing. See the
cost-controls table above.

**A defect's locality can be leaked into the review floor by the touched file
itself.** Discovered in the Phase 0 pilot, where two of three seeded defects
were authored as `cross_file` and both turned out reachable from the floor — one
via a class comment in the touched file restating the very invariant the diff
broke, the other via the visible asymmetry between the new handler and its
siblings. Neither fixture looks wrong on inspection. Because the tools-vs-no-tools
result is reported *broken out by locality*, a mis-tagged corpus does not produce
a noisy result, it produces a confidently wrong one. Mitigation: locality is
measured, not asserted — see Key Decisions.

**Answer-key leakage is the highest-severity failure mode.** If a reviewer can
reach `fixture.yaml`, the repo's git history, or any other trace of the intended
answer, it scores near-perfectly and nothing in the output looks wrong. Every
published number would be worthless and the defect would be invisible on
inspection. Mitigated by executor-enforced path boundaries, history-free
fixtures, and an isolation test treated as a correctness test — but it warrants
re-checking whenever the executor or the fixture layout changes, because the
mitigation is easy to break silently.

**Circularity.** Anthropic models reviewing code, judged by an Anthropic model,
scored in a repo that recommends Anthropic models. That is a real conflict and
the correct response is disclosure in the README rather than a claim of
neutrality that nobody would believe.

**Results go stale quickly.** Model releases will invalidate published numbers
within months. Mitigated by date-stamping and model-stamping every result file
and treating re-runs as routine — which also gives the repo a recurring reason
to be updated, and gives the model-drift tracking idea somewhere to live.

**Adoption.** A benchmark nobody runs is a blog post with a repo attached. This
risk is accepted rather than mitigated: the value of the artifact does not
depend on adoption, and the SARIF input path lowers the barrier as far as it
can reasonably go.

## Open Questions

- [x] ~~Does the Agent SDK expose sufficient control over system-block
      composition and `cache_control` placement for prefix sharing?~~
      **Resolved 2026-07-25.** No — `system_prompt` is a single string. The
      agentic reviewer does **not** drop to a hand-rolled Client SDK tool loop:
      measured cost did not justify it. Cost-controls table corrected.
- [ ] Is K=5 sufficient? **Reframed 2026-07-25.** The pilot found recall
      variance to be zero (detection 1.00 across 34 runs), so K cannot be chosen
      from it; what varies is the non-seeded findings, i.e. precision. K is
      therefore a precision question and cannot be settled until fixtures carry
      distractors. Deferred to the end of Phase 1, measured on `TS-0001`.
- [x] ~~Does a reviewer see only the diff, or the whole repo?~~ **Resolved
      2026-07-24.** Floor is diff + touched files, identical across modes;
      agentic ceiling is read-only repo navigation; execution deferred against a
      stated trigger. See Review context contract and Key Decisions.
- [ ] What is the target mix across defect localities? A corpus weighted toward
      `cross_file` would flatter tools; one weighted toward `local` would bury
      the effect. Needs a defensible ratio decided before authoring, and stated
      in the README.
- [x] ~~How large should a fixture repo be?~~ **Resolved 2026-07-25: 25–50
      source files.** Measured share of the repo the agentic reviewer actually
      reads: 79% at 8 files, 32% at 25, 23% at 50. At 8 files the tools are a
      slow `cat` and the ceiling measures nothing. Cost does not push back —
      agentic cost is near-flat from 25 to 50 files — so the original ~15–40
      assumption had its floor too low.
- [ ] One defect per fixture, or several? Several is more realistic; one makes
      attribution unambiguous.
- [ ] Is the internal finding schema Assay-native with SARIF as an adapter, or
      SARIF-native throughout? SARIF-native avoids a translation layer but its
      shape is awkward for scoring.
- [ ] How is the corpus versioned so results remain comparable as fixtures are
      added? Probably a corpus hash recorded in every result file.
- [ ] Which three reviewer specializations ship first? Correctness, security,
      and error handling is the current assumption but has not been argued.
- [ ] Does the human-labeled adjudication set need periodic re-labeling as the
      corpus grows, or is a fixed set adequate?

---

*Next: [PLAN.md](PLAN.md) — phase breakdown and per-phase verification.*
