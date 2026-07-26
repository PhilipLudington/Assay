import { type Clock, systemClock } from './clock.js';
import { type LimiterConfig, resolveConfig } from './config.js';
import { RateLimitError } from './errors.js';
import { BucketStore } from './store.js';
import type { BucketSnapshot, ClientId, Decision } from './types.js';

/**
 * Entry point. Wraps a bucket store with a clock and the two calling styles
 * we support: a decision object, or a throw.
 */
export class RateLimiter {
  private readonly store: BucketStore;
  private readonly clock: Clock;
  readonly config: LimiterConfig;

  constructor(partial: Partial<LimiterConfig> = {}, clock: Clock = systemClock) {
    this.config = resolveConfig(partial);
    this.store = new BucketStore(this.config);
    this.clock = clock;
  }

  /** Non-throwing form. Returns whether the call may proceed. */
  check(clientId: ClientId, cost = 1): Decision {
    const now = this.clock.now();
    return this.store.acquire(clientId, now).tryConsume(cost, now);
  }

  /** Throwing form, for use as a guard at the top of a handler. */
  consume(clientId: ClientId, cost = 1): void {
    const decision = this.check(clientId, cost);
    if (!decision.allowed) {
      throw new RateLimitError(clientId, decision.retryAfterMs);
    }
  }

  /** Drop buckets that have gone quiet. Safe to call on a timer. */
  sweep(): number {
    return this.store.evictIdle(this.clock.now());
  }

  trackedClients(): number {
    return this.store.size();
  }

  inspect(): BucketSnapshot[] {
    return this.store.snapshot();
  }

  reset(): void {
    this.store.clear();
  }
}
