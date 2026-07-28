import { ValidationError } from '../domain/errors.js';
import { quantity } from '../domain/quantity.js';
import type { ReservationLine } from '../domain/reservation.js';
import { parseSku } from '../domain/sku.js';
import type { WarehouseId, WarehouseMode } from '../domain/warehouse.js';
import { bodyObject, requireParam } from '../http/request.js';
import { applyMiddleware, type Router } from '../http/router.js';
import { ok } from '../http/response.js';
import { requireInternalToken, requireOperator } from '../middleware/auth.js';
import type { WarehouseRepo } from '../repositories/warehouse-repo.js';
import type { AllocationService } from '../services/allocation-service.js';

function parseMode(raw: unknown): WarehouseMode {
  if (raw === 'active' || raw === 'draining' || raw === 'closed') {
    return raw;
  }
  throw new ValidationError('mode must be one of active, draining, closed');
}

function parseLines(raw: unknown): ReservationLine[] {
  if (!Array.isArray(raw)) {
    throw new ValidationError('lines must be an array');
  }
  return raw.map((entry) => {
    const line = entry as Record<string, unknown>;
    if (typeof line['sku'] !== 'string' || typeof line['quantity'] !== 'number') {
      throw new ValidationError('each line needs a sku and a numeric quantity');
    }
    return { sku: parseSku(line['sku']), quantity: quantity(line['quantity']) };
  });
}

/**
 * Control-plane routes. These sit outside the edge gateway, so they carry both
 * the shared-secret check and the operator role check themselves.
 */
export function registerInternalRoutes(
  router: Router,
  warehouses: WarehouseRepo,
  allocation: AllocationService,
  internalTokens: readonly string[],
): void {
  const guard = [requireInternalToken(internalTokens), requireOperator()];

  router.post(
    '/internal/warehouses/:warehouseId/mode',
    applyMiddleware(async (request) => {
      const body = bodyObject(request);
      const warehouse = await warehouses.setMode(
        requireParam(request, 'warehouseId') as WarehouseId,
        parseMode(body['mode']),
      );
      return ok(warehouse);
    }, guard),
  );

  router.post(
    '/internal/allocations/preview',
    applyMiddleware(async (request) => {
      const body = bodyObject(request);
      if (typeof body['region'] !== 'string') {
        throw new ValidationError('region is required');
      }
      const outcome = await allocation.tryChooseWarehouse(body['region'], parseLines(body['lines']));
      return ok(
        outcome.ok
          ? { allocatable: true, warehouseId: outcome.value }
          : { allocatable: false, reason: outcome.error },
      );
    }, guard),
  );
}
