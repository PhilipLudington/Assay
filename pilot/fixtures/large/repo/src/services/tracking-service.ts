import { trackingUrlFor } from '../domain/carrier.js';
import type { Shipment } from '../domain/shipment.js';
import type { TrackingEvent, TrackingEventType } from '../domain/tracking-event.js';
import type { EventRepo } from '../repositories/event-repo.js';
import type { ShipmentRepo } from '../repositories/shipment-repo.js';
import type { Clock } from '../util/clock.js';
import { eventId } from '../util/id.js';
import type { CarrierService } from './carrier-service.js';

export interface TrackingView {
  shipment: Shipment;
  events: TrackingEvent[];
  carrierUrl: string | null;
  lastKnownLocation: string | null;
}

export class TrackingService {
  constructor(
    private readonly shipments: ShipmentRepo,
    private readonly events: EventRepo,
    private readonly carriers: CarrierService,
    private readonly clock: Clock,
  ) {}

  async byTrackingNumber(trackingNumber: string): Promise<TrackingView | undefined> {
    const shipment = await this.shipments.byTrackingNumber(trackingNumber);
    if (!shipment) {
      return undefined;
    }
    return this.viewFor(shipment);
  }

  async viewFor(shipment: Shipment): Promise<TrackingView> {
    const events = await this.events.forShipment(shipment.id);
    const carrier = await this.carriers.byId(shipment.carrierId).catch(() => undefined);
    const located = [...events].reverse().find((event) => event.location !== undefined);
    return {
      shipment,
      events,
      carrierUrl:
        carrier && shipment.trackingNumber
          ? trackingUrlFor(carrier, shipment.trackingNumber)
          : null,
      lastKnownLocation: located?.location ?? null,
    };
  }

  /** Records an event reported by a carrier rather than by our own API. */
  async recordCarrierEvent(
    shipmentId: string,
    type: TrackingEventType,
    location: string | undefined,
  ): Promise<TrackingEvent> {
    const event: TrackingEvent = {
      id: eventId(),
      shipmentId,
      type,
      occurredAt: this.clock.isoNow(),
      actor: 'carrier-webhook',
      ...(location === undefined ? {} : { location }),
    };
    await this.events.append(event);
    return event;
  }
}
