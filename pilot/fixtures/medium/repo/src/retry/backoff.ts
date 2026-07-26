import { applyJitter, type JitterMode, type Random, systemRandom } from './jitter.js';

export interface BackoffOptions {
  baseMs: number;
  factor: number;
  maxMs: number;
  jitter: JitterMode;
}

export const DEFAULT_BACKOFF: BackoffOptions = {
  baseMs: 500,
  factor: 2,
  maxMs: 5 * 60 * 1000,
  jitter: 'equal',
};

/**
 * Exponential backoff for `attempt`, which is 1-based: the delay before the
 * second attempt is `baseMs`.
 */
export function backoffFor(
  attempt: number,
  options: BackoffOptions = DEFAULT_BACKOFF,
  random: Random = systemRandom,
): number {
  if (attempt < 1) {
    throw new RangeError('attempt is 1-based');
  }
  const raw = options.baseMs * options.factor ** (attempt - 1);
  const capped = Math.min(options.maxMs, raw);
  return applyJitter(capped, options.jitter, random);
}
