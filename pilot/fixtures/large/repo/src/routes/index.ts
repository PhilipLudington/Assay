import type { Handler } from '../http/router.js';
import { Router } from '../http/router.js';
import { notFound } from '../http/errors.js';
import type { Clock } from '../util/clock.js';
import type { CarrierService } from '../services/carrier-service.js';
import type { ShipmentService } from '../services/shipment-service.js';
import type { TrackingService } from '../services/tracking-service.js';
import type { ShipmentRepo } from '../repositories/shipment-repo.js';
import { carrierRoutes } from './carriers.js';
import { healthRoutes } from './health.js';
import { shipmentRoutes } from './shipments.js';
import { webhookRoutes } from './webhooks.js';

export interface RouteDependencies {
  shipmentService: ShipmentService;
  shipmentRepo: ShipmentRepo;
  carrierService: CarrierService;
  trackingService: TrackingService;
  clock: Clock;
  version: string;
}

/**
 * Builds the terminal handler. Route groups are consulted in order; the first
 * one that matches wins.
 */
export function buildRoutes(deps: RouteDependencies): { routers: Router[]; terminal: Handler } {
  const routers = [
    healthRoutes(deps.clock, deps.version),
    shipmentRoutes(deps.shipmentService, deps.shipmentRepo, deps.trackingService, deps.clock),
    carrierRoutes(deps.carrierService),
    webhookRoutes(deps.trackingService, deps.shipmentRepo),
  ];

  const terminal: Handler = async (request, response) => {
    for (const router of routers) {
      const match = router.match(request.method, request.path);
      if (match) {
        request.params = match.params;
        await match.handler(request, response);
        return;
      }
    }
    throw notFound(`no route for ${request.method} ${request.path}`);
  };

  return { routers, terminal };
}

/** Paths served before authentication runs. */
export const PUBLIC_PATHS: readonly string[] = ['/health', '/health/ready'];
