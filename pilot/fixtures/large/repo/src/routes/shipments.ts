import { requireScope } from '../auth/principal.js';
import { Scope } from '../auth/scopes.js';
import { notFound } from '../http/errors.js';
import { pathParam, requirePrincipal } from '../http/request.js';
import { json } from '../http/response.js';
import { Router } from '../http/router.js';
import { Status } from '../http/status.js';
import type { ShipmentRepo } from '../repositories/shipment-repo.js';
import type { ShipmentService } from '../services/shipment-service.js';
import type { TrackingService } from '../services/tracking-service.js';
import type { Clock } from '../util/clock.js';
import { paginate, parsePageRequest } from '../util/pagination.js';
import {
  validateShipmentCreate,
  validateShipmentPatch,
} from '../validation/shipment-validator.js';

export function shipmentRoutes(
  shipmentService: ShipmentService,
  shipmentRepo: ShipmentRepo,
  tracking: TrackingService,
  clock: Clock,
): Router {
  const router = new Router();

  router.get('/shipments', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.ShipmentsRead);
    const all = await shipmentRepo.findAll();
    const page = paginate(all, parsePageRequest(request.query), (shipment) => shipment.id);
    json(response, Status.Ok, page);
  });

  router.get('/shipments/:id', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.ShipmentsRead);
    const shipment = await shipmentService.requireById(pathParam(request, 'id'));
    json(response, Status.Ok, shipment);
  });

  router.get('/shipments/:id/history', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.ShipmentsRead);
    const events = await shipmentService.history(pathParam(request, 'id'));
    json(response, Status.Ok, { events });
  });

  router.get('/shipments/by-reference/:reference', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.ShipmentsRead);
    const shipment = await shipmentRepo.byReference(pathParam(request, 'reference'));
    if (!shipment) {
      throw notFound(`no shipment with reference ${pathParam(request, 'reference')}`);
    }
    json(response, Status.Ok, await tracking.viewFor(shipment));
  });

  router.post('/shipments', async (request, response) => {
    const principal = requirePrincipal(request);
    requireScope(principal, Scope.ShipmentsWrite);

    const input = validateShipmentCreate(request.body);
    const shipment = await shipmentService.create(
      {
        reference: input.reference,
        carrierId: input.carrierId,
        serviceLevel: input.serviceLevel,
        origin: input.origin!,
        destination: input.destination!,
        weight: input.weight,
        declaredValue: { amountMinor: 0, currency: 'GBP' },
      },
      principal.id,
    );
    json(response, Status.Created, shipment);
  });

  router.patch('/shipments/:id', async (request, response) => {
    const principal = requirePrincipal(request);
    requireScope(principal, Scope.ShipmentsWrite);

    const id = pathParam(request, 'id');
    const patch = validateShipmentPatch(request.body);

    const updated = await shipmentRepo.update(id, patch, clock.isoNow());
    if (!updated) {
      throw notFound(`shipment ${id} not found`);
    }
    json(response, Status.Ok, updated);
  });

  router.post('/shipments/:id/book', async (request, response) => {
    const principal = requirePrincipal(request);
    requireScope(principal, Scope.ShipmentsWrite);
    const shipment = await shipmentService.book(pathParam(request, 'id'), principal.id);
    json(response, Status.Ok, shipment);
  });

  router.delete('/shipments/:id', async (request, response) => {
    const principal = requirePrincipal(request);
    requireScope(principal, Scope.ShipmentsWrite);
    const shipment = await shipmentService.cancel(pathParam(request, 'id'), principal.id);
    json(response, Status.Ok, shipment);
  });

  return router;
}
