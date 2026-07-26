export interface Clock {
  now(): number;
  isoNow(): string;
}

export class SystemClock implements Clock {
  now(): number {
    return Date.now();
  }

  isoNow(): string {
    return new Date().toISOString();
  }
}

export class FixedClock implements Clock {
  constructor(private at: number) {}

  now(): number {
    return this.at;
  }

  isoNow(): string {
    return new Date(this.at).toISOString();
  }

  set(at: number): void {
    this.at = at;
  }
}

export const systemClock = new SystemClock();
