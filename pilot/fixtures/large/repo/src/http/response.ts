import type { ServerResponse } from 'node:http';
import { Status, type StatusCode } from './status.js';

export interface ApiResponse {
  raw: ServerResponse;
  sent: boolean;
}

export function json(response: ApiResponse, status: StatusCode, body: unknown): void {
  if (response.sent) {
    return;
  }
  const payload = JSON.stringify(body);
  response.raw.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
  });
  response.raw.end(payload);
  response.sent = true;
}

export function noContent(response: ApiResponse): void {
  if (response.sent) {
    return;
  }
  response.raw.writeHead(Status.NoContent);
  response.raw.end();
  response.sent = true;
}

export function problem(
  response: ApiResponse,
  status: StatusCode,
  code: string,
  message: string,
  details?: unknown,
): void {
  json(response, status, {
    error: { code, message, ...(details === undefined ? {} : { details }) },
  });
}
