import type { InventoryItem } from '../domain/inventory.js';
import { availableUnits, isLedgerConsistent } from '../domain/inventory.js';
import type { Sku } from '../domain/sku.js';
import type { WarehouseId } from '../domain/warehouse.js';
import type { AuditRepo } from '../repositories/audit-repo.js';
import type { InventoryRepo } from '../repositories/inventory-repo.js';
import type { WarehouseRepo } from '../repositories/warehouse-repo.js';

export interface AvailabilityLine {
  sku: Sku;
  onHand: number;
  held: number;
  available: number;
}

/**
 * Read paths over the ledger, plus the goods-in write path. Reservation
 * lifecycle stock movements are not here — those belong to the reservation
 * repository, which owns them alongside the status change.
 */
export class InventoryService {
  constructor(
    private readonly inventory: InventoryRepo,
    private readonly warehouses: WarehouseRepo,
    private readonly audit: AuditRepo,
  ) {}

  async availability(warehouseId: WarehouseId, sku: Sku): Promise<AvailabilityLine | null> {
    const item = await this.inventory.find(warehouseId, sku);
    return item === null ? null : this.toLine(item);
  }

  async availabilityForWarehouse(warehouseId: WarehouseId): Promise<AvailabilityLine[]> {
    await this.warehouses.require(warehouseId);
    const items = await this.inventory.listForWarehouse(warehouseId);
    return items.map((item) => this.toLine(item));
  }

  /** Goods-in, stock counts and write-offs. */
  async adjust(
    warehouseId: WarehouseId,
    sku: Sku,
    delta: number,
    reason: string,
  ): Promise<AvailabilityLine> {
    const item = await this.inventory.adjustOnHand(warehouseId, sku, delta);
    await this.audit.record(`${warehouseId}/${sku}`, 'inventory.adjusted', `${delta}: ${reason}`);
    return this.toLine(item);
  }

  /**
   * Rows whose held count has drifted outside what the ledger permits. The
   * reconciliation job pages on a non-empty result, because such a row will
   * oversell rather than fail.
   */
  async inconsistentRows(warehouseId: WarehouseId): Promise<InventoryItem[]> {
    const items = await this.inventory.listForWarehouse(warehouseId);
    return items.filter((item) => !isLedgerConsistent(item));
  }

  private toLine(item: InventoryItem): AvailabilityLine {
    return {
      sku: item.sku,
      onHand: item.onHand,
      held: item.held,
      available: availableUnits(item),
    };
  }
}
