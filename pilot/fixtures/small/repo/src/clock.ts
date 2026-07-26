import type { Millis } from './types.js';

/**
 * Time source. Injected everywhere rather than calling Date.now() inline so
 * that tests can drive the limiter deterministically.
 */
export interface Clock {
  now(): Millis;
}

export class SystemClock implements Clock {
  now(): Millis {
    return Date.now();
  }
}

/** Test double. Time only moves when you move it. */
export class ManualClock implements Clock {
  private current: Millis;

  constructor(start: Millis = 0) {
    this.current = start;
  }

  now(): Millis {
    return this.current;
  }

  advance(by: Millis): void {
    if (by < 0) {
      throw new RangeError('ManualClock cannot move backwards');
    }
    this.current += by;
  }
}

export const systemClock = new SystemClock();
