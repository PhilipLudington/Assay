# ANSWER KEY — small

**This file must never be reachable from `repo/`.** It is the ground truth the
pilot scores against.

- **Fixture:** `small`
- **Source files in `repo/src`:** 8
- **Seeded defects:** 1
- **Distractors:** none (see `pilot/README.md` for why)

## Defect S-1

- **Class:** logic error / starvation
- **Severity:** high
- **Locality:** `local` — the faulty line is inside the diff itself
- **Location:** `src/bucket.ts`, lines 34–36 (the body of `refill`)

### What is wrong

`refill` floors the tokens earned since `lastRefill`, then advances
`lastRefill` to `now` unconditionally. The floored remainder is discarded
rather than carried forward, so any elapsed time that earns less than one whole
token is lost permanently.

```ts
const earned = Math.floor((elapsed / 1000) * this.refillPerSecond);
this.tokens = Math.min(this.capacity, this.tokens + earned);
this.lastRefill = now;   // ← advances even when `earned` floored to 0
```

### Why it matters

`refill` is called on every `tryConsume`, which is every `RateLimiter.check`,
which is every request. Under the default config (`refillPerSecond: 5`) a
client calling more often than once per 200ms earns `Math.floor(<1) === 0`
every time while `lastRefill` still jumps forward. The bucket then **never
refills** — once drained, a busy client is locked out indefinitely, and the
busier it is the more completely it starves. Traffic light enough to leave
200ms gaps between calls refills normally, so the failure only appears under
load.

The pre-change code had the same shape without the floor, and carried the
fraction implicitly by keeping `tokens` fractional.

### Acceptable identifications

A finding counts as a match if it identifies the discarded remainder or the
unconditional `lastRefill` advance, in `src/bucket.ts`, at or near `refill`.
Phrasings seen as equivalent:

- "flooring drops sub-token time, which is never credited back"
- "`lastRefill` is updated even when no tokens were granted"
- "high-frequency callers never accrue tokens"
- "the bucket starves when the call interval is shorter than one token period"

### Not a match

- Noting only that `remaining` is now an integer (that is the intended change).
- Flagging `Math.min(this.capacity, …)` as wrong — the clamp is correct.
- Generic "consider using a monotonic clock" style commentary.
