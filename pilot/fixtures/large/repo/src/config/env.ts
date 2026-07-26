import { DEFAULTS, PRODUCTION_OVERRIDES } from './defaults.js';
import { ConfigError, type AppConfig } from './schema.js';

function readNumber(env: NodeJS.ProcessEnv, name: string, fallback: number): number {
  const raw = env[name];
  if (raw === undefined) {
    return fallback;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new ConfigError(name, 'must be a number');
  }
  return parsed;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const tokenSecret = env['TOKEN_SECRET'];
  if (!tokenSecret || tokenSecret.length < 32) {
    throw new ConfigError('TOKEN_SECRET', 'must be set and at least 32 characters');
  }

  const environment = (env['NODE_ENV'] ?? DEFAULTS.environment) as AppConfig['environment'];
  const base: AppConfig = {
    ...DEFAULTS,
    ...(environment === 'production' ? PRODUCTION_OVERRIDES : {}),
    tokenSecret,
    environment,
    port: readNumber(env, 'PORT', DEFAULTS.port),
    publicBaseUrl: env['PUBLIC_BASE_URL'] ?? DEFAULTS.publicBaseUrl,
  };

  const origins = env['CORS_ALLOWED_ORIGINS'];
  if (origins) {
    base.cors = { ...base.cors, allowedOrigins: origins.split(',').map((o) => o.trim()) };
  }

  return base;
}
