import type { Job, JobRecord, JobStatus } from '../types.js';

export function toRecord<P>(job: Job<P>): JobRecord<P> {
  return { ...job, status: 'queued' };
}

export function isTerminal(record: JobRecord): boolean {
  return record.status === 'succeeded' || record.status === 'dead';
}

export function isRunnable(record: JobRecord, now: number): boolean {
  return record.status === 'queued' && record.availableAt <= now;
}

const ALLOWED: Record<JobStatus, readonly JobStatus[]> = {
  queued: ['running'],
  running: ['succeeded', 'failed', 'dead', 'queued'],
  failed: ['queued', 'dead'],
  succeeded: [],
  dead: [],
};

export function canTransition(from: JobStatus, to: JobStatus): boolean {
  return ALLOWED[from].includes(to);
}

export function cloneRecord<P>(record: JobRecord<P>): JobRecord<P> {
  return { ...record };
}
