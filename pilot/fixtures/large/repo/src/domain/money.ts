export type CurrencyCode = 'GBP' | 'EUR' | 'USD';

/** Money is always stored in minor units to keep arithmetic exact. */
export interface Money {
  amountMinor: number;
  currency: CurrencyCode;
}

export function money(amountMinor: number, currency: CurrencyCode): Money {
  if (!Number.isInteger(amountMinor)) {
    throw new RangeError('amountMinor must be an integer number of minor units');
  }
  return { amountMinor, currency };
}

export function add(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.amountMinor + b.amountMinor, a.currency);
}

export function scale(value: Money, factor: number): Money {
  return money(Math.round(value.amountMinor * factor), value.currency);
}

export function assertSameCurrency(a: Money, b: Money): void {
  if (a.currency !== b.currency) {
    throw new TypeError(`currency mismatch: ${a.currency} vs ${b.currency}`);
  }
}

export function format(value: Money): string {
  return `${(value.amountMinor / 100).toFixed(2)} ${value.currency}`;
}
