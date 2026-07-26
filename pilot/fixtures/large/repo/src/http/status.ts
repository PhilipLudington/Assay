export const Status = {
  Ok: 200,
  Created: 201,
  NoContent: 204,
  BadRequest: 400,
  Unauthorized: 401,
  Forbidden: 403,
  NotFound: 404,
  Conflict: 409,
  UnprocessableEntity: 422,
  TooManyRequests: 429,
  InternalServerError: 500,
  BadGateway: 502,
} as const;

export type StatusCode = (typeof Status)[keyof typeof Status];

export function isClientError(code: number): boolean {
  return code >= 400 && code < 500;
}

export function isServerError(code: number): boolean {
  return code >= 500;
}
