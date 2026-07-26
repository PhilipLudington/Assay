import { HttpError } from '../http/errors.js';
import type { Middleware } from '../http/router.js';
import { Status } from '../http/status.js';
import type { Clock } from '../util/clock.js';

interface Window {
  count: number;
  resetAt: number;
}

export interface RateLimitOptions {
  limit: number;
  windowMs: number;
}

export const DEFAULT_RATE_LIMIT: RateLimitOptions = { limit: 600, windowMs: 60_000 };

/** Fixed-window limiter keyed on the authenticated account. */
export function rateLimitMiddleware(
  clock: Clock,
  options: RateLimitOptions = DEFAULT_RATE_LIMIT,
): Middleware {
  const windows = new Map<string, Window>();

  return async (request, response, next) => {
    const key = request.principal?.accountId ?? 'anonymous';
    const now = clock.now();
    let window = windows.get(key);

    if (!window || window.resetAt <= now) {
      window = { count: 0, resetAt: now + options.windowMs };
      windows.set(key, window);
    }

    window.count += 1;
    const remaining = Math.max(0, options.limit - window.count);
    response.raw.setHeader('x-ratelimit-limit', String(options.limit));
    response.raw.setHeader('x-ratelimit-remaining', String(remaining));
    response.raw.setHeader('x-ratelimit-reset', String(Math.ceil(window.resetAt / 1000)));

    if (window.count > options.limit) {
      throw new HttpError(
        Status.TooManyRequests,
        'rate_limited',
        `rate limit of ${options.limit} requests per window exceeded`,
      );
    }

    await next();
  };
}
