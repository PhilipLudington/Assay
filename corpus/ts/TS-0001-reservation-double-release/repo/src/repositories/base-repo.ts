import type { Db } from '../db/client.js';
import type { Tx } from '../db/tx.js';

/**
 * Shared plumbing for the repositories.
 *
 * Every write method comes in two forms: a `*Within` form that takes the
 * caller's transaction, and a convenience form that opens one of its own. The
 * split exists so that a write which must be atomic with another write can be,
 * without repositories reaching into each other's tables.
 */
export abstract class BaseRepo {
  protected constructor(protected readonly db: Db) {}

  protected async inTransaction<T>(fn: (tx: Tx) => Promise<T>): Promise<T> {
    return this.db.transaction(fn);
  }
}

export function findIndexBy<T>(rows: readonly T[], predicate: (row: T) => boolean): number {
  return rows.findIndex(predicate);
}

export function requireRow<T>(row: T | undefined, describe: () => string): T {
  if (row === undefined) {
    throw new Error(describe());
  }
  return row;
}
