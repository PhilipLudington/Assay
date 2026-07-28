/**
 * Time is injected everywhere in this service so that jobs and expiry windows
 * are testable without sleeping.
 */
export interface Clock {
  /** Milliseconds since the epoch. */
  now(): number;
}

export const systemClock: Clock = {
  now(): number {
    return Date.now();
  },
};

/** A clock that only moves when it is told to. Used by the job tests. */
export class ManualClock implements Clock {
  private current: number;

  constructor(startMs = 0) {
    this.current = startMs;
  }

  now(): number {
    return this.current;
  }

  advance(ms: number): void {
    this.current += ms;
  }
}
