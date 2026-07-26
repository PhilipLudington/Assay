import type { CorsOptions } from '../middleware/cors.js';
import type { RateLimitOptions } from '../middleware/rate-limit.js';

export interface AppConfig {
  port: number;
  environment: 'development' | 'staging' | 'production';
  tokenSecret: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  cors: CorsOptions;
  rateLimit: RateLimitOptions;
  /** Base URL used when rendering customer-facing tracking links. */
  publicBaseUrl: string;
}

export class ConfigError extends Error {
  constructor(variable: string, detail: string) {
    super(`configuration error: ${variable} ${detail}`);
    this.name = 'ConfigError';
  }
}
