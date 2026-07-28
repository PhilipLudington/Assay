/** Base class for failures that map onto a 4xx rather than a 5xx. */
export class DomainError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = new.target.name;
  }
}

export class NotFoundError extends DomainError {
  constructor(what: string, id: string) {
    super(`${what} ${id} not found`, 'not_found');
  }
}

export class ConflictError extends DomainError {
  constructor(message: string) {
    super(message, 'conflict');
  }
}

export class ValidationError extends DomainError {
  constructor(message: string) {
    super(message, 'validation_failed');
  }
}

export class InsufficientStockError extends DomainError {
  constructor(
    readonly sku: string,
    readonly requested: number,
    readonly available: number,
  ) {
    super(
      `insufficient stock for ${sku}: requested ${requested}, available ${available}`,
      'insufficient_stock',
    );
  }
}
