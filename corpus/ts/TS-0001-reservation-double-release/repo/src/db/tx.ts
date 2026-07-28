import type { AuditRow, InventoryRow, ReservationRow, WarehouseRow } from './rows.js';

export interface Tables {
  warehouses: WarehouseRow[];
  inventory: InventoryRow[];
  reservations: ReservationRow[];
  audit: AuditRow[];
}

/**
 * A unit of work. Everything a repository touches goes through the `tables`
 * handle it is given, so that a repository method cannot accidentally write
 * outside the transaction it was called in.
 */
export interface Tx {
  readonly tables: Tables;
  /** Runs after the transaction commits. Never runs if it rolls back. */
  onCommit(fn: () => void): void;
}

export function emptyTables(): Tables {
  return { warehouses: [], inventory: [], reservations: [], audit: [] };
}

export function cloneTables(tables: Tables): Tables {
  return {
    warehouses: tables.warehouses.map((row) => ({ ...row })),
    inventory: tables.inventory.map((row) => ({ ...row })),
    reservations: tables.reservations.map((row) => ({
      ...row,
      lines: row.lines.map((line) => ({ ...line })),
    })),
    audit: tables.audit.map((row) => ({ ...row })),
  };
}
