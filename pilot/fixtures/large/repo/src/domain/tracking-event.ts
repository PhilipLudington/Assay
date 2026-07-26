export type TrackingEventType =
  | 'created'
  | 'label_printed'
  | 'collected'
  | 'in_transit'
  | 'out_for_delivery'
  | 'delivered'
  | 'exception'
  | 'corrected'
  | 'cancelled';

export interface TrackingEvent {
  id: string;
  shipmentId: string;
  type: TrackingEventType;
  occurredAt: string;
  location?: string;
  note?: string;
  /** Who or what caused this event — a principal id, or 'carrier-webhook'. */
  actor: string;
}

/** Events that close a shipment out. Nothing may follow them. */
export const TERMINAL_EVENTS: readonly TrackingEventType[] = ['delivered', 'cancelled'];

export function isTerminal(event: TrackingEvent): boolean {
  return TERMINAL_EVENTS.includes(event.type);
}

export function sortByTime(events: TrackingEvent[]): TrackingEvent[] {
  return [...events].sort((a, b) => a.occurredAt.localeCompare(b.occurredAt));
}
