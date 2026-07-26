import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AppConfig } from './config/schema.js';
import type { ApiRequest } from './http/request.js';
import type { ApiResponse } from './http/response.js';
import { Router } from './http/router.js';
import { authMiddleware } from './middleware/auth.js';
import { bodyParserMiddleware } from './middleware/body-parser.js';
import { corsMiddleware } from './middleware/cors.js';
import { errorHandlerMiddleware } from './middleware/error-handler.js';
import { rateLimitMiddleware } from './middleware/rate-limit.js';
import { requestIdMiddleware } from './middleware/request-id.js';
import { CarrierRepo } from './repositories/carrier-repo.js';
import { EventRepo } from './repositories/event-repo.js';
import { ShipmentRepo } from './repositories/shipment-repo.js';
import { buildRoutes, PUBLIC_PATHS } from './routes/index.js';
import { CarrierService } from './services/carrier-service.js';
import { ShipmentService } from './services/shipment-service.js';
import { TrackingService } from './services/tracking-service.js';
import { WebhookService } from './services/webhook-service.js';
import { systemClock, type Clock } from './util/clock.js';
import { JsonLogger, type Logger } from './util/logger.js';

export const VERSION = '2.7.1';

export function buildApp(config: AppConfig, clock: Clock = systemClock): Server {
  const logger: Logger = new JsonLogger(config.logLevel);

  const eventRepo = new EventRepo();
  const shipmentRepo = new ShipmentRepo(eventRepo);
  const carrierRepo = new CarrierRepo();

  const webhookService = new WebhookService(logger);
  const carrierService = new CarrierService(carrierRepo);
  const shipmentService = new ShipmentService(shipmentRepo, eventRepo, webhookService, clock);
  const trackingService = new TrackingService(shipmentRepo, eventRepo, carrierService, clock);

  const { terminal } = buildRoutes({
    shipmentService,
    shipmentRepo,
    carrierService,
    trackingService,
    clock,
    version: VERSION,
  });

  const pipeline = new Router()
    .use(errorHandlerMiddleware(logger))
    .use(requestIdMiddleware())
    .use(corsMiddleware(config.cors))
    .use(async (request, response, next) => {
      if (PUBLIC_PATHS.includes(request.path)) {
        await next();
        return;
      }
      await authMiddleware(config.tokenSecret, clock)(request, response, next);
    })
    .use(rateLimitMiddleware(clock, config.rateLimit))
    .use(bodyParserMiddleware());

  return createServer((raw: IncomingMessage, rawResponse: ServerResponse) => {
    const url = new URL(raw.url ?? '/', config.publicBaseUrl);
    const request: ApiRequest = {
      raw,
      method: raw.method ?? 'GET',
      path: url.pathname,
      query: url.searchParams,
      params: {},
      headers: raw.headers as Record<string, string>,
      requestId: '',
    };
    const response: ApiResponse = { raw: rawResponse, sent: false };

    void pipeline.dispatch(request, response, terminal);
  });
}
