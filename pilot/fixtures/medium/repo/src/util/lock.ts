/**
 * Minimal async mutex. The store uses it to serialise read-modify-write
 * sequences that would otherwise interleave across awaits.
 */
export class Mutex {
  private tail: Promise<void> = Promise.resolve();

  async run<T>(fn: () => Promise<T>): Promise<T> {
    const previous = this.tail;
    let release!: () => void;
    this.tail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await fn();
    } finally {
      release();
    }
  }
}

/** Keyed mutex — serialises per key, runs different keys in parallel. */
export class KeyedMutex {
  private readonly locks = new Map<string, Mutex>();

  run<T>(key: string, fn: () => Promise<T>): Promise<T> {
    let lock = this.locks.get(key);
    if (!lock) {
      lock = new Mutex();
      this.locks.set(key, lock);
    }
    return lock.run(fn);
  }

  forget(key: string): void {
    this.locks.delete(key);
  }
}
