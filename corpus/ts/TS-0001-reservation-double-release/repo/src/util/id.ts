/**
 * Identifier generation. Deliberately not random at the type level: every id
 * carries the prefix of the thing it names, so a mis-routed id is visible in a
 * log line rather than only in a foreign-key error.
 */
export interface IdGenerator {
  next(prefix: string): string;
}

export class CounterIdGenerator implements IdGenerator {
  private counter = 0;

  next(prefix: string): string {
    this.counter += 1;
    return `${prefix}_${this.counter.toString(36).padStart(8, '0')}`;
  }
}

export function hasPrefix(id: string, prefix: string): boolean {
  return id.startsWith(`${prefix}_`);
}
