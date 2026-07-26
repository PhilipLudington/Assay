import type { QueueConfig } from '../config.js';
import { NoHandlerError } from '../errors.js';
import type { Handler, JobContext, JobRecord } from '../types.js';
import { startDeadline, withDeadline } from '../util/deadline.js';

/**
 * Runs exactly one attempt of one job. Stateless — the pool owns lifecycle,
 * the store owns status, this owns nothing.
 */
export class Worker {
  constructor(
    readonly id: string,
    private readonly handlers: Map<string, Handler<never>>,
    private readonly config: QueueConfig,
  ) {}

  async run(record: JobRecord, now: number): Promise<void> {
    const handler = this.handlers.get(record.name);
    if (!handler) {
      throw new NoHandlerError(record.id, record.name);
    }

    const deadline = startDeadline(now, this.config.jobTimeoutMs);
    const ctx: JobContext = {
      jobId: record.id,
      attempt: record.attempt,
      deadlineAt: deadline.at,
      signal: deadline.signal,
    };

    await withDeadline(
      record.id,
      this.config.jobTimeoutMs,
      deadline,
      (handler as Handler<unknown>)(record.payload, ctx),
    );
  }
}
