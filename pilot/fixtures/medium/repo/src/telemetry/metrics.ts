import type { QueueEvent } from './events.js';

export interface MetricsSnapshot {
  enqueued: number;
  started: number;
  succeeded: number;
  failed: number;
  retried: number;
  dead: number;
  stalled: number;
  durationsMs: number[];
}

/** Counters only. Anything richer belongs in the host application. */
export class Metrics {
  private snapshot: MetricsSnapshot = {
    enqueued: 0,
    started: 0,
    succeeded: 0,
    failed: 0,
    retried: 0,
    dead: 0,
    stalled: 0,
    durationsMs: [],
  };

  observe(event: QueueEvent): void {
    switch (event.type) {
      case 'enqueued':
        this.snapshot.enqueued += 1;
        break;
      case 'started':
        this.snapshot.started += 1;
        break;
      case 'succeeded':
        this.snapshot.succeeded += 1;
        this.snapshot.durationsMs.push(event.durationMs);
        break;
      case 'failed':
        this.snapshot.failed += 1;
        break;
      case 'retrying':
        this.snapshot.retried += 1;
        break;
      case 'dead':
        this.snapshot.dead += 1;
        break;
      case 'stalled':
        this.snapshot.stalled += 1;
        break;
      default:
        break;
    }
  }

  read(): MetricsSnapshot {
    return { ...this.snapshot, durationsMs: [...this.snapshot.durationsMs] };
  }

  percentile(p: number): number {
    const sorted = [...this.snapshot.durationsMs].sort((a, b) => a - b);
    if (sorted.length === 0) {
      return 0;
    }
    const idx = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
    return sorted[idx] ?? 0;
  }
}
