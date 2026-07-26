import type { Shipment, ShipmentPatch } from '../domain/shipment.js';
import { isEditable } from '../domain/shipment.js';
import type { TrackingEvent } from '../domain/tracking-event.js';
import type { ShipmentRepo } from '../repositories/shipment-repo.js';
import type { EventRepo } from '../repositories/event-repo.js';
import type { Clock } from '../util/clock.js';
import { eventId, shipmentId, trackingNumber } from '../util/id.js';
import type { WebhookService } from './webhook-service.js';

export class NotFoundError extends Error {
  constructor(id: string) {
    super(`shipment ${id} not found`);
    this.name = 'NotFoundError';
  }
}

export class ConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConflictError';
  }
}

/**
 * All shipment mutation belongs here. Every method that changes a shipment
 * writes the row and the tracking event together, then hands the event to the
 * webhook fan-out.
 */
export class ShipmentService {
  constructor(
    private readonly shipments: ShipmentRepo,
    private readonly events: EventRepo,
    private readonly webhooks: WebhookService,
    private readonly clock: Clock,
  ) {}

  async byId(id: string): Promise<Shipment | undefined> {
    return this.shipments.findById(id);
  }

  async requireById(id: string): Promise<Shipment> {
    const shipment = await this.byId(id);
    if (!shipment) {
      throw new NotFoundError(id);
    }
    return shipment;
  }

  async create(
    input: Omit<Shipment, 'id' | 'status' | 'trackingNumber' | 'createdAt' | 'updatedAt'>,
    actor: string,
  ): Promise<Shipment> {
    const now = this.clock.isoNow();
    const shipment: Shipment = {
      ...input,
      id: shipmentId(),
      status: 'draft',
      trackingNumber: null,
      createdAt: now,
      updatedAt: now,
    };
    await this.shipments.insert(shipment);
    await this.emit(shipment.id, 'created', actor, now);
    return shipment;
  }

  async book(id: string, actor: string): Promise<Shipment> {
    const shipment = await this.requireById(id);
    if (shipment.status !== 'draft') {
      throw new ConflictError(`shipment ${id} is already ${shipment.status}`);
    }
    const now = this.clock.isoNow();
    const event = this.buildEvent(id, 'label_printed', actor, now);
    const booked = await this.shipments.updateWithEvent(
      id,
      {},
      event,
      now,
    );
    await this.shipments.setStatus(id, 'booked', event, now);
    await this.webhooks.dispatch(event);
    return { ...(booked ?? shipment), status: 'booked', trackingNumber: trackingNumber() };
  }

  /**
   * Customer-initiated correction to a booked shipment. Writes the row and the
   * `corrected` event atomically and fans the event out to subscribers.
   */
  async applyCorrection(id: string, patch: ShipmentPatch, actor: string): Promise<Shipment> {
    const shipment = await this.requireById(id);
    if (!isEditable(shipment)) {
      throw new ConflictError(`shipment ${id} is ${shipment.status} and can no longer be edited`);
    }

    const now = this.clock.isoNow();
    const event = this.buildEvent(id, 'corrected', actor, now);
    const updated = await this.shipments.updateWithEvent(id, patch, event, now);
    if (!updated) {
      throw new NotFoundError(id);
    }
    await this.webhooks.dispatch(event);
    return updated;
  }

  async cancel(id: string, actor: string): Promise<Shipment> {
    const shipment = await this.requireById(id);
    if (shipment.status === 'delivered') {
      throw new ConflictError(`shipment ${id} has already been delivered`);
    }
    const now = this.clock.isoNow();
    const event = this.buildEvent(id, 'cancelled', actor, now);
    const cancelled = await this.shipments.setStatus(id, 'cancelled', event, now);
    await this.webhooks.dispatch(event);
    return cancelled ?? shipment;
  }

  async history(id: string): Promise<TrackingEvent[]> {
    await this.requireById(id);
    return this.events.forShipment(id);
  }

  private buildEvent(
    shipmentId: string,
    type: TrackingEvent['type'],
    actor: string,
    occurredAt: string,
  ): TrackingEvent {
    return { id: eventId(), shipmentId, type, occurredAt, actor };
  }

  private async emit(
    id: string,
    type: TrackingEvent['type'],
    actor: string,
    now: string,
  ): Promise<void> {
    const event = this.buildEvent(id, type, actor, now);
    await this.events.append(event);
    await this.webhooks.dispatch(event);
  }
}
