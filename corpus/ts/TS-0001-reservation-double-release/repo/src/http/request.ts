export type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE';

export interface HttpRequest {
  method: Method;
  path: string;
  params: Record<string, string>;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: unknown;
}

export function header(request: HttpRequest, name: string): string | undefined {
  return request.headers[name.toLowerCase()];
}

export function requireParam(request: HttpRequest, name: string): string {
  const value = request.params[name];
  if (value === undefined || value === '') {
    throw new Error(`route parameter ${name} is missing`);
  }
  return value;
}

export function numericQuery(request: HttpRequest, name: string, fallback: number): number {
  const raw = request.query[name];
  if (raw === undefined) {
    return fallback;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function bodyObject(request: HttpRequest): Record<string, unknown> {
  if (typeof request.body !== 'object' || request.body === null || Array.isArray(request.body)) {
    throw new Error('request body must be a JSON object');
  }
  return request.body as Record<string, unknown>;
}
