import { ValidationError } from '../domain/errors.js';
import { quantity } from '../domain/quantity.js';
import type { ReservationId, ReservationLine } from '../domain/reservation.js';
import { parseSku } from '../domain/sku.js';
import type { WarehouseId } from '../domain/warehouse.js';
import { bodyObject, requireParam } from '../http/request.js';
import type { Router } from '../http/router.js';
import { created, noContent, ok } from '../http/response.js';
import type { ReservationService } from '../services/reservation-service.js';

function parseLines(raw: unknown): ReservationLine[] {
  if (!Array.isArray(raw)) {
    throw new ValidationError('lines must be an array');
  }
  return raw.map((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new ValidationError('each line must be an object');
    }
    const line = entry as Record<string, unknown>;
    if (typeof line['sku'] !== 'string' || typeof line['quantity'] !== 'number') {
      throw new ValidationError('each line needs a sku and a numeric quantity');
    }
    return { sku: parseSku(line['sku']), quantity: quantity(line['quantity']) };
  });
}

export function registerReservationRoutes(router: Router, reservations: ReservationService): void {
  router.post('/reservations', async (request) => {
    const body = bodyObject(request);
    if (typeof body['warehouseId'] !== 'string' || typeof body['orderRef'] !== 'string') {
      throw new ValidationError('warehouseId and orderRef are required');
    }
    const reservation = await reservations.create(
      body['warehouseId'] as WarehouseId,
      body['orderRef'],
      parseLines(body['lines']),
    );
    return created(reservation);
  });

  router.get('/reservations/:id', async (request) =>
    ok(await reservations.get(requireParam(request, 'id') as ReservationId)),
  );

  router.post('/reservations/:id/confirm', async (request) =>
    ok(await reservations.confirm(requireParam(request, 'id') as ReservationId)),
  );

  router.post('/reservations/:id/pick', async (request) =>
    ok(await reservations.pick(requireParam(request, 'id') as ReservationId)),
  );

  router.delete('/reservations/:id', async (request) => {
    const body = typeof request.body === 'object' && request.body !== null ? bodyObject(request) : {};
    const reason = typeof body['reason'] === 'string' ? body['reason'] : 'cancelled by caller';
    await reservations.cancel(requireParam(request, 'id') as ReservationId, reason);
    return noContent();
  });

  router.get('/orders/:orderRef/reservations', async (request) =>
    ok(await reservations.forOrder(requireParam(request, 'orderRef'))),
  );
}
