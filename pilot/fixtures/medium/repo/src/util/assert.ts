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

export function assertNever(value: never, context: string): never {
  throw new InvariantError(`${context}: unexpected value ${JSON.stringify(value)}`);
}

export function required<T>(value: T | undefined | null, name: string): T {
  if (value === undefined || value === null) {
    throw new InvariantError(`${name} is required`);
  }
  return value;
}
