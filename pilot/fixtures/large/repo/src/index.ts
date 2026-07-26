import { buildApp, VERSION } from './app.js';
import { loadConfig } from './config/env.js';
import { JsonLogger } from './util/logger.js';

function main(): void {
  const config = loadConfig();
  const logger = new JsonLogger(config.logLevel);
  const server = buildApp(config);

  server.listen(config.port, () => {
    logger.log('info', 'shipping-api listening', {
      port: config.port,
      environment: config.environment,
      version: VERSION,
    });
  });

  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.on(signal, () => {
      logger.log('info', 'shutting down', { signal });
      server.close(() => process.exit(0));
    });
  }
}

main();
