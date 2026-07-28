import type { Db } from '../db/client.js';
import type { ReservationRow } from '../db/rows.js';
import { toReservation } from '../db/rows.js';
import type { Tx } from '../db/tx.js';
import { ConflictError, NotFoundError } from '../domain/errors.js';
import type {
  Reservation,
  ReservationId,
  ReservationLine,
  ReservationStatus,
} from '../domain/reservation.js';
import { canTransition } from '../domain/reservation.js';
import type { Sku } from '../domain/sku.js';
import type { WarehouseId } from '../domain/warehouse.js';
import type { Clock } from '../util/clock.js';
import type { IdGenerator } from '../util/id.js';
import { BaseRepo } from './base-repo.js';
import type { InventoryRepo } from './inventory-repo.js';

/**
 * Reservations, and the stock movements that belong to a reservation's
 * lifecycle.
 *
 * This repository writes the inventory table as well as its own. That is
 * deliberate and it is the reason `InventoryRepo` exposes `*Within` forms: a
 * reservation's status and the units it is holding are two halves of one fact,
 * and the driver gives us no way to join two repositories' transactions after
 * the event. Splitting them across two commits would leave a window in which
 * the ledger says stock is spoken for by a reservation that is already dead.
 *
 * The rule that follows from that, and which every caller depends on: **a
 * method here that ends a reservation also returns its held units.** Callers
 * move the reservation; they do not move the stock.
 */
export class ReservationRepo extends BaseRepo {
  constructor(
    db: Db,
    private readonly inventory: InventoryRepo,
    private readonly clock: Clock,
    private readonly ids: IdGenerator,
  ) {
    super(db);
  }

  async findById(id: ReservationId): Promise<Reservation | null> {
    const row = this.db.read().reservations.find((candidate) => candidate.id === id);
    return row === undefined ? null : toReservation(row);
  }

  async findByOrderRef(orderRef: string): Promise<Reservation[]> {
    return this.db
      .read()
      .reservations.filter((row) => row.order_ref === orderRef)
      .map(toReservation);
  }

  /**
   * Pending reservations whose TTL has elapsed, oldest first, capped at
   * `limit`. Ordering by expiry keeps a backlog draining in the order it
   * accumulated rather than starving the oldest rows.
   */
  async findDueForExpiry(now: number, limit: number): Promise<Reservation[]> {
    return this.db
      .read()
      .reservations.filter((row) => row.status === 'pending' && row.expires_at <= now)
      .sort((left, right) => left.expires_at - right.expires_at)
      .slice(0, limit)
      .map(toReservation);
  }

  /** Creates a reservation and holds its lines, atomically. */
  async create(
    warehouseId: WarehouseId,
    orderRef: string,
    lines: readonly ReservationLine[],
    ttlMs: number,
  ): Promise<Reservation> {
    return this.inTransaction(async (tx) => {
      const now = this.clock.now();
      for (const line of lines) {
        await this.inventory.holdWithin(tx, warehouseId, line.sku, line.quantity);
      }
      const row: ReservationRow = {
        id: this.ids.next('rsv'),
        warehouse_id: warehouseId,
        order_ref: orderRef,
        status: 'pending',
        lines: lines.map((line) => ({ sku: line.sku, quantity: line.quantity })),
        created_at: now,
        expires_at: now + ttlMs,
      };
      tx.tables.reservations.push(row);
      return toReservation(row);
    });
  }

  async markConfirmed(id: ReservationId): Promise<Reservation> {
    return this.inTransaction(async (tx) => {
      const row = this.requireRowIn(tx, id);
      this.assertTransition(row, 'confirmed');
      row.status = 'confirmed';
      return toReservation(row);
    });
  }

  /**
   * Expires a pending reservation.
   *
   * Expiry is two facts — the reservation is dead, and the units it was
   * holding are free — so this method commits both together: it moves the row
   * to `expired` and releases every one of its lines inside the same
   * transaction. Nothing else needs to release them, and nothing else may:
   * `InventoryRepo.releaseWithin` cannot tell a duplicate release from a real
   * one, so a caller that releases as well leaves the ledger holding fewer
   * units than it has promised.
   *
   * Returns `null` when the reservation has already left `pending` — another
   * sweeper worker got there first, or the order was confirmed in the window.
   */
  async markExpired(id: ReservationId): Promise<Reservation | null> {
    return this.inTransaction(async (tx) => {
      const row = this.requireRowIn(tx, id);
      if (row.status !== 'pending') {
        return null;
      }
      await this.releaseLines(tx, row);
      row.status = 'expired';
      return toReservation(row);
    });
  }

  /**
   * Cancels a reservation before it is picked, returning its held units in the
   * same transaction. Same contract as `markExpired`.
   */
  async markReleased(id: ReservationId): Promise<Reservation> {
    return this.inTransaction(async (tx) => {
      const row = this.requireRowIn(tx, id);
      this.assertTransition(row, 'released');
      await this.releaseLines(tx, row);
      row.status = 'released';
      return toReservation(row);
    });
  }

  /**
   * Picking. The units leave the shelf rather than returning to the pool, so
   * this consumes the hold instead of releasing it.
   */
  async markPicked(id: ReservationId): Promise<Reservation> {
    return this.inTransaction(async (tx) => {
      const row = this.requireRowIn(tx, id);
      this.assertTransition(row, 'picked');
      for (const line of row.lines) {
        await this.inventory.consumeWithin(
          tx,
          row.warehouse_id as WarehouseId,
          line.sku as Sku,
          line.quantity,
        );
      }
      row.status = 'picked';
      return toReservation(row);
    });
  }

  private async releaseLines(tx: Tx, row: ReservationRow): Promise<void> {
    for (const line of row.lines) {
      await this.inventory.releaseWithin(
        tx,
        row.warehouse_id as WarehouseId,
        line.sku as Reservation['lines'][number]['sku'],
        line.quantity,
      );
    }
  }

  private requireRowIn(tx: Tx, id: ReservationId): ReservationRow {
    const row = tx.tables.reservations.find((candidate) => candidate.id === id);
    if (row === undefined) {
      throw new NotFoundError('reservation', id);
    }
    return row;
  }

  private assertTransition(row: ReservationRow, to: ReservationStatus): void {
    const from = row.status as ReservationStatus;
    if (!canTransition(from, to)) {
      throw new ConflictError(`reservation ${row.id} cannot move from ${from} to ${to}`);
    }
  }
}
