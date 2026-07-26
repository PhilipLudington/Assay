/** Public shapes shared across the limiter. */

/** Identifies the subject being limited — an API key, a user id, an IP. */
export type ClientId = string;

/** Milliseconds since the Unix epoch. */
export type Millis = number;

export interface Decision {
  /** Whether the caller may proceed. */
  allowed: boolean;
  /** Tokens left in the bucket after this decision. */
  remaining: number;
  /**
   * Milliseconds until at least one token is available again. Zero when the
   * request was allowed.
   */
  retryAfterMs: number;
}

export interface BucketSnapshot {
  clientId: ClientId;
  tokens: number;
  capacity: number;
  lastRefill: Millis;
}

/** Anything that can hand out per-client buckets. */
export interface BucketSource {
  acquire(clientId: ClientId, now: Millis): { tryConsume(cost: number, now: Millis): Decision };
  size(): number;
}
