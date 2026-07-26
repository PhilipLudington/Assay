import type { JobRecord } from '../types.js';

/**
 * Higher priority first; ties break on enqueue time so equal-priority work
 * stays FIFO.
 */
export function compareRecords(a: JobRecord, b: JobRecord): number {
  if (a.priority !== b.priority) {
    return b.priority - a.priority;
  }
  return a.enqueuedAt - b.enqueuedAt;
}

export function sortByPriority(records: JobRecord[]): JobRecord[] {
  return [...records].sort(compareRecords);
}

export const PRIORITY = {
  low: -10,
  normal: 0,
  high: 10,
  critical: 100,
} as const;

export type PriorityName = keyof typeof PRIORITY;

export function priorityValue(priority: number | PriorityName): number {
  return typeof priority === 'number' ? priority : PRIORITY[priority];
}
