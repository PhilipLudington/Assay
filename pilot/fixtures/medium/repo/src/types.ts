export type JobId = string;

export type JobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'dead';

/** Terminal statuses never transition again. */
export const TERMINAL_STATUSES: readonly JobStatus[] = ['succeeded', 'dead'];

export interface Job<P = unknown> {
  id: JobId;
  name: string;
  payload: P;
  priority: number;
  attempt: number;
  maxAttempts: number;
  enqueuedAt: number;
  /** Earliest time this job may be picked up. Backoff pushes this forward. */
  availableAt: number;
  dedupeKey?: string;
}

export interface JobRecord<P = unknown> extends Job<P> {
  status: JobStatus;
  startedAt?: number;
  finishedAt?: number;
  /** Set whenever the worker that owned this job last reported liveness. */
  heartbeatAt?: number;
  lastError?: string;
}

export interface JobContext {
  jobId: JobId;
  attempt: number;
  deadlineAt: number;
  signal: AbortSignal;
}

export type Handler<P = unknown> = (payload: P, ctx: JobContext) => Promise<void>;

export interface QueueStats {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  dead: number;
}
