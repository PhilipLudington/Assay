import { UnknownJobError } from '../errors.js';
import type { Job, JobId, JobRecord, JobStatus, QueueStats } from '../types.js';
import { invariant } from '../util/assert.js';
import { KeyedMutex } from '../util/lock.js';
import { StatusIndex } from './index-by-status.js';
import { canTransition, cloneRecord, isRunnable, toRecord } from './record.js';

/**
 * The single source of truth for job state. Every transition goes through
 * here so the status index and the records never disagree.
 *
 * Writes are awaited by callers; they are not instantaneous. A caller that
 * mutates its own bookkeeping around a store write must assume the store is
 * momentarily behind.
 */
export class MemoryStore {
  private readonly records = new Map<JobId, JobRecord>();
  private readonly index = new StatusIndex();
  private readonly locks = new KeyedMutex();

  async insert<P>(job: Job<P>): Promise<JobRecord<P>> {
    const record = toRecord(job);
    this.records.set(job.id, record as JobRecord);
    this.index.add('queued', job.id);
    return record;
  }

  get(id: JobId): JobRecord | undefined {
    const record = this.records.get(id);
    return record ? cloneRecord(record) : undefined;
  }

  require(id: JobId): JobRecord {
    const record = this.get(id);
    if (!record) {
      throw new UnknownJobError(id);
    }
    return record;
  }

  /** Ids currently in a given status. */
  ids(status: JobStatus): JobId[] {
    return this.index.ids(status);
  }

  runnable(now: number, limit: number): JobRecord[] {
    const out: JobRecord[] = [];
    for (const id of this.index.ids('queued')) {
      const record = this.records.get(id);
      if (record && isRunnable(record, now)) {
        out.push(cloneRecord(record));
        if (out.length >= limit) {
          break;
        }
      }
    }
    return out;
  }

  async markRunning(id: JobId, now: number): Promise<JobRecord> {
    return this.transition(id, 'running', (record) => {
      record.attempt += 1;
      record.startedAt = now;
      record.heartbeatAt = now;
    });
  }

  async heartbeat(id: JobId, now: number): Promise<void> {
    await this.locks.run(id, async () => {
      const record = this.records.get(id);
      if (record && record.status === 'running') {
        record.heartbeatAt = now;
      }
    });
  }

  async complete(id: JobId, now: number): Promise<JobRecord> {
    return this.transition(id, 'succeeded', (record) => {
      record.finishedAt = now;
    });
  }

  async fail(id: JobId, now: number, error: string): Promise<JobRecord> {
    return this.transition(id, 'failed', (record) => {
      record.finishedAt = now;
      record.lastError = error;
    });
  }

  async kill(id: JobId, now: number, reason: string): Promise<JobRecord> {
    return this.transition(id, 'dead', (record) => {
      record.finishedAt = now;
      record.lastError = reason;
    });
  }

  async requeue(id: JobId, availableAt: number, reason?: string): Promise<JobRecord> {
    return this.transition(id, 'queued', (record) => {
      record.availableAt = availableAt;
      delete record.startedAt;
      delete record.heartbeatAt;
      if (reason) {
        record.lastError = reason;
      }
    });
  }

  private async transition(
    id: JobId,
    to: JobStatus,
    mutate: (record: JobRecord) => void,
  ): Promise<JobRecord> {
    return this.locks.run(id, async () => {
      const record = this.records.get(id);
      if (!record) {
        throw new UnknownJobError(id);
      }
      invariant(
        canTransition(record.status, to),
        `cannot move ${id} from ${record.status} to ${to}`,
      );
      this.index.move(record.status, to, id);
      record.status = to;
      mutate(record);
      return cloneRecord(record);
    });
  }

  stats(): QueueStats {
    return {
      queued: this.index.count('queued'),
      running: this.index.count('running'),
      succeeded: this.index.count('succeeded'),
      failed: this.index.count('failed'),
      dead: this.index.count('dead'),
    };
  }

  compact(now: number, retentionMs: number): number {
    let removed = 0;
    for (const [id, record] of this.records) {
      const finished = record.finishedAt;
      if (finished !== undefined && now - finished > retentionMs) {
        this.index.remove(record.status, id);
        this.records.delete(id);
        this.locks.forget(id);
        removed += 1;
      }
    }
    return removed;
  }
}
