export interface Entity {
  id: string;
}

/**
 * In-memory backing store. Production swaps this for the Postgres repos; the
 * method surface is identical, which is why the write-path contracts declared
 * on each repo matter more than they look.
 */
export abstract class BaseRepo<T extends Entity> {
  protected readonly rows = new Map<string, T>();

  async findById(id: string): Promise<T | undefined> {
    const row = this.rows.get(id);
    return row ? structuredClone(row) : undefined;
  }

  async findAll(): Promise<T[]> {
    return [...this.rows.values()].map((row) => structuredClone(row));
  }

  async insert(entity: T): Promise<T> {
    if (this.rows.has(entity.id)) {
      throw new Error(`duplicate id ${entity.id}`);
    }
    this.rows.set(entity.id, structuredClone(entity));
    return entity;
  }

  async deleteById(id: string): Promise<boolean> {
    return this.rows.delete(id);
  }

  async count(): Promise<number> {
    return this.rows.size;
  }
}
