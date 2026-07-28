import type { Db } from '../db/client.js';
import type { AuditRow } from '../db/rows.js';
import type { Clock } from '../util/clock.js';
import type { IdGenerator } from '../util/id.js';
import { BaseRepo } from './base-repo.js';

export interface AuditEntry {
  id: string;
  subject: string;
  action: string;
  detail: string;
  recordedAt: number;
}

function toEntry(row: AuditRow): AuditEntry {
  return {
    id: row.id,
    subject: row.subject,
    action: row.action,
    detail: row.detail,
    recordedAt: row.recorded_at,
  };
}

/**
 * The audit trail is advisory: it records what the service did for support
 * staff to read back. Nothing reads it to make a decision, which is why the
 * pruner is allowed to drop old rows outright.
 */
export class AuditRepo extends BaseRepo {
  constructor(
    db: Db,
    private readonly clock: Clock,
    private readonly ids: IdGenerator,
  ) {
    super(db);
  }

  async record(subject: string, action: string, detail: string): Promise<AuditEntry> {
    return this.inTransaction(async (tx) => {
      const row: AuditRow = {
        id: this.ids.next('aud'),
        subject,
        action,
        detail,
        recorded_at: this.clock.now(),
      };
      tx.tables.audit.push(row);
      return toEntry(row);
    });
  }

  async listForSubject(subject: string): Promise<AuditEntry[]> {
    return this.db
      .read()
      .audit.filter((row) => row.subject === subject)
      .map(toEntry);
  }

  async deleteOlderThan(cutoff: number): Promise<number> {
    return this.inTransaction(async (tx) => {
      const before = tx.tables.audit.length;
      tx.tables.audit = tx.tables.audit.filter((row) => row.recorded_at >= cutoff);
      return before - tx.tables.audit.length;
    });
  }
}
