import { requireScope } from '../auth/principal.js';
import { Scope } from '../auth/scopes.js';
import { badRequest } from '../http/errors.js';
import { pathParam, requirePrincipal } from '../http/request.js';
import { json } from '../http/response.js';
import { Router } from '../http/router.js';
import { Status } from '../http/status.js';
import type { CarrierService } from '../services/carrier-service.js';
import { isPlainObject } from '../validation/validators.js';

export function carrierRoutes(carriers: CarrierService): Router {
  const router = new Router();

  router.get('/carriers', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.CarriersRead);
    json(response, Status.Ok, { carriers: await carriers.list() });
  });

  router.get('/carriers/:id', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.CarriersRead);
    const carrier = await carriers.byId(pathParam(request, 'id'));
    json(response, Status.Ok, carrier);
  });

  router.patch('/carriers/:id', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.CarriersWrite);

    const body = request.body;
    if (!isPlainObject(body) || typeof body['active'] !== 'boolean') {
      throw badRequest('body must be { "active": boolean }');
    }

    const carrier = await carriers.setActive(pathParam(request, 'id'), body['active']);
    json(response, Status.Ok, carrier);
  });

  return router;
}
