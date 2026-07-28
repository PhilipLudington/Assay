import type { Db } from '../db/client.js';
import type { InventoryRow } from '../db/rows.js';
import { toInventoryItem } from '../db/rows.js';
import type { Tx } from '../db/tx.js';
import { InsufficientStockError, NotFoundError } from '../domain/errors.js';
import type { InventoryItem } from '../domain/inventory.js';
import { availableUnits } from '../domain/inventory.js';
import type { Sku } from '../domain/sku.js';
import type { WarehouseId } from '../domain/warehouse.js';
import type { Clock } from '../util/clock.js';
import { BaseRepo } from './base-repo.js';

/**
 * The stock ledger.
 *
 * The ledger counts units, not promises: a row knows that twelve units are
 * held, and nothing more. Which reservation holds them is the reservations
 * table's business, and that asymmetry is what the `release` contract below is
 * about.
 */
export class InventoryRepo extends BaseRepo {
  constructor(
    db: Db,
    private readonly clock: Clock,
  ) {
    super(db);
  }

  async find(warehouseId: WarehouseId, sku: Sku): Promise<InventoryItem | null> {
    const row = this.rowIn(this.db.read().inventory, warehouseId, sku);
    return row === undefined ? null : toInventoryItem(row);
  }

  async listForWarehouse(warehouseId: WarehouseId): Promise<InventoryItem[]> {
    return this.db
      .read()
      .inventory.filter((row) => row.warehouse_id === warehouseId)
      .map(toInventoryItem);
  }

  /**
   * Promises `units` of a sku to a reservation, failing if they are not there.
   */
  async holdWithin(tx: Tx, warehouseId: WarehouseId, sku: Sku, units: number): Promise<void> {
    const row = this.requireRowIn(tx.tables.inventory, warehouseId, sku);
    const item = toInventoryItem(row);
    if (availableUnits(item) < units) {
      throw new InsufficientStockError(sku, units, availableUnits(item));
    }
    row.held += units;
    row.updated_at = this.clock.now();
  }

  /**
   * Returns `units` of held stock to the available pool.
   *
   * The ledger records how many units are held, never *which* reservation is
   * holding them, so this method cannot distinguish a second release of the
   * same units from a first: both are a subtraction it will happily perform.
   * Exactly one release per hold is therefore the caller's obligation. A
   * second one does not fail — it quietly overstates availability, and the row
   * oversells the next time someone asks for stock that is not there.
   */
  async releaseWithin(tx: Tx, warehouseId: WarehouseId, sku: Sku, units: number): Promise<void> {
    const row = this.requireRowIn(tx.tables.inventory, warehouseId, sku);
    row.held -= units;
    row.updated_at = this.clock.now();
  }

  /** Picking: the units leave the shelf, so they leave both columns. */
  async consumeWithin(tx: Tx, warehouseId: WarehouseId, sku: Sku, units: number): Promise<void> {
    const row = this.requireRowIn(tx.tables.inventory, warehouseId, sku);
    row.on_hand -= units;
    row.held -= units;
    row.updated_at = this.clock.now();
  }

  async hold(warehouseId: WarehouseId, sku: Sku, units: number): Promise<void> {
    await this.inTransaction((tx) => this.holdWithin(tx, warehouseId, sku, units));
  }

  /** See `releaseWithin` for the contract this inherits. */
  async release(warehouseId: WarehouseId, sku: Sku, units: number): Promise<void> {
    await this.inTransaction((tx) => this.releaseWithin(tx, warehouseId, sku, units));
  }

  /** Goods-in and stock counts. Never touches `held`. */
  async adjustOnHand(warehouseId: WarehouseId, sku: Sku, delta: number): Promise<InventoryItem> {
    return this.inTransaction(async (tx) => {
      const row = this.requireRowIn(tx.tables.inventory, warehouseId, sku);
      row.on_hand += delta;
      row.updated_at = this.clock.now();
      return toInventoryItem(row);
    });
  }

  private rowIn(
    rows: readonly InventoryRow[],
    warehouseId: WarehouseId,
    sku: Sku,
  ): InventoryRow | undefined {
    return rows.find((row) => row.warehouse_id === warehouseId && row.sku === sku);
  }

  private requireRowIn(
    rows: readonly InventoryRow[],
    warehouseId: WarehouseId,
    sku: Sku,
  ): InventoryRow {
    const row = this.rowIn(rows, warehouseId, sku);
    if (row === undefined) {
      throw new NotFoundError('inventory row', `${warehouseId}/${sku}`);
    }
    return row;
  }
}
