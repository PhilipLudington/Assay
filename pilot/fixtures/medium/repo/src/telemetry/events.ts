import type { JobId, JobRecord } from '../types.js';

export type QueueEvent =
  | { type: 'enqueued'; jobId: JobId; name: string }
  | { type: 'deduped'; jobId: JobId; existingId: JobId }
  | { type: 'started'; jobId: JobId; attempt: number; workerId: string }
  | { type: 'succeeded'; jobId: JobId; durationMs: number }
  | { type: 'failed'; jobId: JobId; attempt: number; error: string }
  | { type: 'retrying'; jobId: JobId; delayMs: number }
  | { type: 'dead'; jobId: JobId; reason: string }
  | { type: 'stalled'; jobId: JobId; lastHeartbeatAt: number | undefined };

export type Listener = (event: QueueEvent) => void;

export class EventBus {
  private readonly listeners = new Set<Listener>();

  on(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event: QueueEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // A misbehaving listener must not take the queue down.
      }
    }
  }
}

export function describeRecord(record: JobRecord): string {
  return `${record.name}#${record.id} attempt=${record.attempt}/${record.maxAttempts} status=${record.status}`;
}
