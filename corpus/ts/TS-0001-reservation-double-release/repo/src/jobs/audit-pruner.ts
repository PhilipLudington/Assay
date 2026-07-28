import type { AuditRepo } from '../repositories/audit-repo.js';
import type { Clock } from '../util/clock.js';
import type { Logger } from '../util/logger.js';
import type { Metrics } from '../util/metrics.js';
import type { Job, JobRunSummary } from './job.js';

/**
 * Drops audit rows past the retention window.
 *
 * The audit trail is advisory — nothing reads it to make a decision — so rows
 * are deleted outright rather than archived.
 */
export class AuditPruner implements Job {
  readonly name = 'audit-prune';

  constructor(
    private readonly audit: AuditRepo,
    private readonly clock: Clock,
    private readonly logger: Logger,
    private readonly metrics: Metrics,
    private readonly config: { intervalMs: number; retentionMs: number },
  ) {}

  get intervalMs(): number {
    return this.config.intervalMs;
  }

  async runOnce(): Promise<JobRunSummary> {
    const cutoff = this.clock.now() - this.config.retentionMs;
    const removed = await this.audit.deleteOlderThan(cutoff);
    this.metrics.increment('audit.pruned', removed);
    this.logger.log('info', 'audit.pruned', { removed, cutoff });
    return { processed: removed, failed: 0 };
  }
}
