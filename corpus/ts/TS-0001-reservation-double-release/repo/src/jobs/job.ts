import { describeError, type Logger } from '../util/logger.js';
import type { Metrics } from '../util/metrics.js';
import type { Clock } from '../util/clock.js';

export interface JobRunSummary {
  /** Rows the job successfully dealt with. */
  processed: number;
  /** Rows it tried and could not. */
  failed: number;
}

export interface Job {
  readonly name: string;
  readonly intervalMs: number;
  runOnce(): Promise<JobRunSummary>;
}

export const EMPTY_SUMMARY: JobRunSummary = { processed: 0, failed: 0 };

/**
 * Runs jobs on their own cadence.
 *
 * A tick that throws is logged and the job stays scheduled: background work is
 * retried by definition, and a job that unscheduled itself on the first bad
 * row would go quiet exactly when it is most needed.
 */
export class JobRunner {
  private readonly lastRunAt = new Map<string, number>();

  constructor(
    private readonly jobs: readonly Job[],
    private readonly clock: Clock,
    private readonly logger: Logger,
    private readonly metrics: Metrics,
  ) {}

  async tick(): Promise<void> {
    const now = this.clock.now();
    for (const job of this.jobs) {
      const last = this.lastRunAt.get(job.name) ?? 0;
      if (now - last < job.intervalMs) {
        continue;
      }
      this.lastRunAt.set(job.name, now);
      await this.run(job);
    }
  }

  private async run(job: Job): Promise<void> {
    try {
      const summary = await job.runOnce();
      this.metrics.increment(`job.${job.name}.processed`, summary.processed);
      this.metrics.increment(`job.${job.name}.failed`, summary.failed);
      this.logger.log('info', 'job.completed', { job: job.name, ...summary });
    } catch (error) {
      this.metrics.increment(`job.${job.name}.crashed`);
      this.logger.log('error', 'job.crashed', { job: job.name, ...describeError(error) });
    }
  }
}
