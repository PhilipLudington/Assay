import { header } from '../http/request.js';
import type { Middleware } from '../http/router.js';
import type { IdGenerator } from '../util/id.js';

export const REQUEST_ID_HEADER = 'x-request-id';

/**
 * Every response carries a request id, either the one the gateway supplied or
 * one minted here. Support tickets quote it, so it must exist even for the
 * failure paths.
 */
export function withRequestId(ids: IdGenerator): Middleware {
  return (next) => async (request) => {
    const incoming = header(request, REQUEST_ID_HEADER) ?? ids.next('req');
    const response = await next({
      ...request,
      headers: { ...request.headers, [REQUEST_ID_HEADER]: incoming },
    });
    return {
      ...response,
      headers: { ...response.headers, [REQUEST_ID_HEADER]: incoming },
    };
  };
}
