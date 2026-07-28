/**
 * A stock-keeping unit. Branded so that a bare string cannot be passed where
 * the inventory tables expect a normalised sku — the tables are keyed on the
 * upper-case form and a lower-case lookup silently misses.
 */
export type Sku = string & { readonly __brand: 'Sku' };

const SKU_PATTERN = /^[A-Z0-9]{3,12}(-[A-Z0-9]{1,6})?$/;

export function parseSku(raw: string): Sku {
  const normalised = raw.trim().toUpperCase();
  if (!SKU_PATTERN.test(normalised)) {
    throw new Error(`not a valid sku: ${raw}`);
  }
  return normalised as Sku;
}

export function isSku(raw: string): boolean {
  return SKU_PATTERN.test(raw.trim().toUpperCase());
}

export function skuEquals(left: Sku, right: Sku): boolean {
  return left === right;
}
