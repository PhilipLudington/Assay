import { ConflictError, NotFoundError } from '../domain/errors.js';
import type { Reservation, ReservationId, ReservationLine } from '../domain/reservation.js';
import type { WarehouseId } from '../domain/warehouse.js';
import { acceptsNewReservations } from '../domain/warehouse.js';
import type { AuditRepo } from '../repositories/audit-repo.js';
import type { ReservationRepo } from '../repositories/reservation-repo.js';
import type { WarehouseRepo } from '../repositories/warehouse-repo.js';

/**
 * The reservation lifecycle as the API exposes it.
 *
 * Every method here is a thin coordination layer: it checks what the caller is
 * allowed to do, delegates the write to the repository, and records an audit
 * line. Stock movement is not coordinated here — the repository moves stock as
 * part of the status change it performs.
 */
export class ReservationService {
  constructor(
    private readonly reservations: ReservationRepo,
    private readonly warehouses: WarehouseRepo,
    private readonly audit: AuditRepo,
  ) {}

  async create(
    warehouseId: WarehouseId,
    orderRef: string,
    lines: readonly ReservationLine[],
  ): Promise<Reservation> {
    const warehouse = await this.warehouses.require(warehouseId);
    if (!acceptsNewReservations(warehouse)) {
      throw new ConflictError(`warehouse ${warehouse.code} is ${warehouse.mode}`);
    }
    if (lines.length === 0) {
      throw new ConflictError('a reservation needs at least one line');
    }

    const reservation = await this.reservations.create(
      warehouseId,
      orderRef,
      lines,
      warehouse.reservationTtlMs,
    );
    await this.audit.record(reservation.id, 'reservation.created', orderRef);
    return reservation;
  }

  async get(id: ReservationId): Promise<Reservation> {
    const reservation = await this.reservations.findById(id);
    if (reservation === null) {
      throw new NotFoundError('reservation', id);
    }
    return reservation;
  }

  async confirm(id: ReservationId): Promise<Reservation> {
    const reservation = await this.reservations.markConfirmed(id);
    await this.audit.record(id, 'reservation.confirmed', reservation.orderRef);
    return reservation;
  }

  /** Cancellation before picking. The held units go back with the status change. */
  async cancel(id: ReservationId, reason: string): Promise<Reservation> {
    const reservation = await this.reservations.markReleased(id);
    await this.audit.record(id, 'reservation.released', reason);
    return reservation;
  }

  async pick(id: ReservationId): Promise<Reservation> {
    const reservation = await this.reservations.markPicked(id);
    await this.audit.record(id, 'reservation.picked', reservation.orderRef);
    return reservation;
  }

  async forOrder(orderRef: string): Promise<Reservation[]> {
    return this.reservations.findByOrderRef(orderRef);
  }
}
