import type { Quantity } from './quantity.js';
import type { Sku } from './sku.js';
import type { WarehouseId } from './warehouse.js';

export type ReservationId = string & { readonly __brand: 'ReservationId' };

/**
 * `pending` — created, awaiting confirmation from the order service.
 * `confirmed` — the order is paid for and the picker will be given the lines.
 * `picked` — the units have physically left the shelf.
 * `released` — cancelled before picking.
 * `expired` — not confirmed inside the warehouse's TTL.
 */
export type ReservationStatus = 'pending' | 'confirmed' | 'picked' | 'released' | 'expired';

export interface ReservationLine {
  sku: Sku;
  quantity: Quantity;
}

export interface Reservation {
  id: ReservationId;
  warehouseId: WarehouseId;
  orderRef: string;
  status: ReservationStatus;
  lines: ReservationLine[];
  createdAt: number;
  expiresAt: number;
}

const TRANSITIONS: Record<ReservationStatus, readonly ReservationStatus[]> = {
  pending: ['confirmed', 'released', 'expired'],
  confirmed: ['picked', 'released'],
  picked: [],
  released: [],
  expired: [],
};

export function canTransition(from: ReservationStatus, to: ReservationStatus): boolean {
  return TRANSITIONS[from].includes(to);
}

export function isTerminal(status: ReservationStatus): boolean {
  return TRANSITIONS[status].length === 0;
}

/** A reservation is only eligible for expiry while it is still unconfirmed. */
export function isExpirable(reservation: Reservation, now: number): boolean {
  return reservation.status === 'pending' && reservation.expiresAt <= now;
}

export function totalUnits(reservation: Reservation): number {
  return reservation.lines.reduce<number>((total, line) => total + line.quantity, 0);
}
