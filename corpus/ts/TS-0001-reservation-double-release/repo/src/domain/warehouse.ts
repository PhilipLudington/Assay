export type WarehouseId = string & { readonly __brand: 'WarehouseId' };

export type WarehouseMode = 'active' | 'draining' | 'closed';

export interface Warehouse {
  id: WarehouseId;
  code: string;
  region: string;
  mode: WarehouseMode;
  /** Reservations in this warehouse expire after this many milliseconds. */
  reservationTtlMs: number;
}

export function warehouseId(raw: string): WarehouseId {
  if (raw.length === 0) {
    throw new Error('warehouse id must not be empty');
  }
  return raw as WarehouseId;
}

/** A draining warehouse still honours existing reservations but takes no new ones. */
export function acceptsNewReservations(warehouse: Warehouse): boolean {
  return warehouse.mode === 'active';
}

export function isPickable(warehouse: Warehouse): boolean {
  return warehouse.mode !== 'closed';
}
