export interface QueueConfig {
  /** Maximum jobs executing at once. */
  concurrency: number;
  /** Per-attempt wall clock budget. */
  jobTimeoutMs: number;
  /** Default attempts before a job is declared dead. */
  maxAttempts: number;
  /** How often the heartbeat sweeper runs. */
  heartbeatIntervalMs: number;
  /**
   * A running job whose heartbeat is older than this is treated as stalled
   * and requeued. Must comfortably exceed heartbeatIntervalMs.
   */
  stallTimeoutMs: number;
  /** Retain terminal records for this long before compaction drops them. */
  retentionMs: number;
}

export const DEFAULT_CONFIG: QueueConfig = {
  concurrency: 4,
  jobTimeoutMs: 30_000,
  maxAttempts: 5,
  heartbeatIntervalMs: 1_000,
  stallTimeoutMs: 15_000,
  retentionMs: 60 * 60 * 1000,
};

export function resolveConfig(partial: Partial<QueueConfig> = {}): QueueConfig {
  const config = { ...DEFAULT_CONFIG, ...partial };

  if (config.concurrency < 1) {
    throw new RangeError('concurrency must be at least 1');
  }
  if (config.stallTimeoutMs <= config.heartbeatIntervalMs) {
    throw new RangeError('stallTimeoutMs must exceed heartbeatIntervalMs');
  }
  if (config.maxAttempts < 1) {
    throw new RangeError('maxAttempts must be at least 1');
  }
  return config;
}
