import { AuditPruner } from './audit-pruner.js';
import type { JobDeps } from './deps.js';
import type { Job } from './job.js';
import { ReservationSweeper } from './reservation-sweeper.js';

/**
 * The background jobs this service runs, in the order the runner ticks them.
 * Adding a job means adding it here; nothing discovers jobs by scanning.
 */
export function buildJobs(deps: JobDeps): Job[] {
  return [
    new AuditPruner(
      deps.audit,
      deps.clock,
      deps.logger.child({ job: 'audit-prune' }),
      deps.metrics,
      deps.config.jobs.auditPrune,
    ),
    new ReservationSweeper(
      deps.reservations,
      deps.inventory,
      deps.clock,
      deps.logger.child({ job: 'reservation-sweep' }),
      deps.metrics,
      deps.config.jobs.reservationSweep,
    ),
  ];
}
