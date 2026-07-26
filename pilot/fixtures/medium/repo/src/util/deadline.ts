import { JobTimeoutError } from '../errors.js';
import type { JobId } from '../types.js';

export interface Deadline {
  at: number;
  signal: AbortSignal;
  cancel(): void;
}

/** Creates an abortable deadline `afterMs` from `now`. */
export function startDeadline(now: number, afterMs: number): Deadline {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), afterMs);
  if (typeof timer.unref === 'function') {
    timer.unref();
  }
  return {
    at: now + afterMs,
    signal: controller.signal,
    cancel: () => clearTimeout(timer),
  };
}

/** Rejects with JobTimeoutError if `work` outlives the deadline. */
export async function withDeadline<T>(
  jobId: JobId,
  afterMs: number,
  deadline: Deadline,
  work: Promise<T>,
): Promise<T> {
  const timeout = new Promise<never>((_, reject) => {
    deadline.signal.addEventListener(
      'abort',
      () => reject(new JobTimeoutError(jobId, afterMs)),
      { once: true },
    );
  });
  try {
    return await Promise.race([work, timeout]);
  } finally {
    deadline.cancel();
  }
}
