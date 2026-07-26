import type { Address } from './address.js';
import type { ServiceLevel } from './carrier.js';
import type { Money } from './money.js';
import type { Weight } from './weight.js';

export type ShipmentStatus =
  | 'draft'
  | 'booked'
  | 'in_transit'
  | 'delivered'
  | 'cancelled';

export interface Shipment {
  id: string;
  reference: string;
  status: ShipmentStatus;
  carrierId: string;
  serviceLevel: ServiceLevel;
  origin: Address;
  destination: Address;
  weight: Weight;
  declaredValue: Money;
  trackingNumber: string | null;
  createdAt: string;
  updatedAt: string;
  /** Free-form, customer-visible. Editable after booking. */
  note?: string;
}

/** Fields a correction is allowed to touch after a shipment is booked. */
export type ShipmentPatch = Partial<
  Pick<Shipment, 'reference' | 'note' | 'destination' | 'weight' | 'declaredValue'>
>;

const OPEN: readonly ShipmentStatus[] = ['draft', 'booked', 'in_transit'];

export function isOpen(shipment: Shipment): boolean {
  return OPEN.includes(shipment.status);
}

export function isEditable(shipment: Shipment): boolean {
  return shipment.status === 'draft' || shipment.status === 'booked';
}
