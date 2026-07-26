import { randomUUID, randomBytes } from 'node:crypto';

const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

export function shipmentId(): string {
  return `shp_${randomUUID().replace(/-/g, '').slice(0, 24)}`;
}

export function carrierId(): string {
  return `car_${randomUUID().replace(/-/g, '').slice(0, 16)}`;
}

export function eventId(): string {
  return `evt_${randomUUID().replace(/-/g, '').slice(0, 24)}`;
}

export function requestId(): string {
  return `req_${randomUUID()}`;
}

/** Human-quotable tracking number. Crockford-ish, no ambiguous glyphs. */
export function trackingNumber(): string {
  const bytes = randomBytes(10);
  let out = '';
  for (const byte of bytes) {
    out += ALPHABET[byte % ALPHABET.length];
  }
  return out;
}
