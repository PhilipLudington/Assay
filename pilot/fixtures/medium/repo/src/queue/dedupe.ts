import type { JobId } from '../types.js';

/**
 * Collapses repeat enqueues while an equivalent job is still pending. The
 * mapping is released as soon as the job reaches a terminal status, so the
 * same key can be scheduled again afterwards.
 */
export class DedupeRegistry {
  private readonly pending = new Map<string, JobId>();

  claim(key: string, jobId: JobId): JobId | undefined {
    const existing = this.pending.get(key);
    if (existing !== undefined) {
      return existing;
    }
    this.pending.set(key, jobId);
    return undefined;
  }

  release(key: string): void {
    this.pending.delete(key);
  }

  releaseFor(jobId: JobId): void {
    for (const [key, id] of this.pending) {
      if (id === jobId) {
        this.pending.delete(key);
        return;
      }
    }
  }

  size(): number {
    return this.pending.size;
  }
}
