export interface FieldError {
  field: string;
  message: string;
}

export class ValidationError extends Error {
  readonly errors: FieldError[];

  constructor(errors: FieldError[]) {
    super(`validation failed: ${errors.map((e) => `${e.field} ${e.message}`).join('; ')}`);
    this.name = 'ValidationError';
    this.errors = errors;
  }
}

export class Collector {
  private readonly errors: FieldError[] = [];

  add(field: string, message: string): void {
    this.errors.push({ field, message });
  }

  addIf(condition: unknown, field: string, message: string): void {
    if (condition) {
      this.add(field, message);
    }
  }

  throwIfAny(): void {
    if (this.errors.length > 0) {
      throw new ValidationError(this.errors);
    }
  }

  get isEmpty(): boolean {
    return this.errors.length === 0;
  }
}
