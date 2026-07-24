# Assay

**Measures how good a code-review agent actually is** — a TypeScript corpus of
seeded defects, and a Python harness that scores per-reviewer precision and
recall with confidence intervals.

> **Status: pre-implementation.** This repository currently contains design
> documents only — no code, no corpus, no results. Phase 0 has not started.
> Nothing here has been measured yet, and this README will not carry a results
> table until it has. See [Status](#status).

## The problem

Teams ship AI-generated code faster than they can review it, and the follow-up
question — *how do you know it's correct?* — has no good answer. Human review
degrades into rubber-stamping as diff volume rises. Passing tests only cover
what the tests already knew to check, and were often written by the same agent
that wrote the bug.

Underneath that sits a quieter problem, and it's the one Assay is about. Teams
that *do* build review-agent pipelines have no way to tell whether the pipeline
works. You add a "security reviewer" prompt, it produces confident-sounding
findings, and everyone assumes it's catching security bugs. Nobody measures
recall. Nobody knows what it misses. The pipeline produces the feeling of rigor
without the substance — which is worse than no pipeline, because it licenses
people to stop looking.

Anyone can write a "review my code" prompt. Almost nobody can tell you their
reviewer's recall on null-dereference defects versus injection defects, or
whether it regressed when they changed models. Assay exists to make that number
cheap to obtain and honest to publish.

## What it measures

Reviewers run against **fixtures**: self-contained repositories with a diff
under review and a documented answer key of seeded defects.

- **Recall** — seeded defects caught by at least one finding.
- **Precision** — findings that matched a real seeded defect, over all findings.

Both are reported **per reviewer and per defect class**, as a mean across K runs
with a bootstrap 95% confidence interval. A regression is confidence-interval
non-overlap between runs, never a point-to-point comparison — reviewer output is
nondeterministic, and a single run cannot distinguish a real regression from
sampling noise.

Every fixture also carries **distractors**: plausible-but-wrong things a reviewer
may flag. Without them, precision approaches 1.0 for any reviewer and the metric
conveys nothing.

## How it works

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

The hard boundary between `run` and `score` is the most important structural
decision in the system. Everything downstream of a transcript is free,
deterministic, and re-runnable. Changing the matcher, swapping the judge, fixing
a scoring bug, or adding a metric costs nothing and does not invalidate
historical runs — so there is never budget pressure to leave a bad scoring rule
in place.

Findings are matched to seeded defects in two stages: a free **proximity gate**
(same file, line ranges within a window) narrows candidates, then a **semantic
judge** on a cheap model decides whether a finding actually describes a defect.
Line matching alone is too brittle — a reviewer can correctly identify a defect
while citing the call site rather than the guard.

## Three things this does that eval harnesses usually skip

**The judge is itself validated, and its agreement rate is published.** A
human-labeled adjudication set is committed to the repo; every scoring run
replays the judge against it and reports agreement next to the reviewer scores.
An unvalidated judge just relocates the trust problem one layer down and hides
it. If the judge's agreement is poor, every reviewer number here is suspect —
which is exactly the fact a reader is entitled to know.

**Answer-key isolation is enforced, not assumed.** A reviewer that can read the
fixture's answer key scores near-perfectly and the failure is silent — the
benchmark equivalent of train/test contamination, and it has invalidated real
benchmarks. Manifests live outside the directory the reviewer sees, fixtures
ship without git history, the executor enforces a hard path boundary, and a test
asserts the answer key is unreachable. That test failing invalidates every
number in the repo, so it is treated as a correctness test.

**Any reviewer that emits SARIF can be scored,** with no bespoke integration
code. The reference panel is the first thing measured, not the only thing
measurable.

## The v1 research question

Assay's first published result answers one question:

> **Does giving a reviewer read-only filesystem tools improve recall enough to
> justify the cost?**

Two reviewer modes ship in v1 — single-shot, and agentic with read-only `Read` /
`Glob` / `Grep` navigation. Both start from an **identical floor**: the diff plus
the full contents of every file it touches. Only the tool ceiling differs. A
differing floor would confound context volume with tool access and make the
comparison uninterpretable.

Every defect is tagged by locality (`local`, `touched_file`, `cross_file`), so
the answer is reported broken out by locality rather than only in aggregate.
That also doubles as a self-check: tools should help substantially on
`cross_file` defects and barely at all on `local` ones. If they appear to help on
`local` defects, something is wrong in the matcher or the floor — and that needs
finding before publication, not after.

## Scope

Deliberate omissions, not oversights. The full fence is in
[DESIGN.md](DESIGN.md#non-goals--out-of-scope).

- **No auto-fix.** You cannot cleanly score a reviewer that also edits the code.
- **No hosted component.** No service, dashboard, database, or accounts. Assay
  is a library and a CLI that writes files.
- **No provider abstraction.** Anthropic models only.
- **One corpus language.** Bug taxonomies are not portable; v1 ships TypeScript.
- **Not a production CI gate.** The panel is usable in CI, but Assay is not
  competing with commercial AI code review and will not be pitched that way.

## Status

Design is settled; implementation has not begun. Phases are defined in
[PLAN.md](PLAN.md).

| Phase | | Status |
|---|---|---|
| 0 | Pilot — resolve empirical unknowns | Not started |
| 1 | Corpus format and isolation | Not started |
| 2 | Reviewers and the run path | Not started |
| 3 | Matching, judge, and judge validation | Not started |
| 4 | Scoring and reporting | Not started |
| 5 | Corpus buildout | Not started |
| 6 | First published sweep | Not started |

Phase 0 is a throwaway pilot that answers three questions rather than guessing
them: how many runs a stable score needs, how large a fixture repo must be for
navigation to be non-trivial, and whether prompt-cache prefix sharing survives
the Agent SDK. Nothing expensive gets built on an unvalidated assumption.

## Honest limitations

These are stated here rather than buried, because a benchmark that hides them is
a marketing number.

- **The corpus is small and hand-authored.** v1 ships 15 fixtures reflecting one
  person's idea of what a realistic bug looks like. That cannot represent the
  space of real defects. No percentage will be reported without its `n`.
- **Everything rests on the judge.** If judge agreement is low, every number is
  noise. That is why the agreement rate is published — and if it comes back
  poor, the honest response is to say so, not to tune the adjudication set until
  it looks better.
- **Circularity.** Anthropic models reviewing code, judged by an Anthropic
  model, scored in a repo that recommends Anthropic models. That is a real
  conflict of interest, disclosed rather than explained away.
- **Results go stale fast.** Model releases will invalidate published numbers
  within months. Every result file is date-stamped and model-stamped, and
  re-running is treated as routine.

## Built by agents, under a review gate

Assay is designed and directed by hand, and implemented by coding agents behind
a specialized review gate. On this project that is the thesis rather than a
caveat: a tool for verifying agent-written code, itself agent-written, with
evals demonstrating that its own gate works.

## Documents

| | |
|---|---|
| [IDEA.md](IDEA.md) | The problem, the possibilities considered, the unknowns |
| [DESIGN.md](DESIGN.md) | What is being built and why — decisions with rationale |
| [PLAN.md](PLAN.md) | Phase breakdown, per-phase verification, budget |

## License

Apache 2.0 is the intended license (permissive, with an explicit patent grant —
the norm for dev tooling that companies run in CI). The `LICENSE` file has not
been added yet.
