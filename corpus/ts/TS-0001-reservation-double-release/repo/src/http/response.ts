export interface HttpResponse {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

export function json(status: number, body: unknown): HttpResponse {
  return { status, headers: { 'content-type': 'application/json' }, body };
}

export function ok(body: unknown): HttpResponse {
  return json(200, body);
}

export function created(body: unknown): HttpResponse {
  return json(201, body);
}

export function accepted(body: unknown): HttpResponse {
  return json(202, body);
}

export function noContent(): HttpResponse {
  return { status: 204, headers: {}, body: null };
}

export function problem(status: number, code: string, message: string): HttpResponse {
  return json(status, { code, message });
}
