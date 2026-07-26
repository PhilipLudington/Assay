import type { Collector } from './schema.js';

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function requireString(
  collector: Collector,
  source: Record<string, unknown>,
  field: string,
  { maxLength = 255 }: { maxLength?: number } = {},
): string | undefined {
  const value = source[field];
  if (typeof value !== 'string' || value.trim() === '') {
    collector.add(field, 'must be a non-empty string');
    return undefined;
  }
  if (value.length > maxLength) {
    collector.add(field, `must be at most ${maxLength} characters`);
    return undefined;
  }
  return value;
}

export function optionalString(
  collector: Collector,
  source: Record<string, unknown>,
  field: string,
): string | undefined {
  if (source[field] === undefined) {
    return undefined;
  }
  return requireString(collector, source, field);
}

export function requirePositiveNumber(
  collector: Collector,
  source: Record<string, unknown>,
  field: string,
): number | undefined {
  const value = source[field];
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    collector.add(field, 'must be a positive number');
    return undefined;
  }
  return value;
}

export function requireEnum<T extends string>(
  collector: Collector,
  source: Record<string, unknown>,
  field: string,
  allowed: readonly T[],
): T | undefined {
  const value = source[field];
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    collector.add(field, `must be one of ${allowed.join(', ')}`);
    return undefined;
  }
  return value as T;
}
