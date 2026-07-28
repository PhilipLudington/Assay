import type { InventoryRepo } from '../repositories/inventory-repo.js';
import type { ReservationRepo } from '../repositories/reservation-repo.js';
import type { Clock } from '../util/clock.js';
import { describeError, type Logger } from '../util/logger.js';
import type { Metrics } from '../util/metrics.js';
import type { Job, JobRunSummary } from './job.js';

/**
 * Expires reservations that were never confirmed.
 *
 * A reservation that nobody confirmed inside the warehouse's TTL is dead
 * weight: the order it was created for is gone, but the units it asked for are
 * still promised to it, so the sweeper has to put them back where the next
 * customer can buy them.
 *
 * Each tick takes a bounded batch, oldest expiry first. Anything left over is
 * picked up on the following tick rather than in one long transaction, so a
 * backlog drains steadily instead of stalling the ledger.
 */
export class ReservationSweeper implements Job {
  readonly name = 'reservation-sweep';

  constructor(
    private readonly reservations: ReservationRepo,
    private readonly inventory: InventoryRepo,
    private readonly clock: Clock,
    private readonly logger: Logger,
    private readonly metrics: Metrics,
    private readonly config: { intervalMs: number; batchSize: number },
  ) {}

  get intervalMs(): number {
    return this.config.intervalMs;
  }

  async runOnce(): Promise<JobRunSummary> {
    const now = this.clock.now();
    const due = await this.reservations.findDueForExpiry(now, this.config.batchSize);
    if (due.length === 0) {
      return { processed: 0, failed: 0 };
    }

    let processed = 0;
    let failed = 0;

    for (const reservation of due) {
      try {
        for (const line of reservation.lines) {
          await this.inventory.release(reservation.warehouseId, line.sku, line.quantity);
        }

        const expired = await this.reservations.markExpired(reservation.id);
        if (expired === null) {
          this.metrics.increment('sweep.already_settled');
          continue;
        }

        processed += 1;
        this.metrics.increment('sweep.expired');
        this.logger.log('info', 'sweep.reservation_expired', {
          reservationId: reservation.id,
          orderRef: reservation.orderRef,
          lines: reservation.lines.length,
        });
      } catch (error) {
        // One unhappy reservation must not stop the batch; it stays pending
        // and the next tick picks it up again.
        failed += 1;
        this.metrics.increment('sweep.failed');
        this.logger.log('warn', 'sweep.reservation_failed', {
          reservationId: reservation.id,
          ...describeError(error),
        });
      }
    }

    this.logger.log('info', 'sweep.completed', {
      due: due.length,
      processed,
      failed,
      batchSize: this.config.batchSize,
    });

    return { processed, failed };
  }
}
