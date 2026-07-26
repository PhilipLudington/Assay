import { Status, type StatusCode } from './status.js';

export class HttpError extends Error {
  readonly status: StatusCode;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: StatusCode, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.code = code;
    if (details !== undefined) {
      this.details = details;
    }
  }
}

export const badRequest = (message: string, details?: unknown) =>
  new HttpError(Status.BadRequest, 'bad_request', message, details);

export const unauthorized = (message = 'authentication required') =>
  new HttpError(Status.Unauthorized, 'unauthorized', message);

export const forbidden = (message = 'insufficient scope') =>
  new HttpError(Status.Forbidden, 'forbidden', message);

export const notFound = (message = 'not found') =>
  new HttpError(Status.NotFound, 'not_found', message);

export const conflict = (message: string) =>
  new HttpError(Status.Conflict, 'conflict', message);

export const unprocessable = (message: string, details?: unknown) =>
  new HttpError(Status.UnprocessableEntity, 'unprocessable_entity', message, details);
