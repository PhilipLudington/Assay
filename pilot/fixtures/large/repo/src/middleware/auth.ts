import { InvalidTokenError, verifyToken } from '../auth/token.js';
import { unauthorized } from '../http/errors.js';
import { headerOf } from '../http/request.js';
import type { Middleware } from '../http/router.js';
import type { Clock } from '../util/clock.js';

/**
 * Establishes *who* the caller is and attaches the principal to the request.
 *
 * It deliberately performs no authorisation: scopes vary per route and per
 * method, so there is nothing sensible to check here. Each handler is
 * responsible for calling `requireScope` with the scope that handler needs.
 * A route that omits that call is authenticated but unrestricted.
 */
export function authMiddleware(secret: string, clock: Clock): Middleware {
  return async (request, _response, next) => {
    const header = headerOf(request, 'authorization');
    if (!header || !header.startsWith('Bearer ')) {
      throw unauthorized('missing bearer token');
    }

    try {
      request.principal = verifyToken(header.slice('Bearer '.length), secret, clock.now());
    } catch (error) {
      if (error instanceof InvalidTokenError) {
        throw unauthorized(error.message);
      }
      throw error;
    }

    await next();
  };
}
