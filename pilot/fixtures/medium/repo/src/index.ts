export { JobQueue, type EnqueueOptions } from './queue/queue.js';
export { DedupeRegistry } from './queue/dedupe.js';
export { PRIORITY, priorityValue, sortByPriority, type PriorityName } from './queue/priority.js';

export { WorkerPool } from './worker/pool.js';
export { Worker } from './worker/worker.js';
export { HeartbeatSweeper } from './worker/heartbeat.js';

export { MemoryStore } from './store/memory-store.js';
export { StatusIndex } from './store/index-by-status.js';
export { isTerminal, isRunnable, canTransition } from './store/record.js';

export {
  ExponentialRetryPolicy,
  NonRetryableError,
  type RetryPolicy,
  type RetryDecision,
} from './retry/policy.js';
export { backoffFor, DEFAULT_BACKOFF, type BackoffOptions } from './retry/backoff.js';
export { applyJitter, type JitterMode } from './retry/jitter.js';

export { EventBus, type QueueEvent, type Listener } from './telemetry/events.js';
export { Metrics, type MetricsSnapshot } from './telemetry/metrics.js';
export { ConsoleLogger, NullLogger, nullLogger, type Logger, type LogLevel } from './telemetry/logger.js';

export { DEFAULT_CONFIG, resolveConfig, type QueueConfig } from './config.js';
export * from './errors.js';
export * from './types.js';

export { SystemClock, ManualClock, systemClock, type Clock } from './util/clock.js';
export { Mutex, KeyedMutex } from './util/lock.js';
export { type Result, ok, err, attempt, unwrap } from './util/result.js';
