# Assay — Idea

*(Name is provisional. See Open Questions.)*

## Problem

Teams are shipping AI-generated code faster than they can review it, and nobody
has a good answer to the obvious follow-up question: *how do you know it's
correct?* The current answers are all bad. "A human reviews it" doesn't scale
and quietly degrades into rubber-stamping once the diff volume rises. "The
tests pass" only covers what the tests already knew to check, and the tests
were often written by the same agent that wrote the bug. "The model is good
now" is not an engineering control.

There is a second, quieter problem underneath the first. The teams that *do*
build review-agent pipelines have no way to tell whether the pipeline works.
They add a "security reviewer" prompt, it produces confident-sounding findings,
and everyone assumes it's catching security bugs. Nobody measures recall.
Nobody knows what it misses. The pipeline becomes a ritual that produces the
feeling of rigor without the substance, which is arguably worse than no
pipeline at all, because it licenses people to stop looking.

Personally: I already run a methodology that addresses the first problem —
specialized review agents gating between phases, treating LLM output the way
you'd treat compiler output rather than a colleague's work. It's real, I use it
daily, and it has caught things I would have shipped. But it exists only as a
habit. There is no artifact anyone can run, read, or disagree with. That's a
waste of the only genuinely differentiated thing I do.

## Core Idea

A harness that runs a panel of specialized reviewer agents over a diff and
returns a merge verdict — **plus an eval suite that measures whether the
reviewers actually work**, by running them against a corpus of code with
deliberately seeded bugs and scoring per-reviewer precision and recall.

The panel is the useful tool. The eval suite is the point. Anyone can write a
"review my code" prompt; almost nobody can tell you what their reviewer's
recall is on null-dereference bugs versus injection bugs, or whether it got
better or worse when they upgraded models. That measurement is the thing worth
building and the thing worth publishing.

## Possibilities

Deliberately unfiltered. Some of these contradict each other.

- **Panel-first.** The product is the review gate; the evals are internal
  quality control for it. Optimizes for people who want to *use* it in CI.
  Broader audience, more competition, and the eval work risks getting starved
  because it's not what users ask for.

- **Eval-first.** The product is a benchmark for code-review agents; the panel
  is the reference implementation being measured. Narrower audience, far more
  defensible, and it's the half that produces publishable numbers. Risk: a
  benchmark nobody adopts is just a blog post with a repo attached.

- **Both, honestly split.** Ship them as two coupled-but-separable pieces so
  each can be adopted alone. Costs more design work up front. Probably the
  right answer, which is why it needs to be argued rather than assumed.

- **Reviewer specialization as the core abstraction.** Each reviewer is a
  narrow, named, independently-evaluated unit with its own bug taxonomy and its
  own score. The panel is just composition. This makes the eval suite fall out
  naturally — you score units, not the whole.

- **Adversarial verification instead of a flat panel.** Reviewers propose
  findings; a second stage tries to *refute* each one. Kills confident-sounding
  false positives, which are the dominant failure mode of LLM review. Costs
  roughly double per pass. Might be a mode rather than the default.

- **Seeded-bug corpus, three ways to get one.** (a) Hand-author fixtures —
  highest quality, slowest, biases toward bugs I already think about. (b) Mine
  real fix commits from OSS history and invert them — realistic, laborious,
  license questions. (c) Have an agent inject bugs into clean code —
  fast and scalable, but risks generating bugs that are artificially easy for
  another agent to find, which would silently inflate every number in the
  README. Probably a blend, with (c) never used alone for headline results.

- **Model-drift tracking as a first-class feature.** Re-run the suite on each
  new model release and publish a diff. This turns a static repo into something
  with a reason to be revisited, and it's a genuinely useful public good.

- **Wildcard: make the reviewers portable.** Emit findings in SARIF so they
  drop into existing code-scanning UIs instead of asking anyone to adopt a new
  surface. Adoption cost drops to near zero. Might be the highest-leverage
  single decision in the whole project.

- **Wildcard: score human reviewers with the same harness.** If the fixtures
  and scoring are honest, they work on people too. Interesting, probably
  inflammatory, definitely not v1.

## Edge Cases & Unknowns

- **Nondeterminism poisons regression tracking.** Two runs of the same reviewer
  on the same diff won't produce identical findings. Scoring needs to be robust
  to phrasing variance, and "did the score drop?" needs a confidence interval,
  not a point comparison. This is the single hardest technical problem here and
  it's easy to underestimate.

- **Finding-to-bug matching.** A reviewer says "possible null deref around the
  cache lookup." The seeded bug is a null deref three lines away. Is that a
  catch? Matching on file+line is too brittle; matching on semantics needs a
  judge, and now the judge needs evaluating too. Turtles.

- **Seeded bugs may not resemble real bugs.** If the corpus is full of tidy,
  single-line, textbook defects, high recall proves nothing. Real bugs are
  emergent, cross-file, and often invisible in the diff that introduced them.
  A benchmark that only measures the easy class is worse than none, because it
  produces a number people will cite.

