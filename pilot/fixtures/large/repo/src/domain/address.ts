export interface Address {
  line1: string;
  line2?: string;
  city: string;
  region?: string;
  postcode: string;
  countryCode: string;
}

export function normalisePostcode(postcode: string, countryCode: string): string {
  const stripped = postcode.replace(/\s+/g, '').toUpperCase();
  if (countryCode !== 'GB') {
    return stripped;
  }
  return `${stripped.slice(0, -3)} ${stripped.slice(-3)}`;
}

export function isDomestic(from: Address, to: Address): boolean {
  return from.countryCode === to.countryCode;
}

export function formatAddress(address: Address): string {
  return [
    address.line1,
    address.line2,
    address.city,
    address.region,
    address.postcode,
    address.countryCode,
  ]
    .filter(Boolean)
    .join(', ');
}
