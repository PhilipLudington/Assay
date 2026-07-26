import { ConfigError } from './errors.js';

export interface LimiterConfig {
  /** Maximum tokens a bucket may hold. Also the maximum burst size. */
  capacity: number;
  /** Tokens added per second of elapsed time. May be fractional. */
  refillPerSecond: number;
  /** Buckets idle for longer than this are evicted from the store. */
  idleEvictionMs: number;
  /** Hard cap on tracked clients, to bound memory. */
  maxTrackedClients: number;
}

export const DEFAULT_CONFIG: LimiterConfig = {
  capacity: 20,
  refillPerSecond: 5,
  idleEvictionMs: 10 * 60 * 1000,
  maxTrackedClients: 10_000,
};

export function resolveConfig(partial: Partial<LimiterConfig> = {}): LimiterConfig {
  const config = { ...DEFAULT_CONFIG, ...partial };
  validateConfig(config);
  return config;
}

export function validateConfig(config: LimiterConfig): void {
  if (!Number.isFinite(config.capacity) || config.capacity <= 0) {
    throw new ConfigError('capacity', 'must be a positive finite number');
  }
  if (!Number.isFinite(config.refillPerSecond) || config.refillPerSecond <= 0) {
    throw new ConfigError('refillPerSecond', 'must be a positive finite number');
  }
  if (config.idleEvictionMs <= 0) {
    throw new ConfigError('idleEvictionMs', 'must be positive');
  }
  if (config.maxTrackedClients <= 0) {
    throw new ConfigError('maxTrackedClients', 'must be positive');
  }
}
