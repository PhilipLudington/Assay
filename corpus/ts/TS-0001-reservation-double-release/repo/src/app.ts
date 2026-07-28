import type { StockroomConfig } from './config/schema.js';
import { Db } from './db/client.js';
import type { Tables } from './db/tx.js';
import { emptyTables } from './db/tx.js';
import { applyMiddleware, Router, type Handler } from './http/router.js';
import { buildJobs } from './jobs/registry.js';
import { JobRunner } from './jobs/job.js';
import { handleErrors } from './middleware/error-handler.js';
import { withRequestId } from './middleware/request-id.js';
import { AuditRepo } from './repositories/audit-repo.js';
import { InventoryRepo } from './repositories/inventory-repo.js';
import { ReservationRepo } from './repositories/reservation-repo.js';
import { WarehouseRepo } from './repositories/warehouse-repo.js';
import { registerHealthRoutes } from './routes/health.js';
import { registerInternalRoutes } from './routes/internal.js';
import { registerInventoryRoutes } from './routes/inventory.js';
import { registerReservationRoutes } from './routes/reservations.js';
import { AllocationService } from './services/allocation-service.js';
import { InventoryService } from './services/inventory-service.js';
import { ReservationService } from './services/reservation-service.js';
import { systemClock, type Clock } from './util/clock.js';
import { ConsoleLogger, type Logger } from './util/logger.js';
import { CounterIdGenerator, type IdGenerator } from './util/id.js';
import { InMemoryMetrics } from './util/metrics.js';

export interface AppOverrides {
  clock?: Clock;
  logger?: Logger;
  ids?: IdGenerator;
  tables?: Tables;
}

export interface StockroomApp {
  handle: Handler;
  jobs: JobRunner;
  metrics: InMemoryMetrics;
}

/**
 * The composition root. Everything is constructed here and nothing constructs
 * its own dependencies, so a test can swap the clock or the tables without the
 * production wiring knowing about it.
 */
export function createApp(config: StockroomConfig, overrides: AppOverrides = {}): StockroomApp {
  const clock = overrides.clock ?? systemClock;
  const logger =
    overrides.logger ?? new ConsoleLogger((line) => void line, { service: config.serviceName });
  const ids = overrides.ids ?? new CounterIdGenerator();
  const metrics = new InMemoryMetrics();

  const db = new Db(overrides.tables ?? emptyTables());
  const inventoryRepo = new InventoryRepo(db, clock);
  const reservationRepo = new ReservationRepo(db, inventoryRepo, clock, ids);
  const warehouseRepo = new WarehouseRepo(db);
  const auditRepo = new AuditRepo(db, clock, ids);

  const inventoryService = new InventoryService(inventoryRepo, warehouseRepo, auditRepo);
  const reservationService = new ReservationService(reservationRepo, warehouseRepo, auditRepo);
  const allocationService = new AllocationService(warehouseRepo, inventoryRepo);

  const router = new Router();
  registerHealthRoutes(router, clock, metrics, config.serviceName);
  registerReservationRoutes(router, reservationService);
  registerInventoryRoutes(router, inventoryService, inventoryRepo);
  registerInternalRoutes(router, warehouseRepo, allocationService, config.internalTokens);

  const handle = applyMiddleware((request) => router.handle(request), [
    handleErrors(logger, metrics),
    withRequestId(ids),
  ]);

  const jobs = new JobRunner(
    buildJobs({
      audit: auditRepo,
      reservations: reservationRepo,
      inventory: inventoryRepo,
      warehouses: warehouseRepo,
      clock,
      logger,
      metrics,
      config,
    }),
    clock,
    logger,
    metrics,
  );

  return { handle, jobs, metrics };
}
