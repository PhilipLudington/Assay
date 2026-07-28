import { RouteNotFoundError } from './errors.js';
import type { HttpRequest, Method } from './request.js';
import type { HttpResponse } from './response.js';

export type Handler = (request: HttpRequest) => Promise<HttpResponse>;
export type Middleware = (next: Handler) => Handler;

interface Route {
  method: Method;
  segments: string[];
  handler: Handler;
}

/**
 * A pattern router with `:name` segments. Deliberately small: routes are
 * matched in registration order and the first match wins, so ordering is the
 * only precedence rule anyone has to remember.
 */
export class Router {
  private readonly routes: Route[] = [];

  add(method: Method, pattern: string, handler: Handler): this {
    this.routes.push({ method, segments: split(pattern), handler });
    return this;
  }

  get(pattern: string, handler: Handler): this {
    return this.add('GET', pattern, handler);
  }

  post(pattern: string, handler: Handler): this {
    return this.add('POST', pattern, handler);
  }

  patch(pattern: string, handler: Handler): this {
    return this.add('PATCH', pattern, handler);
  }

  delete(pattern: string, handler: Handler): this {
    return this.add('DELETE', pattern, handler);
  }

  async handle(request: HttpRequest): Promise<HttpResponse> {
    const actual = split(request.path);
    for (const route of this.routes) {
      if (route.method !== request.method || route.segments.length !== actual.length) {
        continue;
      }
      const params = match(route.segments, actual);
      if (params !== null) {
        return route.handler({ ...request, params });
      }
    }
    throw new RouteNotFoundError(request.method, request.path);
  }
}

export function applyMiddleware(handler: Handler, middleware: readonly Middleware[]): Handler {
  return middleware.reduceRight<Handler>((next, wrap) => wrap(next), handler);
}

function split(path: string): string[] {
  return path.split('/').filter((segment) => segment.length > 0);
}

function match(pattern: readonly string[], actual: readonly string[]): Record<string, string> | null {
  const params: Record<string, string> = {};
  for (let index = 0; index < pattern.length; index += 1) {
    const expected = pattern[index];
    const value = actual[index];
    if (expected === undefined || value === undefined) {
      return null;
    }
    if (expected.startsWith(':')) {
      params[expected.slice(1)] = value;
      continue;
    }
    if (expected !== value) {
      return null;
    }
  }
  return params;
}
