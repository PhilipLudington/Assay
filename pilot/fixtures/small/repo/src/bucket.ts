import type { Decision, BucketSnapshot, ClientId, Millis } from './types.js';

/**
 * A single client's token bucket.
 *
 * Tokens accrue continuously with elapsed time and are capped at `capacity`,
 * so `capacity` doubles as the maximum burst a client can spend at once.
 */
export class TokenBucket {
  readonly clientId: ClientId;
  readonly capacity: number;
  readonly refillPerSecond: number;

  private tokens: number;
  private lastRefill: Millis;

  constructor(clientId: ClientId, capacity: number, refillPerSecond: number, now: Millis) {
    this.clientId = clientId;
    this.capacity = capacity;
    this.refillPerSecond = refillPerSecond;
    this.tokens = capacity;
    this.lastRefill = now;
  }

  /**
   * Grant the whole tokens earned since the last refill and advance the
   * refill mark to `now`.
   */
  private refill(now: Millis): void {
    const elapsed = now - this.lastRefill;
    if (elapsed <= 0) {
      return;
    }
    const earned = Math.floor((elapsed / 1000) * this.refillPerSecond);
    this.tokens = Math.min(this.capacity, this.tokens + earned);
    this.lastRefill = now;
  }

  tryConsume(cost: number, now: Millis): Decision {
    if (cost <= 0) {
      throw new RangeError('cost must be positive');
    }
    this.refill(now);

    if (this.tokens >= cost) {
      this.tokens -= cost;
      return { allowed: true, remaining: this.tokens, retryAfterMs: 0 };
    }

    const deficit = cost - this.tokens;
    const retryAfterMs = Math.ceil((deficit / this.refillPerSecond) * 1000);
    return { allowed: false, remaining: this.tokens, retryAfterMs };
  }

  /** Last time this bucket was touched, used by the store for eviction. */
  idleSince(): Millis {
    return this.lastRefill;
  }

  snapshot(): BucketSnapshot {
    return {
      clientId: this.clientId,
      tokens: this.tokens,
      capacity: this.capacity,
      lastRefill: this.lastRefill,
    };
  }
}
