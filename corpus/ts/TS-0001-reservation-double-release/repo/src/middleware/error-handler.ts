import { statusFor, toResponse } from '../http/errors.js';
import type { Middleware } from '../http/router.js';
import { describeError, type Logger } from '../util/logger.js';
import type { Metrics } from '../util/metrics.js';

/**
 * Turns a thrown error into a response exactly once, at the outermost layer.
 * Handlers below this throw freely; none of them format an error themselves.
 */
export function handleErrors(logger: Logger, metrics: Metrics): Middleware {
  return (next) => async (request) => {
    try {
      return await next(request);
    } catch (error) {
      const status = statusFor(error);
      metrics.increment(`http.error.${status}`);
      logger.log(status >= 500 ? 'error' : 'warn', 'http.request_failed', {
        method: request.method,
        path: request.path,
        status,
        ...describeError(error),
      });
      return toResponse(error);
    }
  };
}