- **Reviewer overlap.** Eight reviewers will independently flag the same
  obvious bug. Does that count once or eight times? Dedup strategy materially
  changes every precision number.

- **The false-positive tax is the real adoption blocker.** A gate that cries
  wolf gets disabled in week two. Precision may matter more than recall for
  the tool, even though recall is the more interesting number for the benchmark.
  These two goals pull in opposite directions and the design has to pick.

- **Cost of a full sweep is bounded but not free.** Prompt caching (large shared
  prefix across reviewers), the Batch API, cheaper models for plumbing
  iteration, and replayable recorded transcripts all cut it substantially.
  Unknown: what a *statistically meaningful* sweep costs once repeated runs are
  required for the nondeterminism problem above. That could be the real budget
  driver, not the headline pass.

- **Execution backend and billing — RESOLVED 2026-07-24, API key required.**
  The Agent SDK's own docs state its use "is governed by Anthropic's Commercial
  Terms of Service," and Consumer Terms §3 prohibits accessing the Services
  "through automated or non-human means, whether through a bot, script, or
  otherwise" except via an API key or where explicitly permitted. A scheme that
  would have funded Agent SDK usage from a monthly per-plan credit was
  announced for 2026-06-15 and is currently **paused**. So: the harness runs on
  an API key. Cost controls (caching, Batch API, model tiering, transcript
  replay) are therefore load-bearing, not optional. Open sub-question: whether
  a *script* driving the `claude -p` headless CLI counts as automated access
  under §3 — treat as yes until Anthropic says otherwise, and don't build the
  free path on that assumption.

- **Language scope.** Bug taxonomies are not language-portable. Whatever
  language the corpus starts in is the language the project is *about* for a
  long time.

- **Prior art.** Multiple commercial AI code-review products exist, and there
  are academic bug-injection benchmarks. Need an honest survey before claiming
  novelty — the defensible claim is probably "open, reproducible, per-reviewer
  measurement," not "first to review code with agents."

## Open Questions

- [x] ~~Is the name **Assay** right, or does this want something else?~~
      **Resolved 2026-07-24: keeping Assay.** See DESIGN.md Key Decisions.
- [ ] Panel-first, eval-first, or explicitly two coupled deliverables?
- [ ] What is the target language for the fixture corpus, and does that differ
      from the language the harness itself is written in?
- [ ] How are findings matched to seeded bugs — location, semantics, or a
      judge? If a judge, how is *it* validated?
- [ ] What's the dedup rule when multiple reviewers flag the same defect?
- [ ] How many runs constitute a score, given nondeterminism? What does the
      README publish — mean, median, or a range?
- [ ] Where does the corpus come from: hand-authored, mined from fix commits,
      agent-injected, or a documented blend? What's the rule for headline numbers?
- [ ] Does the execution backend abstraction exist in v1, or is it retrofitted?
      (Leaning: v1, because retrofitting an executor through a codebase that
      assumed one is exactly the kind of rework this project should not model.)
- [x] ~~Does the Agent SDK path run on subscription auth, and is unattended use
      within terms?~~ **Resolved 2026-07-24: no — API key required.** See Edge
      Cases. Follow-on question this opens: given API-key-only, is the executor
      abstraction still justified in v1, or does its value now rest entirely on
      the Bedrock / Vertex / Foundry enterprise-deployment story rather than on
      cost avoidance?
- [ ] Is SARIF output in scope for v1, or the first thing after?
- [ ] What is the minimum publishable result — how many reviewers and how many
      fixtures before a results table is worth putting in a README?
- [ ] License. Permissive to maximize adoption, or copyleft?

## Not Now (Parking Lot)

- IDE / editor integration of any kind.
- A hosted service, dashboard, or anything with a database.
- Multi-provider model support. Anthropic-only until the single-provider version
  is actually good; adding a provider abstraction early buys nothing and costs
  design clarity.
- Auto-fix. Proposing patches is a different and much larger product, and it
  undermines the measurement story — you can't cleanly score a reviewer that
  also edits.
- Multi-language corpora beyond the first target.
- Scoring human reviewers with the same fixtures.
- Any kind of leaderboard or public submission process.

---

## Note on framing (not part of the standard IDEA structure)

Scope discipline is a first-class constraint on this project, not an
afterthought: a small, finished, well-documented thing with numbers in the
README beats a large, sprawling, half-built one. Where polish and substance
pull apart, substance wins — an artifact built to look good rather than to be
good will not survive anyone who actually reads the code.

Build framing is unchanged from everything else here: designed and directed,
built by agents under a review gate. On this project that is the thesis rather
than a caveat — a tool for verifying agent-written code, itself agent-written,
with evals demonstrating that its own gate works. The README should say so
plainly and early.
