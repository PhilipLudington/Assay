import type { IncomingMessage } from 'node:http';
import type { Principal } from '../auth/principal.js';

export interface ApiRequest {
  raw: IncomingMessage;
  method: string;
  path: string;
  query: URLSearchParams;
  params: Record<string, string>;
  headers: Record<string, string>;
  /** Populated by the auth middleware. Absent on public routes. */
  principal?: Principal;
  /** Populated by the body parser. */
  body?: unknown;
  requestId: string;
}

export function headerOf(request: ApiRequest, name: string): string | undefined {
  return request.headers[name.toLowerCase()];
}

export function requirePrincipal(request: ApiRequest): Principal {
  if (!request.principal) {
    throw new Error('requirePrincipal called on a route without auth middleware');
  }
  return request.principal;
}

export function pathParam(request: ApiRequest, name: string): string {
  const value = request.params[name];
  if (value === undefined) {
    throw new Error(`route did not bind path parameter :${name}`);
  }
  return value;
}
