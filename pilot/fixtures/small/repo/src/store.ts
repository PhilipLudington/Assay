import { TokenBucket } from './bucket.js';
import type { LimiterConfig } from './config.js';
import type { BucketSnapshot, ClientId, Millis } from './types.js';

/**
 * Holds one bucket per client. Buckets are created lazily and dropped once
 * they have been idle long enough that recreating one at full capacity is
 * equivalent to keeping it.
 */
export class BucketStore {
  private readonly buckets = new Map<ClientId, TokenBucket>();

  constructor(private readonly config: LimiterConfig) {}

  acquire(clientId: ClientId, now: Millis): TokenBucket {
    const existing = this.buckets.get(clientId);
    if (existing) {
      return existing;
    }

    if (this.buckets.size >= this.config.maxTrackedClients) {
      this.evictIdle(now);
    }
    if (this.buckets.size >= this.config.maxTrackedClients) {
      this.evictOldest();
    }

    const created = new TokenBucket(
      clientId,
      this.config.capacity,
      this.config.refillPerSecond,
      now,
    );
    this.buckets.set(clientId, created);
    return created;
  }

  evictIdle(now: Millis): number {
    let removed = 0;
    for (const [clientId, bucket] of this.buckets) {
      if (now - bucket.idleSince() > this.config.idleEvictionMs) {
        this.buckets.delete(clientId);
        removed += 1;
      }
    }
    return removed;
  }

  private evictOldest(): void {
    let oldestId: ClientId | undefined;
    let oldestAt = Number.POSITIVE_INFINITY;
    for (const [clientId, bucket] of this.buckets) {
      if (bucket.idleSince() < oldestAt) {
        oldestAt = bucket.idleSince();
        oldestId = clientId;
      }
    }
    if (oldestId !== undefined) {
      this.buckets.delete(oldestId);
    }
  }

  size(): number {
    return this.buckets.size;
  }

  snapshot(): BucketSnapshot[] {
    return [...this.buckets.values()].map((bucket) => bucket.snapshot());
  }

  clear(): void {
    this.buckets.clear();
  }
}
