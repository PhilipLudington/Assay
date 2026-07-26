import { requireScope } from '../auth/principal.js';
import { Scope } from '../auth/scopes.js';
import { badRequest, notFound } from '../http/errors.js';
import { requirePrincipal } from '../http/request.js';
import { json, noContent } from '../http/response.js';
import { Router } from '../http/router.js';
import { Status } from '../http/status.js';
import type { ShipmentRepo } from '../repositories/shipment-repo.js';
import type { TrackingService } from '../services/tracking-service.js';
import type { TrackingEventType } from '../domain/tracking-event.js';
import { isPlainObject, requireString } from '../validation/validators.js';
import { Collector } from '../validation/schema.js';

const CARRIER_EVENT_TYPES: readonly TrackingEventType[] = [
  'collected',
  'in_transit',
  'out_for_delivery',
  'delivered',
  'exception',
];

export function webhookRoutes(
  tracking: TrackingService,
  shipments: ShipmentRepo,
): Router {
  const router = new Router();

  router.post('/webhooks/carrier', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.WebhooksReceive);

    const body = request.body;
    if (!isPlainObject(body)) {
      throw badRequest('body must be an object');
    }

    const collector = new Collector();
    const trackingNumber = requireString(collector, body, 'trackingNumber');
    const type = requireString(collector, body, 'eventType');
    collector.throwIfAny();

    if (!CARRIER_EVENT_TYPES.includes(type as TrackingEventType)) {
      throw badRequest(`eventType must be one of ${CARRIER_EVENT_TYPES.join(', ')}`);
    }

    const shipment = await shipments.byTrackingNumber(trackingNumber as string);
    if (!shipment) {
      throw notFound(`no shipment with tracking number ${trackingNumber}`);
    }

    const event = await tracking.recordCarrierEvent(
      shipment.id,
      type as TrackingEventType,
      typeof body['location'] === 'string' ? body['location'] : undefined,
    );
    json(response, Status.Created, event);
  });

  router.delete('/webhooks/subscriptions/:id', async (request, response) => {
    requireScope(requirePrincipal(request), Scope.Admin);
    noContent(response);
  });

  return router;
}
