import { cloneTables, emptyTables, type Tables, type Tx } from './tx.js';

/**
 * The storage driver.
 *
 * Backed by in-memory tables in every deployment we currently run; the
 * interface is the one the SQL driver will present when the migration lands,
 * which is why writes are only reachable through `transaction`.
 */
export class Db {
  private tables: Tables;

  constructor(tables: Tables = emptyTables()) {
    this.tables = tables;
  }

  /**
   * Runs `fn` against a snapshot. If it throws, the snapshot is discarded and
   * the tables are left exactly as they were — a partially applied write is
   * never visible to another caller.
   */
  async transaction<T>(fn: (tx: Tx) => Promise<T>): Promise<T> {
    const snapshot = cloneTables(this.tables);
    const afterCommit: (() => void)[] = [];
    const tx: Tx = {
      tables: snapshot,
      onCommit(hook: () => void): void {
        afterCommit.push(hook);
      },
    };

    const result = await fn(tx);

    this.tables = snapshot;
    for (const hook of afterCommit) {
      hook();
    }
    return result;
  }

  /** Read-only view for queries that do not need a transaction. */
  read(): Readonly<Tables> {
    return this.tables;
  }
}
