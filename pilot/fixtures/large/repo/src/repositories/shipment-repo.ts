import type { Shipment, ShipmentPatch, ShipmentStatus } from '../domain/shipment.js';
import type { TrackingEvent } from '../domain/tracking-event.js';
import type { EventRepo } from './event-repo.js';
import { BaseRepo } from './base-repo.js';

export class ShipmentRepo extends BaseRepo<Shipment> {
  constructor(private readonly events: EventRepo) {
    super();
  }

  async byReference(reference: string): Promise<Shipment | undefined> {
    return (await this.findAll()).find((shipment) => shipment.reference === reference);
  }

  async byTrackingNumber(trackingNumber: string): Promise<Shipment | undefined> {
    return (await this.findAll()).find(
      (shipment) => shipment.trackingNumber === trackingNumber,
    );
  }

  async byStatus(status: ShipmentStatus): Promise<Shipment[]> {
    return (await this.findAll()).filter((shipment) => shipment.status === status);
  }

  /**
   * Raw row write. Does **not** append a tracking event.
   *
   * A shipment's history is reconstructed entirely from the event log — the
   * customer-facing tracking page, the carrier reconciliation job and the
   * outbound webhook fan-out all read `EventRepo`, never this table's audit
   * columns. A mutation written through here is therefore invisible to all
   * three, and the gap is not detectable after the fact.
   *
   * This exists for migrations and for the reconciliation job, which appends
   * its own events in bulk afterwards. **Anything reachable from a route must
   * go through `updateWithEvent`, or through a service method that does.**
   */
  async update(id: string, patch: ShipmentPatch, now: string): Promise<Shipment | undefined> {
    const existing = this.rows.get(id);
    if (!existing) {
      return undefined;
    }
    const next: Shipment = { ...existing, ...patch, id: existing.id, updatedAt: now };
    this.rows.set(id, next);
    return structuredClone(next);
  }

  /** The write path every caller outside a migration should use. */
  async updateWithEvent(
    id: string,
    patch: ShipmentPatch,
    event: TrackingEvent,
    now: string,
  ): Promise<Shipment | undefined> {
    const updated = await this.update(id, patch, now);
    if (!updated) {
      return undefined;
    }
    await this.events.append(event);
    return updated;
  }

  async setStatus(
    id: string,
    status: ShipmentStatus,
    event: TrackingEvent,
    now: string,
  ): Promise<Shipment | undefined> {
    const existing = this.rows.get(id);
    if (!existing) {
      return undefined;
    }
    this.rows.set(id, { ...existing, status, updatedAt: now });
    await this.events.append(event);
    return structuredClone(this.rows.get(id) as Shipment);
  }
}
