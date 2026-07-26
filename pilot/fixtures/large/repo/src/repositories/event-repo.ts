import type { TrackingEvent } from '../domain/tracking-event.js';
import { sortByTime } from '../domain/tracking-event.js';
import { BaseRepo } from './base-repo.js';

export class EventRepo extends BaseRepo<TrackingEvent> {
  async append(event: TrackingEvent): Promise<TrackingEvent> {
    return this.insert(event);
  }

  async forShipment(shipmentId: string): Promise<TrackingEvent[]> {
    const all = await this.findAll();
    return sortByTime(all.filter((event) => event.shipmentId === shipmentId));
  }

  async latestForShipment(shipmentId: string): Promise<TrackingEvent | undefined> {
    const events = await this.forShipment(shipmentId);
    return events[events.length - 1];
  }

  async countForShipment(shipmentId: string): Promise<number> {
    return (await this.forShipment(shipmentId)).length;
  }
}
