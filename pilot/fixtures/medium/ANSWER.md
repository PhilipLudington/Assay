# ANSWER KEY — medium

**This file must never be reachable from `repo/`.**

- **Fixture:** `medium`
- **Source files in `repo/src`:** 25
- **Seeded defects:** 1
- **Distractors:** none

## Defect M-1

- **Class:** race condition / duplicate execution
- **Severity:** high
- **Locality:** `touched_file` — **corrected 2026-07-25 after measurement.**
  Authored as `cross_file`, but the pilot disproved that: `WorkerPool`'s own
  class comment in `pool.ts` (lines 17–20) states the heartbeat invariant
  outright, and `pool.ts` is the file the diff touches, so that sentence is in
  the review-context floor. Single-shot runs with no tool access found M-1 and
  quoted the invariant back. The evidence never required `heartbeat.ts`.
- **Location:** `src/worker/pool.ts`, `finish` (line 78) and `recover`
  (line 88)
- **Required to see it:** `src/worker/heartbeat.ts`, which is **not** in the
  diff and **not** among the touched files handed to the reviewer

### What is wrong

`WorkerPool.finish` and `WorkerPool.recover` now remove the job from
`this.active` *before* awaiting the store write that moves the record out of
`running`:

```ts
private async finish(jobId: JobId, startedAt: number): Promise<void> {
  this.active.delete(jobId);                          // slot freed
  await this.store.complete(jobId, this.clock.now()); // ← await: yields
  ...
}
```

`HeartbeatSweeper.sweep` states the invariant this breaks, in its class
doc comment:

> A job id is present in `pool.activeIds()` for the *entire* time its store
> record is in the `running` status — it is added before the record moves to
> `running`, and removed only after the record has left it.

The sweeper treats a `running` record that nothing owns as orphaned and
requeues it **immediately** — there is no stall timeout on that path, because
in an in-process queue unowned means nothing is working on it. Between the
`active.delete` and the completion of the store write, the job is exactly that:
`running` in the store, absent from `active`.

### Why it matters

`JobQueue.tick` calls `sweeper.sweep()` on every tick, and `MemoryStore`
serialises writes per job id behind a `KeyedMutex`, so the window is not
theoretical — it widens precisely when the queue is busy, which is when the
sweeper runs most often.

A sweep landing in that window requeues a job that is in fact succeeding. The
job then runs a second time, with a handler that has already had its side
effects. For a queue whose whole contract is at-least-once-with-dedupe, silent
duplicate execution is the worst available failure. The `recover` path is worse
still: the record is requeued as stalled *and* by the retry policy, so
`attempt` can advance twice for one failure and a job can be declared dead
early.

The commit's stated benefit is real — the slot genuinely was held across the
write — but the fix must keep `active` membership strictly wider than the
`running` status, e.g. by releasing in a `finally` after the write, or by
having the sweeper consult a separate "releasing" set.

### Acceptable identifications

A finding matches if it identifies the reordering in `pool.ts` as unsafe with
respect to the heartbeat sweeper's ownership check. Equivalent phrasings:

- "removing from `active` before the store write lets the sweeper see the job
  as orphaned"
- "the heartbeat sweeper can requeue a job that is completing, causing it to
  run twice"
- "`activeIds()` must remain a superset of the store's `running` set"
- "the delete should be in a `finally` after `store.complete` / `store.fail`"

### Not a match

- Flagging the throughput claim in the commit message as unverified.
- Noting only that `finish` lacks a `try`/`finally` for exception safety
  without connecting it to the sweeper. This is a real (pre-existing) weakness
  and a reviewer may well raise it, but on its own it does not describe M-1.
- Generic "consider a distributed lock" commentary.
