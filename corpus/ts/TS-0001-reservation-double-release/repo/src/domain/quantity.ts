/**
 * Quantities crossing the API boundary are validated once, here, so that the
 * rest of the service can treat them as whole non-negative units.
 *
 * Note that stored column values (`on_hand`, `held`) are plain numbers rather
 * than `Quantity`: the database is the system of record and this type is a
 * parsing result, not a storage constraint.
 */
export type Quantity = number & { readonly __brand: 'Quantity' };

export const MAX_LINE_QUANTITY = 10_000;

export function quantity(value: number): Quantity {
  if (!Number.isInteger(value)) {
    throw new Error(`quantity must be a whole number of units: ${value}`);
  }
  if (value < 0) {
    throw new Error(`quantity must not be negative: ${value}`);
  }
  if (value > MAX_LINE_QUANTITY) {
    throw new Error(`quantity exceeds the per-line maximum: ${value}`);
  }
  return value as Quantity;
}

export function isQuantity(value: number): boolean {
  return Number.isInteger(value) && value >= 0 && value <= MAX_LINE_QUANTITY;
}

export function sumQuantities(values: readonly Quantity[]): number {
  return values.reduce<number>((total, value) => total + value, 0);
}
