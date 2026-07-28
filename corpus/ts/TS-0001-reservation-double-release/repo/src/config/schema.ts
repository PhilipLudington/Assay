export interface HttpConfig {
  port: number;
  requestTimeoutMs: number;
  maxBodyBytes: number;
}

export interface JobConfig {
  /** How often the job runs, in milliseconds. */
  intervalMs: number;
  /** Rows processed per tick. Keeps one tick's transaction footprint bounded. */
  batchSize: number;
}

export interface JobsConfig {
  reservationSweep: JobConfig;
  auditPrune: JobConfig & { retentionMs: number };
}

export interface StockroomConfig {
  serviceName: string;
  environment: 'development' | 'staging' | 'production';
  http: HttpConfig;
  jobs: JobsConfig;
  /** Tokens accepted on the internal control-plane routes. */
  internalTokens: readonly string[];
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

export function assertPositive(name: string, value: number): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new ConfigError(`${name} must be a positive number, got ${value}`);
  }
  return value;
}
