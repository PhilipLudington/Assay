import type { Router } from '../http/router.js';
import { ok } from '../http/response.js';
import type { Clock } from '../util/clock.js';
import type { InMemoryMetrics } from '../util/metrics.js';

export function registerHealthRoutes(
  router: Router,
  clock: Clock,
  metrics: InMemoryMetrics,
  serviceName: string,
): void {
  const startedAt = clock.now();

  router.get('/health', async () =>
    ok({ service: serviceName, status: 'ok', uptimeMs: clock.now() - startedAt }),
  );

  router.get('/health/metrics', async () => ok(metrics.snapshot()));
}
