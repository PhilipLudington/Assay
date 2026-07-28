import type { StockroomConfig } from './schema.js';

export const MINUTE_MS = 60_000;
export const HOUR_MS = 60 * MINUTE_MS;
export const DAY_MS = 24 * HOUR_MS;

/**
 * Defaults are the development profile. Production overrides arrive through
 * the environment; anything not overridden is what runs.
 */
export const DEFAULT_CONFIG: StockroomConfig = {
  serviceName: 'stockroom',
  environment: 'development',
  http: {
    port: 8080,
    requestTimeoutMs: 15_000,
    maxBodyBytes: 256 * 1024,
  },
  jobs: {
    reservationSweep: {
      intervalMs: MINUTE_MS,
      batchSize: 200,
    },
    auditPrune: {
      intervalMs: 6 * HOUR_MS,
      batchSize: 5_000,
      retentionMs: 90 * DAY_MS,
    },
  },
  internalTokens: [],
};
