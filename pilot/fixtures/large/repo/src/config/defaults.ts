import { DEFAULT_CORS } from '../middleware/cors.js';
import { DEFAULT_RATE_LIMIT } from '../middleware/rate-limit.js';
import type { AppConfig } from './schema.js';

export const DEFAULTS: Omit<AppConfig, 'tokenSecret'> = {
  port: 8080,
  environment: 'development',
  logLevel: 'info',
  cors: DEFAULT_CORS,
  rateLimit: DEFAULT_RATE_LIMIT,
  publicBaseUrl: 'http://localhost:8080',
};

export const PRODUCTION_OVERRIDES: Partial<AppConfig> = {
  logLevel: 'warn',
  rateLimit: { limit: 1200, windowMs: 60_000 },
};
