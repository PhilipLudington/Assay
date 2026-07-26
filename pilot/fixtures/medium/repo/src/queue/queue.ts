import { type QueueConfig, resolveConfig } from '../config.js';
import { NoHandlerError, QueueClosedError } from '../errors.js';
import { ExponentialRetryPolicy, type RetryPolicy } from '../retry/policy.js';
import { MemoryStore } from '../store/memory-store.js';
import { EventBus } from '../telemetry/events.js';
import { Metrics } from '../telemetry/metrics.js';
import { type Logger, nullLogger } from '../telemetry/logger.js';
import type { Handler, Job, JobId, JobRecord, QueueStats } from '../types.js';
import { type Clock, systemClock } from '../util/clock.js';
import { dedupeKeyFor, newJobId } from '../util/id.js';
import { DedupeRegistry } from './dedupe.js';
import { priorityValue, sortByPriority, type PriorityName } from './priority.js';
import { HeartbeatSweeper } from '../worker/heartbeat.js';
import { WorkerPool } from '../worker/pool.js';

export interface EnqueueOptions {
  priority?: number | PriorityName;
  maxAttempts?: number;
  delayMs?: number;
  dedupeKey?: string;
}

export class JobQueue {
  readonly config: QueueConfig;
  private readonly store = new MemoryStore();
  private readonly bus = new EventBus();
  private readonly metrics = new Metrics();
  private readonly dedupe = new DedupeRegistry();
  private readonly handlers = new Map<string, Handler<never>>();
  private readonly pool: WorkerPool;
  private readonly sweeper: HeartbeatSweeper;
  private closed = false;
  private ticking = false;

  constructor(
    partial: Partial<QueueConfig> = {},
    private readonly clock: Clock = systemClock,
    private readonly logger: Logger = nullLogger,
    retryPolicy: RetryPolicy = new ExponentialRetryPolicy(),
  ) {
    this.config = resolveConfig(partial);
    this.pool = new WorkerPool(this.store, this.bus, this.clock, this.config, retryPolicy);
    this.sweeper = new HeartbeatSweeper(this.store, this.pool, this.bus, this.config);
    this.bus.on((event) => this.metrics.observe(event));
  }

  register<P>(name: string, handler: Handler<P>): void {
    this.handlers.set(name, handler as Handler<never>);
    this.pool.register(name, handler as Handler<never>);
  }

  async enqueue<P>(name: string, payload: P, options: EnqueueOptions = {}): Promise<JobId> {
    if (this.closed) {
      throw new QueueClosedError();
    }
    if (!this.handlers.has(name)) {
      throw new NoHandlerError('<unassigned>', name);
    }

    const now = this.clock.now();
    const id = newJobId();
    const key = dedupeKeyFor(name, options.dedupeKey);
    if (key) {
      const existing = this.dedupe.claim(key, id);
      if (existing) {
        this.bus.emit({ type: 'deduped', jobId: id, existingId: existing });
        return existing;
      }
    }

    const job: Job<P> = {
      id,
      name,
      payload,
      priority: priorityValue(options.priority ?? 0),
      attempt: 0,
      maxAttempts: options.maxAttempts ?? this.config.maxAttempts,
      enqueuedAt: now,
      availableAt: now + (options.delayMs ?? 0),
      ...(options.dedupeKey === undefined ? {} : { dedupeKey: options.dedupeKey }),
    };
    await this.store.insert(job);
    this.bus.emit({ type: 'enqueued', jobId: id, name });
    return id;
  }

  /** Dispatch as much runnable work as the pool has room for. */
  async tick(): Promise<number> {
    if (this.ticking || this.closed) {
      return 0;
    }
    this.ticking = true;
    try {
      const now = this.clock.now();
      await this.sweeper.sweep(now);

      const room = this.pool.availableSlots();
      if (room <= 0) {
        return 0;
      }
      const candidates: JobRecord[] = sortByPriority(this.store.runnable(now, room));
      for (const record of candidates) {
        void this.pool.dispatch(record).then(() => {
          if (record.dedupeKey) {
            this.dedupe.releaseFor(record.id);
          }
        });
      }
      return candidates.length;
    } finally {
      this.ticking = false;
    }
  }

  async drain(): Promise<void> {
    while (this.store.stats().queued > 0 || this.pool.activeIds().length > 0) {
      await this.tick();
      await this.clock.sleep(this.config.heartbeatIntervalMs);
    }
  }

  async close(): Promise<void> {
    this.closed = true;
    await this.pool.settle();
    this.logger.log('info', 'queue closed', this.stats() as unknown as Record<string, unknown>);
  }

  stats(): QueueStats {
    return this.store.stats();
  }

  onEvent = this.bus.on.bind(this.bus);
  readMetrics = this.metrics.read.bind(this.metrics);
  inspect = (id: JobId): JobRecord | undefined => this.store.get(id);
}
