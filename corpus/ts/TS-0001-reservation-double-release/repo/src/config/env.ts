import { DEFAULT_CONFIG } from './defaults.js';
import { assertPositive, ConfigError, type StockroomConfig } from './schema.js';

export type EnvBag = Readonly<Record<string, string | undefined>>;

function optionalNumber(env: EnvBag, name: string, fallback: number): number {
  const raw = env[name];
  if (raw === undefined || raw === '') {
    return fallback;
  }
  const parsed = Number(raw);
  if (Number.isNaN(parsed)) {
    throw new ConfigError(`${name} must be numeric, got ${raw}`);
  }
  return assertPositive(name, parsed);
}

function environment(env: EnvBag): StockroomConfig['environment'] {
  const raw = env['STOCKROOM_ENV'] ?? DEFAULT_CONFIG.environment;
  if (raw === 'development' || raw === 'staging' || raw === 'production') {
    return raw;
  }
  throw new ConfigError(`unknown STOCKROOM_ENV: ${raw}`);
}

/**
 * Builds the runtime config from an environment bag. The bag is passed in
 * rather than read from the process so that the config can be built in a test
 * without mutating global state.
 */
export function loadConfig(env: EnvBag): StockroomConfig {
  const tokens = (env['STOCKROOM_INTERNAL_TOKENS'] ?? '')
    .split(',')
    .map((token) => token.trim())
    .filter((token) => token.length > 0);

  return {
    serviceName: env['STOCKROOM_SERVICE_NAME'] ?? DEFAULT_CONFIG.serviceName,
    environment: environment(env),
    http: {
      port: optionalNumber(env, 'PORT', DEFAULT_CONFIG.http.port),
      requestTimeoutMs: optionalNumber(
        env,
        'STOCKROOM_REQUEST_TIMEOUT_MS',
        DEFAULT_CONFIG.http.requestTimeoutMs,
      ),
      maxBodyBytes: optionalNumber(
        env,
        'STOCKROOM_MAX_BODY_BYTES',
        DEFAULT_CONFIG.http.maxBodyBytes,
      ),
    },
    jobs: {
      reservationSweep: {
        intervalMs: optionalNumber(
          env,
          'STOCKROOM_SWEEP_INTERVAL_MS',
          DEFAULT_CONFIG.jobs.reservationSweep.intervalMs,
        ),
        batchSize: optionalNumber(
          env,
          'STOCKROOM_SWEEP_BATCH_SIZE',
          DEFAULT_CONFIG.jobs.reservationSweep.batchSize,
        ),
      },
      auditPrune: {
        intervalMs: optionalNumber(
          env,
          'STOCKROOM_PRUNE_INTERVAL_MS',
          DEFAULT_CONFIG.jobs.auditPrune.intervalMs,
        ),
        batchSize: DEFAULT_CONFIG.jobs.auditPrune.batchSize,
        retentionMs: optionalNumber(
          env,
          'STOCKROOM_AUDIT_RETENTION_MS',
          DEFAULT_CONFIG.jobs.auditPrune.retentionMs,
        ),
      },
    },
    internalTokens: tokens,
  };
}
