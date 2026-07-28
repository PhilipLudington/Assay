export interface Metrics {
  increment(name: string, by?: number): void;
  gauge(name: string, value: number): void;
}

/** In-process counters. The exporter scrapes them on an interval. */
export class InMemoryMetrics implements Metrics {
  private readonly counters = new Map<string, number>();
  private readonly gauges = new Map<string, number>();

  increment(name: string, by = 1): void {
    this.counters.set(name, (this.counters.get(name) ?? 0) + by);
  }

  gauge(name: string, value: number): void {
    this.gauges.set(name, value);
  }

  snapshot(): { counters: Record<string, number>; gauges: Record<string, number> } {
    return {
      counters: Object.fromEntries(this.counters),
      gauges: Object.fromEntries(this.gauges),
    };
  }
}

export const noopMetrics: Metrics = {
  increment(): void {},
  gauge(): void {},
};
