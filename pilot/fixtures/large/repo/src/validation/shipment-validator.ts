import { SERVICE_LEVEL_ORDER, type ServiceLevel } from '../domain/carrier.js';
import type { ShipmentPatch } from '../domain/shipment.js';
import type { Weight, WeightUnit } from '../domain/weight.js';
import { validateAddress } from './address-validator.js';
import { Collector } from './schema.js';
import { isPlainObject, optionalString, requireEnum, requirePositiveNumber, requireString } from './validators.js';

const WEIGHT_UNITS: readonly WeightUnit[] = ['g', 'kg', 'lb'];

export interface ShipmentCreateInput {
  reference: string;
  carrierId: string;
  serviceLevel: ServiceLevel;
  origin: ReturnType<typeof validateAddress>;
  destination: ReturnType<typeof validateAddress>;
  weight: Weight;
}

export function validateShipmentCreate(body: unknown): ShipmentCreateInput {
  const collector = new Collector();
  if (!isPlainObject(body)) {
    collector.add('body', 'must be an object');
    collector.throwIfAny();
    throw new Error('unreachable');
  }

  const reference = requireString(collector, body, 'reference');
  const carrierId = requireString(collector, body, 'carrierId');
  const serviceLevel = requireEnum(collector, body, 'serviceLevel', SERVICE_LEVEL_ORDER);
  const origin = validateAddress(body['origin'], 'origin', collector);
  const destination = validateAddress(body['destination'], 'destination', collector);
  const weight = validateWeight(body['weight'], collector);

  collector.throwIfAny();
  return {
    reference: reference as string,
    carrierId: carrierId as string,
    serviceLevel: serviceLevel as ServiceLevel,
    origin,
    destination,
    weight: weight as Weight,
  };
}

/** Corrections are partial: every field is optional, but present ones must be valid. */
export function validateShipmentPatch(body: unknown): ShipmentPatch {
  const collector = new Collector();
  if (!isPlainObject(body)) {
    collector.add('body', 'must be an object');
    collector.throwIfAny();
    throw new Error('unreachable');
  }

  const patch: ShipmentPatch = {};
  if (body['reference'] !== undefined) {
    patch.reference = requireString(collector, body, 'reference') as string;
  }
  if (body['note'] !== undefined) {
    patch.note = optionalString(collector, body, 'note') as string;
  }
  if (body['destination'] !== undefined) {
    const destination = validateAddress(body['destination'], 'destination', collector);
    if (destination) {
      patch.destination = destination;
    }
  }
  if (body['weight'] !== undefined) {
    const weight = validateWeight(body['weight'], collector);
    if (weight) {
      patch.weight = weight;
    }
  }

  collector.throwIfAny();
  return patch;
}

function validateWeight(input: unknown, collector: Collector): Weight | undefined {
  if (!isPlainObject(input)) {
    collector.add('weight', 'must be an object');
    return undefined;
  }
  const value = requirePositiveNumber(collector, input, 'value');
  const unit = requireEnum(collector, input, 'unit', WEIGHT_UNITS);
  if (value === undefined || unit === undefined) {
    return undefined;
  }
  return { value, unit };
}
