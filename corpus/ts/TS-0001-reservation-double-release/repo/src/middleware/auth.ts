import { UnauthorizedError } from '../http/errors.js';
import { header } from '../http/request.js';
import type { Middleware } from '../http/router.js';

/**
 * Guards the internal control-plane routes.
 *
 * The public routes sit behind the edge gateway, which has already
 * authenticated the caller and stripped anything it did not issue. These
 * routes do not, so they carry their own shared-secret check.
 */
export function requireInternalToken(tokens: readonly string[]): Middleware {
  const accepted = new Set(tokens);
  return (next) => async (request) => {
    const presented = header(request, 'x-internal-token');
    if (presented === undefined || !accepted.has(presented)) {
      throw new UnauthorizedError('internal token not accepted');
    }
    return next(request);
  };
}

export function requireOperator(): Middleware {
  return (next) => async (request) => {
    const role = header(request, 'x-gateway-role');
    if (role !== 'operator' && role !== 'admin') {
      throw new UnauthorizedError('operator role required');
    }
    return next(request);
  };
}
