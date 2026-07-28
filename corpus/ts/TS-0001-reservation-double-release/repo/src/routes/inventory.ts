import { NotFoundError, ValidationError } from '../domain/errors.js';
import { parseSku } from '../domain/sku.js';
import type { WarehouseId } from '../domain/warehouse.js';
import { bodyObject, requireParam } from '../http/request.js';
import type { Router } from '../http/router.js';
import { ok } from '../http/response.js';
import type { InventoryRepo } from '../repositories/inventory-repo.js';
import type { InventoryService } from '../services/inventory-service.js';

export function registerInventoryRoutes(
  router: Router,
  inventoryService: InventoryService,
  inventoryRepo: InventoryRepo,
): void {
  router.get('/warehouses/:warehouseId/inventory', async (request) =>
    ok(
      await inventoryService.availabilityForWarehouse(
        requireParam(request, 'warehouseId') as WarehouseId,
      ),
    ),
  );

  router.get('/warehouses/:warehouseId/inventory/:sku', async (request) => {
    const line = await inventoryService.availability(
      requireParam(request, 'warehouseId') as WarehouseId,
      parseSku(requireParam(request, 'sku')),
    );
    if (line === null) {
      throw new NotFoundError('inventory row', requireParam(request, 'sku'));
    }
    return ok(line);
  });

  router.post('/warehouses/:warehouseId/inventory/:sku/adjust', async (request) => {
    const body = bodyObject(request);
    if (typeof body['delta'] !== 'number' || typeof body['reason'] !== 'string') {
      throw new ValidationError('delta (number) and reason (string) are required');
    }
    return ok(
      await inventoryService.adjust(
        requireParam(request, 'warehouseId') as WarehouseId,
        parseSku(requireParam(request, 'sku')),
        body['delta'],
        body['reason'],
      ),
    );
  });

  /**
   * Operator escape hatch: releases stock that the ledger believes is held but
   * which support has confirmed is not. Used when an integration crashed
   * mid-reservation and left a hold with no owning row.
   */
  router.post('/warehouses/:warehouseId/inventory/:sku/force-release', async (request) => {
    const body = bodyObject(request);
    if (typeof body['units'] !== 'number') {
      throw new ValidationError('units (number) is required');
    }
    const warehouseId = requireParam(request, 'warehouseId') as WarehouseId;
    const sku = parseSku(requireParam(request, 'sku'));
    await inventoryRepo.release(warehouseId, sku, body['units']);
    return ok(await inventoryService.availability(warehouseId, sku));
  });

  router.get('/warehouses/:warehouseId/inventory-consistency', async (request) =>
    ok(
      await inventoryService.inconsistentRows(
        requireParam(request, 'warehouseId') as WarehouseId,
      ),
    ),
  );
}
