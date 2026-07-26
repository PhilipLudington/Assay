import type { ClientId, Millis } from './types.js';

export class RateLimitError extends Error {
  readonly clientId: ClientId;
  readonly retryAfterMs: Millis;

  constructor(clientId: ClientId, retryAfterMs: Millis) {
    super(`rate limit exceeded for ${clientId}; retry in ${retryAfterMs}ms`);
    this.name = 'RateLimitError';
    this.clientId = clientId;
    this.retryAfterMs = retryAfterMs;
  }
}

export class ConfigError extends Error {
  constructor(field: string, detail: string) {
    super(`invalid limiter config: ${field} ${detail}`);
    this.name = 'ConfigError';
  }
}

export function isRateLimitError(err: unknown): err is RateLimitError {
  return err instanceof RateLimitError;
}
