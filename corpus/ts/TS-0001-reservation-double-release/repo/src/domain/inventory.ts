import type { Sku } from './sku.js';
import type { WarehouseId } from './warehouse.js';

/**
 * One row of the stock ledger: how many units of a sku physically sit in a
 * warehouse, and how many of those are already promised to someone.
 *
 * Availability is *derived*, never stored. Storing it would give two writers
 * two ways to disagree.
 */
export interface InventoryItem {
  warehouseId: WarehouseId;
  sku: Sku;
  /** Units physically present, including units that are held. */
  onHand: number;
  /** Units promised to reservations that have not yet been picked. */
  held: number;
  updatedAt: number;
}

export function availableUnits(item: InventoryItem): number {
  return item.onHand - item.held;
}

export function canSatisfy(item: InventoryItem, units: number): boolean {
  return availableUnits(item) >= units;
}

/**
 * The ledger is consistent when nothing is promised twice and nothing is
 * promised that is not there. The reconciliation job reports rows that fail
 * this, because a row that fails it will eventually oversell.
 */
export function isLedgerConsistent(item: InventoryItem): boolean {
  return item.held >= 0 && item.held <= item.onHand;
}
