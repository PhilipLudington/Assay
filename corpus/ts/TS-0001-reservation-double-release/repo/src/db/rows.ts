import type { InventoryItem } from '../domain/inventory.js';
import type { Quantity } from '../domain/quantity.js';
import type { Reservation, ReservationId, ReservationStatus } from '../domain/reservation.js';
import type { Sku } from '../domain/sku.js';
import type { WarehouseId } from '../domain/warehouse.js';

/**
 * Row shapes as the driver returns them: snake_case, no branded types, no
 * nesting. Mapping to the domain happens here and nowhere else.
 */

export interface InventoryRow {
  warehouse_id: string;
  sku: string;
  on_hand: number;
  held: number;
  updated_at: number;
}

export interface ReservationRow {
  id: string;
  warehouse_id: string;
  order_ref: string;
  status: string;
  lines: { sku: string; quantity: number }[];
  created_at: number;
  expires_at: number;
}

export interface WarehouseRow {
  id: string;
  code: string;
  region: string;
  mode: string;
  reservation_ttl_ms: number;
}

export interface AuditRow {
  id: string;
  subject: string;
  action: string;
  detail: string;
  recorded_at: number;
}

export function toInventoryItem(row: InventoryRow): InventoryItem {
  return {
    warehouseId: row.warehouse_id as WarehouseId,
    sku: row.sku as Sku,
    onHand: row.on_hand,
    held: row.held,
    updatedAt: row.updated_at,
  };
}

export function toReservation(row: ReservationRow): Reservation {
  return {
    id: row.id as ReservationId,
    warehouseId: row.warehouse_id as WarehouseId,
    orderRef: row.order_ref,
    status: row.status as ReservationStatus,
    lines: row.lines.map((line) => ({
      sku: line.sku as Sku,
      quantity: line.quantity as Quantity,
    })),
    createdAt: row.created_at,
    expiresAt: row.expires_at,
  };
}
