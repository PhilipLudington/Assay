import type { JobId, JobStatus } from '../types.js';

/**
 * Secondary index so the queue and the heartbeat sweeper can enumerate jobs
 * in a given status without scanning every record.
 */
export class StatusIndex {
  private readonly byStatus = new Map<JobStatus, Set<JobId>>();

  add(status: JobStatus, id: JobId): void {
    let bucket = this.byStatus.get(status);
    if (!bucket) {
      bucket = new Set();
      this.byStatus.set(status, bucket);
    }
    bucket.add(id);
  }

  move(from: JobStatus, to: JobStatus, id: JobId): void {
    this.byStatus.get(from)?.delete(id);
    this.add(to, id);
  }

  remove(status: JobStatus, id: JobId): void {
    this.byStatus.get(status)?.delete(id);
  }

  ids(status: JobStatus): JobId[] {
    return [...(this.byStatus.get(status) ?? [])];
  }

  count(status: JobStatus): number {
    return this.byStatus.get(status)?.size ?? 0;
  }
}
