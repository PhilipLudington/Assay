import { headerOf } from '../http/request.js';
import type { Middleware } from '../http/router.js';
import { requestId } from '../util/id.js';

const HEADER = 'x-request-id';

/** Adopts an inbound request id when present so traces stitch across hops. */
export function requestIdMiddleware(): Middleware {
  return async (request, response, next) => {
    request.requestId = headerOf(request, HEADER) ?? requestId();
    response.raw.setHeader(HEADER, request.requestId);
    await next();
  };
}
