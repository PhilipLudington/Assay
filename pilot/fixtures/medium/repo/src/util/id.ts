import { randomUUID } from 'node:crypto';
import type { JobId } from '../types.js';

/** Job ids are opaque to everything except the store's index. */
export function newJobId(): JobId {
  return `job_${randomUUID().replace(/-/g, '').slice(0, 20)}`;
}

export function newWorkerId(): string {
  return `wrk_${randomUUID().slice(0, 8)}`;
}

/**
 * Stable key for dedupe. Two enqueues with the same name and key collapse
 * into one job while the first is still pending.
 */
export function dedupeKeyFor(name: string, key: string | undefined): string | undefined {
  return key === undefined ? undefined : `${name}::${key}`;
}
