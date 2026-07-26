import type { JobId } from './types.js';

export class JobError extends Error {
  readonly jobId: JobId;

  constructor(jobId: JobId, message: string) {
    super(message);
    this.name = 'JobError';
    this.jobId = jobId;
  }
}

export class UnknownJobError extends JobError {
  constructor(jobId: JobId) {
    super(jobId, `no job record for ${jobId}`);
    this.name = 'UnknownJobError';
  }
}

export class NoHandlerError extends JobError {
  constructor(jobId: JobId, name: string) {
    super(jobId, `no handler registered for job type "${name}"`);
    this.name = 'NoHandlerError';
  }
}

export class JobTimeoutError extends JobError {
  constructor(jobId: JobId, afterMs: number) {
    super(jobId, `job ${jobId} exceeded its ${afterMs}ms deadline`);
    this.name = 'JobTimeoutError';
  }
}

export class QueueClosedError extends Error {
  constructor() {
    super('queue is closed and will not accept new work');
    this.name = 'QueueClosedError';
  }
}

export function describeError(err: unknown): string {
  if (err instanceof Error) {
    return `${err.name}: ${err.message}`;
  }
  return String(err);
}
