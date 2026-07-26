import type { QueueConfig } from '../config.js';
import type { MemoryStore } from '../store/memory-store.js';
import type { EventBus } from '../telemetry/events.js';
import type { JobId } from '../types.js';
import type { WorkerPool } from './pool.js';

/**
 * Finds jobs that the store still believes are running but which nothing is
 * actually working on, and puts them back on the queue.
 *
 * This relies on one invariant, which the pool is responsible for upholding:
 *
 *   A job id is present in `pool.activeIds()` for the *entire* time its store
 *   record is in the `running` status — it is added before the record moves
 *   to `running`, and removed only after the record has left it.
 *
 * Because this queue is in-process, that membership is authoritative: a
 * `running` record that no worker owns cannot be making progress, so there is
 * nothing to wait for and it is requeued immediately. Jobs that *are* owned
 * are only requeued once their heartbeat has gone quiet for `stallTimeoutMs`,
 * which catches a worker wedged inside a handler.
 */
export class HeartbeatSweeper {
  constructor(
    private readonly store: MemoryStore,
    private readonly pool: WorkerPool,
    private readonly bus: EventBus,
    private readonly config: QueueConfig,
  ) {}

  async sweep(now: number): Promise<number> {
    const owned = new Set<JobId>(this.pool.activeIds());
    let requeued = 0;

    for (const id of this.store.ids('running')) {
      const record = this.store.get(id);
      if (!record) {
        continue;
      }

      if (owned.has(id)) {
        const last = record.heartbeatAt ?? record.startedAt ?? now;
        if (now - last <= this.config.stallTimeoutMs) {
          await this.store.heartbeat(id, now);
          continue;
        }
        await this.requeue(id, now, record.heartbeatAt, 'worker stopped reporting');
        requeued += 1;
        continue;
      }

      await this.requeue(id, now, record.heartbeatAt, 'no worker owns this job');
      requeued += 1;
    }

    return requeued;
  }

  private async requeue(
    id: JobId,
    now: number,
    lastHeartbeatAt: number | undefined,
    reason: string,
  ): Promise<void> {
    await this.store.requeue(id, now, `stalled: ${reason}`);
    this.bus.emit({ type: 'stalled', jobId: id, lastHeartbeatAt });
  }
}
