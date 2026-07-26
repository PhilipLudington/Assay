import { ForbiddenError } from '../auth/principal.js';
import { HttpError } from '../http/errors.js';
import { problem } from '../http/response.js';
import { Status } from '../http/status.js';
import { ConflictError, NotFoundError } from '../services/shipment-service.js';
import { UnknownCarrierError } from '../services/carrier-service.js';
import { ValidationError } from '../validation/schema.js';
import type { Middleware } from '../http/router.js';
import type { Logger } from '../util/logger.js';

/** Outermost middleware. Maps domain errors onto the wire format. */
export function errorHandlerMiddleware(logger: Logger): Middleware {
  return async (request, response, next) => {
    try {
      await next();
    } catch (error) {
      const log = logger.child({ requestId: request.requestId, path: request.path });

      if (error instanceof HttpError) {
        problem(response, error.status, error.code, error.message, error.details);
        return;
      }
      if (error instanceof ValidationError) {
        problem(response, Status.UnprocessableEntity, 'unprocessable_entity', error.message, error.errors);
        return;
      }
      if (error instanceof ForbiddenError) {
        problem(response, Status.Forbidden, 'forbidden', error.message);
        return;
      }
      if (error instanceof NotFoundError || error instanceof UnknownCarrierError) {
        problem(response, Status.NotFound, 'not_found', error.message);
        return;
      }
      if (error instanceof ConflictError) {
        problem(response, Status.Conflict, 'conflict', error.message);
        return;
      }

      log.log('error', 'unhandled error', { error: String(error) });
      problem(response, Status.InternalServerError, 'internal_error', 'something went wrong');
    }
  };
}
