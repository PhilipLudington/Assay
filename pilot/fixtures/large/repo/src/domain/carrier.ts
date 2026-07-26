import type { Money } from './money.js';

export type ServiceLevel = 'economy' | 'standard' | 'express' | 'overnight';

export interface Carrier {
  id: string;
  name: string;
  active: boolean;
  serviceLevels: ServiceLevel[];
  /** Countries this carrier will collect from. */
  originCountries: string[];
  basePrice: Money;
  /** Multiplier applied per billable kilogram. */
  pricePerKgMinor: number;
  trackingUrlTemplate: string;
}

export function supportsService(carrier: Carrier, level: ServiceLevel): boolean {
  return carrier.active && carrier.serviceLevels.includes(level);
}

export function trackingUrlFor(carrier: Carrier, trackingNumber: string): string {
  return carrier.trackingUrlTemplate.replace('{tracking}', encodeURIComponent(trackingNumber));
}

export const SERVICE_LEVEL_ORDER: readonly ServiceLevel[] = [
  'economy',
  'standard',
  'express',
  'overnight',
];
