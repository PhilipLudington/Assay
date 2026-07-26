import { badRequest } from '../http/errors.js';
import { headerOf } from '../http/request.js';
import type { Middleware } from '../http/router.js';

const MAX_BODY_BYTES = 1_000_000;

export function bodyParserMiddleware(maxBytes = MAX_BODY_BYTES): Middleware {
  return async (request, _response, next) => {
    if (request.method === 'GET' || request.method === 'DELETE') {
      await next();
      return;
    }

    const chunks: Buffer[] = [];
    let received = 0;
    for await (const chunk of request.raw) {
      const buffer = chunk as Buffer;
      received += buffer.length;
      if (received > maxBytes) {
        throw badRequest(`request body exceeds ${maxBytes} bytes`);
      }
      chunks.push(buffer);
    }

    if (received === 0) {
      request.body = undefined;
      await next();
      return;
    }

    const contentType = headerOf(request, 'content-type') ?? '';
    if (!contentType.includes('application/json')) {
      throw badRequest('content-type must be application/json');
    }

    try {
      request.body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch {
      throw badRequest('request body is not valid JSON');
    }

    await next();
  };
}
