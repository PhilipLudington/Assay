import {
  ConflictError,
  DomainError,
  InsufficientStockError,
  NotFoundError,
  ValidationError,
} from '../domain/errors.js';
import { problem, type HttpResponse } from './response.js';

export class UnauthorizedError extends Error {
  readonly code = 'unauthorized';

  constructor(message = 'missing or invalid credentials') {
    super(message);
    this.name = 'UnauthorizedError';
  }
}

export class RouteNotFoundError extends Error {
  readonly code = 'route_not_found';

  constructor(method: string, path: string) {
    super(`no route for ${method} ${path}`);
    this.name = 'RouteNotFoundError';
  }
}

/**
 * The single place where an exception becomes a status code. Anything not
 * recognised here is a bug in this service, so it becomes a 500 and is logged
 * with its stack rather than being described to the caller.
 */
export function statusFor(error: unknown): number {
  if (error instanceof UnauthorizedError) {
    return 401;
  }
  if (error instanceof RouteNotFoundError || error instanceof NotFoundError) {
    return 404;
  }
  if (error instanceof ValidationError) {
    return 422;
  }
  if (error instanceof InsufficientStockError || error instanceof ConflictError) {
    return 409;
  }
  return 500;
}

export function toResponse(error: unknown): HttpResponse {
  const status = statusFor(error);
  if (status === 500) {
    return problem(500, 'internal_error', 'the request could not be completed');
  }
  if (error instanceof DomainError) {
    return problem(status, error.code, error.message);
  }
  if (error instanceof UnauthorizedError || error instanceof RouteNotFoundError) {
    return problem(status, error.code, error.message);
  }
  return problem(status, 'error', 'the request could not be completed');
}
