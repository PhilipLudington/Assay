import { InsufficientStockError } from '../domain/errors.js';
import type { ReservationLine } from '../domain/reservation.js';
import type { Warehouse, WarehouseId } from '../domain/warehouse.js';
import { acceptsNewReservations } from '../domain/warehouse.js';
import type { InventoryRepo } from '../repositories/inventory-repo.js';
import type { WarehouseRepo } from '../repositories/warehouse-repo.js';
import { availableUnits } from '../domain/inventory.js';
import { err, ok, type Result } from '../util/result.js';

export interface AllocationCandidate {
  warehouse: Warehouse;
  shortfall: number;
}

/**
 * Chooses which warehouse should serve an order.
 *
 * Preference order: same region first, then fewest missing units, then the
 * lowest warehouse code so the choice is stable across restarts.
 */
export class AllocationService {
  constructor(
    private readonly warehouses: WarehouseRepo,
    private readonly inventory: InventoryRepo,
  ) {}

  async chooseWarehouse(
    region: string,
    lines: readonly ReservationLine[],
  ): Promise<WarehouseId> {
    const candidates = await this.rank(region, lines);
    const best = candidates[0];
    if (best === undefined || best.shortfall > 0) {
      const missing = lines[0];
      throw new InsufficientStockError(
        missing === undefined ? 'unknown' : missing.sku,
        best === undefined ? 0 : best.shortfall,
        0,
      );
    }
    return best.warehouse.id;
  }

  /**
   * The same choice as `chooseWarehouse`, for callers that treat "nowhere can
   * serve this" as an answer rather than an exception.
   */
  async tryChooseWarehouse(
    region: string,
    lines: readonly ReservationLine[],
  ): Promise<Result<WarehouseId, string>> {
    const candidates = await this.rank(region, lines);
    const best = candidates[0];
    if (best === undefined) {
      return err('no warehouse is accepting reservations');
    }
    if (best.shortfall > 0) {
      return err(`best candidate ${best.warehouse.code} is short ${best.shortfall} units`);
    }
    return ok(best.warehouse.id);
  }

  async rank(region: string, lines: readonly ReservationLine[]): Promise<AllocationCandidate[]> {
    const warehouses = await this.warehouses.list();
    const open = warehouses.filter(acceptsNewReservations);

    const candidates: AllocationCandidate[] = [];
    for (const warehouse of open) {
      candidates.push({ warehouse, shortfall: await this.shortfall(warehouse.id, lines) });
    }

    return candidates.sort((left, right) => {
      const byRegion = Number(right.warehouse.region === region) - Number(left.warehouse.region === region);
      if (byRegion !== 0) {
        return byRegion;
      }
      if (left.shortfall !== right.shortfall) {
        return left.shortfall - right.shortfall;
      }
      return left.warehouse.code.localeCompare(right.warehouse.code);
    });
  }

  private async shortfall(
    warehouseId: WarehouseId,
    lines: readonly ReservationLine[],
  ): Promise<number> {
    let missing = 0;
    for (const line of lines) {
      const item = await this.inventory.find(warehouseId, line.sku);
      const available = item === null ? 0 : availableUnits(item);
      missing += Math.max(0, line.quantity - available);
    }
    return missing;
  }
}
