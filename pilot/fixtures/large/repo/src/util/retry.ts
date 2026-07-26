export interface RetryOptions {
  attempts: number;
  baseMs: number;
  maxMs: number;
  retryOn?: (error: unknown) => boolean;
}

export const DEFAULT_RETRY: RetryOptions = { attempts: 3, baseMs: 200, maxMs: 5_000 };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Retries transient work — used for carrier API calls, not for our own store. */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = DEFAULT_RETRY,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= options.attempts; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (options.retryOn && !options.retryOn(error)) {
        throw error;
      }
      if (attempt === options.attempts) {
        break;
      }
      await sleep(Math.min(options.maxMs, options.baseMs * 2 ** (attempt - 1)));
    }
  }
  throw lastError;
}
