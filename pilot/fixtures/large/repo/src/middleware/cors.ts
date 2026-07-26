import { headerOf } from '../http/request.js';
import type { Middleware } from '../http/router.js';
import { Status } from '../http/status.js';

export interface CorsOptions {
  allowedOrigins: string[];
  allowedMethods: string[];
  maxAgeSeconds: number;
}

export const DEFAULT_CORS: CorsOptions = {
  allowedOrigins: [],
  allowedMethods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
  maxAgeSeconds: 600,
};

export function corsMiddleware(options: CorsOptions = DEFAULT_CORS): Middleware {
  return async (request, response, next) => {
    const origin = headerOf(request, 'origin');
    if (origin && options.allowedOrigins.includes(origin)) {
      response.raw.setHeader('access-control-allow-origin', origin);
      response.raw.setHeader('vary', 'Origin');
      response.raw.setHeader('access-control-allow-methods', options.allowedMethods.join(', '));
      response.raw.setHeader('access-control-allow-headers', 'authorization, content-type');
      response.raw.setHeader('access-control-max-age', String(options.maxAgeSeconds));
    }

    if (request.method === 'OPTIONS') {
      response.raw.writeHead(Status.NoContent);
      response.raw.end();
      response.sent = true;
      return;
    }

    await next();
  };
}
