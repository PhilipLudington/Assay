import type { StockroomConfig } from '../config/schema.js';
import type { AuditRepo } from '../repositories/audit-repo.js';
import type { InventoryRepo } from '../repositories/inventory-repo.js';
import type { ReservationRepo } from '../repositories/reservation-repo.js';
import type { WarehouseRepo } from '../repositories/warehouse-repo.js';
import type { Clock } from '../util/clock.js';
import type { Logger } from '../util/logger.js';
import type { Metrics } from '../util/metrics.js';

/**
 * Everything the background jobs are allowed to reach.
 *
 * One bag for all of them, rather than a bespoke interface per job: jobs come
 * and go, and a shared bag means adding one is a change to the registry alone
 * instead of a change that ripples back through the composition root.
 */
export interface JobDeps {
  audit: AuditRepo;
  reservations: ReservationRepo;
  inventory: InventoryRepo;
  warehouses: WarehouseRepo;
  clock: Clock;
  logger: Logger;
  metrics: Metrics;
  config: StockroomConfig;
}
