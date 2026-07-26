export interface Clock {
  now(): number;
  sleep(ms: number): Promise<void>;
}

export class SystemClock implements Clock {
  now(): number {
    return Date.now();
  }

  sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/** Deterministic clock for tests. Nothing resolves until time is advanced. */
export class ManualClock implements Clock {
  private current: number;
  private pending: Array<{ at: number; resolve: () => void }> = [];

  constructor(start = 0) {
    this.current = start;
  }

  now(): number {
    return this.current;
  }

  sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      this.pending.push({ at: this.current + ms, resolve });
    });
  }

  advance(by: number): void {
    this.current += by;
    const due = this.pending.filter((p) => p.at <= this.current);
    this.pending = this.pending.filter((p) => p.at > this.current);
    for (const p of due) {
      p.resolve();
    }
  }
}

export const systemClock = new SystemClock();
