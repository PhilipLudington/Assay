export class InvariantError extends Error {
  constructor(message: string) {
    super(`invariant violated: ${message}`);
    this.name = 'InvariantError';
  }
}

export function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new InvariantError(message);
  }
}

export function required<T>(value: T | null | undefined, name: string): T {
  if (value === null || value === undefined) {
    throw new InvariantError(`${name} is required`);
  }
  return value;
}

export function exhaustive(value: never, context: string): never {
  throw new InvariantError(`${context}: unhandled ${JSON.stringify(value)}`);
}
