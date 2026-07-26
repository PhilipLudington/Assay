# pilot/ — throwaway

**This is not production code and it is deleted at the end of Phase 1.**
Nothing here is imported by `src/assay/`. Nothing here is a template for the
real corpus format. It exists to answer three empirical questions before
[PLAN.md](../PLAN.md) Phase 1 starts building on guesses:

1. **Is K=5 sufficient?** How much does a reviewer's finding set vary run to run?
2. **How large should a fixture repo be?** At what size does `Glob`/`Grep`
   navigation stop being trivial, and what does each size cost per run?
3. **Does the Agent SDK permit fixture-first system-block composition with a
   `cache_control` breakpoint?** If not, the agentic-reviewer cost estimate and
   the DESIGN cost-controls table are wrong.

The answers land in [FINDINGS.md](FINDINGS.md), which is the only artifact of
this phase that outlives it.

## Layout

```
pilot/
├── fixtures/
│   ├── small/    8 source files  — token-bucket rate limiter
│   ├── medium/  25 source files  — job queue with worker pool
│   └── large/   50 source files  — shipment tracking HTTP API
│       ├── repo/          ← reviewer's cwd. Bug present. No .git.
│       ├── change.patch   ← the diff under review
│       └── ANSWER.md      ← ground truth. MUST stay outside repo/.
├── common.py       fixture loading, review-context floor, pricing
├── run_singleshot.py   Client SDK reviewer, N repeats
├── run_agentic.py      Agent SDK reviewer, tool-call capture
├── analyze.py          variance → K, navigation, cache, cost
└── FINDINGS.md
```

Each fixture carries exactly one seeded defect and no distractors. That is
deliberate: distractors exist to make *precision* a real measurement, and the
pilot does not measure precision. It measures detection variance, navigation
behaviour, and cost. Corpus-quality fixtures (Phase 1 and Phase 5) do carry
distractors.

`ANSWER.md` sits outside `repo/` for the same reason `fixture.yaml` does in the
real corpus — a reviewer whose working directory is the fixture root could read
the answer key and post a perfect score.

**The 34 runs behind FINDINGS.md were made before that boundary was enforced.**
Layout was the only thing standing between the reviewer and `ANSWER.md`. An
audit of all 34 transcripts found 135 paths inside `repo/`, none outside, and no
reference to the answer key — so those numbers are clean — but 22 calls did
attempt absolute paths outside the working directory and failed only because
those paths did not exist. `run_agentic.py` now enforces the boundary through
`assay.executor`; any run from here on is confined for cause rather than by
luck, and blocked attempts are recorded in each transcript under
`boundary_violations`.

## Running it

Requires an Anthropic API key. Per [DESIGN.md](../DESIGN.md) Key Decisions, the
Agent SDK is governed by Commercial Terms and scripted access needs an API key —
running this against a Claude subscription is not an option.

```sh
export ANTHROPIC_API_KEY=sk-ant-...

# Q1: variance. 10 single-shot runs on one fixture.
uv run pilot/run_singleshot.py --fixture small --runs 10

# Q2 + Q3: navigation and caching. Agentic runs at each size.
# Project venv, not `uv run` — this one imports the real answer-key boundary.
.venv/bin/python pilot/run_agentic.py --fixture small  --runs 2 --reviewers correctness,security
.venv/bin/python pilot/run_agentic.py --fixture medium --runs 2 --reviewers correctness,security
.venv/bin/python pilot/run_agentic.py --fixture large  --runs 2 --reviewers correctness,security

# Label the variance runs by hand — the pilot's K rests on these, not on the
# proximity heuristic. The worksheet carries each run's findings inline.
uv run pilot/analyze.py --emit-labels
#   ...correct the booleans in pilot/out/labels.template.json...
cp pilot/out/labels.template.json pilot/out/labels.json

# Q4 + report
uv run pilot/analyze.py
```

`run_singleshot.py` and `analyze.py` use PEP 723 inline dependencies, so `uv
run` needs no project venv. `run_agentic.py` is the exception: it imports
`assay.executor` for the answer-key boundary and therefore runs under the
project venv. That import is the pilot's one dependency on production code, and
it is deliberate — the Phase 1 gate forbids a measurement run while the
boundary is unenforced, so the harness that runs and the control that is tested
must be the same code.

Raw transcripts land in `pilot/out/` (gitignored). `analyze.py` reads them and
prints the numbers that go into FINDINGS.md.

## Cost

Reviewers run on `claude-opus-5`, decided 2026-07-24 — the same model the v1
sweep will publish against, because neither variance nor cost transfers across
models. The pilot is roughly 10 single-shot runs plus 12 agentic runs; the
agentic runs on the 50-file fixture dominate. Expect a few dollars, not tens.

`--model` exists, but changing it invalidates the K this pilot produces. If the
sweep model changes, the variance run has to be redone.
