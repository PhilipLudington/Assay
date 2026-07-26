import type { Address } from '../domain/address.js';
import { normalisePostcode } from '../domain/address.js';
import { Collector } from './schema.js';
import { isPlainObject, optionalString, requireString } from './validators.js';

const POSTCODE_PATTERNS: Record<string, RegExp> = {
  GB: /^[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}$/,
  US: /^\d{5}(-\d{4})?$/,
  DE: /^\d{5}$/,
};

export function validateAddress(input: unknown, path: string, collector: Collector): Address | undefined {
  if (!isPlainObject(input)) {
    collector.add(path, 'must be an object');
    return undefined;
  }

  const line1 = requireString(collector, input, `${path}.line1`.slice(path.length + 1)) ?? '';
  const city = requireString(collector, input, 'city') ?? '';
  const postcode = requireString(collector, input, 'postcode') ?? '';
  const countryCode = requireString(collector, input, 'countryCode') ?? '';

  if (countryCode.length !== 2) {
    collector.add(`${path}.countryCode`, 'must be a two-letter ISO country code');
  }

  const pattern = POSTCODE_PATTERNS[countryCode.toUpperCase()];
  if (pattern && !pattern.test(postcode.toUpperCase())) {
    collector.add(`${path}.postcode`, `is not valid for ${countryCode}`);
  }

  if (!collector.isEmpty) {
    return undefined;
  }

  return {
    line1,
    city,
    postcode: normalisePostcode(postcode, countryCode.toUpperCase()),
    countryCode: countryCode.toUpperCase(),
    ...(optionalString(collector, input, 'line2') === undefined
      ? {}
      : { line2: input['line2'] as string }),
    ...(optionalString(collector, input, 'region') === undefined
      ? {}
      : { region: input['region'] as string }),
  };
}
