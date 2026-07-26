import { backoffFor, DEFAULT_BACKOFF, type BackoffOptions } from './backoff.js';
import type { JobRecord } from '../types.js';

export type RetryDecision =
  | { action: 'retry'; availableAt: number; delayMs: number }
  | { action: 'dead'; reason: string };

export interface RetryPolicy {
  decide(record: JobRecord, error: unknown, now: number): RetryDecision;
}

/** Errors marked non-retryable skip the remaining attempts entirely. */
export class NonRetryableError extends Error {
  readonly nonRetryable = true;
}

function isNonRetryable(error: unknown): boolean {
  return (
    error instanceof NonRetryableError ||
    (typeof error === 'object' && error !== null && 'nonRetryable' in error)
  );
}

export class ExponentialRetryPolicy implements RetryPolicy {
  constructor(private readonly backoff: BackoffOptions = DEFAULT_BACKOFF) {}

  decide(record: JobRecord, error: unknown, now: number): RetryDecision {
    if (isNonRetryable(error)) {
      return { action: 'dead', reason: 'handler marked the failure non-retryable' };
    }
    if (record.attempt >= record.maxAttempts) {
      return { action: 'dead', reason: `exhausted ${record.maxAttempts} attempts` };
    }
    const delayMs = backoffFor(record.attempt, this.backoff);
    return { action: 'retry', availableAt: now + delayMs, delayMs };
  }
}
