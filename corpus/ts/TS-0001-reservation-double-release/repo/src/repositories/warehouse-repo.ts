import type { Db } from '../db/client.js';
import type { WarehouseRow } from '../db/rows.js';
import { NotFoundError } from '../domain/errors.js';
import type { Warehouse, WarehouseId, WarehouseMode } from '../domain/warehouse.js';
import { BaseRepo } from './base-repo.js';

function toWarehouse(row: WarehouseRow): Warehouse {
  return {
    id: row.id as WarehouseId,
    code: row.code,
    region: row.region,
    mode: row.mode as WarehouseMode,
    reservationTtlMs: row.reservation_ttl_ms,
  };
}

export class WarehouseRepo extends BaseRepo {
  constructor(db: Db) {
    super(db);
  }

  async findById(id: WarehouseId): Promise<Warehouse | null> {
    const row = this.db.read().warehouses.find((candidate) => candidate.id === id);
    return row === undefined ? null : toWarehouse(row);
  }

  async require(id: WarehouseId): Promise<Warehouse> {
    const warehouse = await this.findById(id);
    if (warehouse === null) {
      throw new NotFoundError('warehouse', id);
    }
    return warehouse;
  }

  async list(): Promise<Warehouse[]> {
    return this.db.read().warehouses.map(toWarehouse);
  }

  async setMode(id: WarehouseId, mode: WarehouseMode): Promise<Warehouse> {
    return this.inTransaction(async (tx) => {
      const row = tx.tables.warehouses.find((candidate) => candidate.id === id);
      if (row === undefined) {
        throw new NotFoundError('warehouse', id);
      }
      row.mode = mode;
      return toWarehouse(row);
    });
  }
}
