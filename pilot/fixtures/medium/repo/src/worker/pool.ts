import type { QueueConfig } from '../config.js';
import { describeError } from '../errors.js';
import type { RetryPolicy } from '../retry/policy.js';
import type { MemoryStore } from '../store/memory-store.js';
import type { EventBus } from '../telemetry/events.js';
import type { Handler, JobId, JobRecord } from '../types.js';
import type { Clock } from '../util/clock.js';
import { newWorkerId } from '../util/id.js';
import { Worker } from './worker.js';

interface ActiveEntry {
  workerId: string;
  startedAt: number;
}

/**
 * Owns the set of jobs currently executing in this process and enforces the
 * concurrency limit. Membership of `active` is what the heartbeat sweeper
 * uses to tell a live job from an orphaned one.
 */
export class WorkerPool {
  private readonly active = new Map<JobId, ActiveEntry>();
  private readonly handlers = new Map<string, Handler<never>>();
  private readonly inflight = new Set<Promise<void>>();

  constructor(
    private readonly store: MemoryStore,
    private readonly bus: EventBus,
    private readonly clock: Clock,
    private readonly config: QueueConfig,
    private readonly retryPolicy: RetryPolicy,
  ) {}

  register(name: string, handler: Handler<never>): void {
    this.handlers.set(name, handler);
  }

  activeIds(): JobId[] {
    return [...this.active.keys()];
  }

  availableSlots(): number {
    return Math.max(0, this.config.concurrency - this.active.size);
  }

  async dispatch(record: JobRecord): Promise<void> {
    const worker = new Worker(newWorkerId(), this.handlers, this.config);
    const startedAt = this.clock.now();

    this.active.set(record.id, { workerId: worker.id, startedAt });
    const running = await this.store.markRunning(record.id, startedAt);
    this.bus.emit({
      type: 'started',
      jobId: record.id,
      attempt: running.attempt,
      workerId: worker.id,
    });

    const task = this.execute(worker, running, startedAt);
    this.inflight.add(task);
    try {
      await task;
    } finally {
      this.inflight.delete(task);
    }
  }

  private async execute(worker: Worker, record: JobRecord, startedAt: number): Promise<void> {
    try {
      await worker.run(record, startedAt);
      await this.finish(record.id, startedAt);
    } catch (error) {
      await this.recover(record, error);
    }
  }

  private async finish(jobId: JobId, startedAt: number): Promise<void> {
    this.active.delete(jobId);
    await this.store.complete(jobId, this.clock.now());
    this.bus.emit({
      type: 'succeeded',
      jobId,
      durationMs: this.clock.now() - startedAt,
    });
  }

  private async recover(record: JobRecord, error: unknown): Promise<void> {
    this.active.delete(record.id);
    const now = this.clock.now();
    const message = describeError(error);
    await this.store.fail(record.id, now, message);
    this.bus.emit({
      type: 'failed',
      jobId: record.id,
      attempt: record.attempt,
      error: message,
    });

    const decision = this.retryPolicy.decide(record, error, now);
    if (decision.action === 'retry') {
      await this.store.requeue(record.id, decision.availableAt);
      this.bus.emit({ type: 'retrying', jobId: record.id, delayMs: decision.delayMs });
    } else {
      await this.store.kill(record.id, now, decision.reason);
      this.bus.emit({ type: 'dead', jobId: record.id, reason: decision.reason });
    }
  }

  /** Waits for everything currently executing to reach a terminal state. */
  async settle(): Promise<void> {
    while (this.inflight.size > 0) {
      await Promise.allSettled([...this.inflight]);
    }
  }
}
