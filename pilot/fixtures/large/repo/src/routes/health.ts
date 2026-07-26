import { json } from '../http/response.js';
import { Router } from '../http/router.js';
import { Status } from '../http/status.js';
import type { Clock } from '../util/clock.js';

/** Public. Deliberately mounted before the auth middleware. */
export function healthRoutes(clock: Clock, version: string): Router {
  const startedAt = clock.now();
  const router = new Router();

  router.get('/health', (_request, response) => {
    json(response, Status.Ok, { status: 'ok', version });
  });

  router.get('/health/ready', (_request, response) => {
    json(response, Status.Ok, {
      status: 'ok',
      version,
      uptimeMs: clock.now() - startedAt,
    });
  });

  return router;
}
