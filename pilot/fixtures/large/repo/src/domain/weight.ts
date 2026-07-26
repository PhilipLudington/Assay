export type WeightUnit = 'g' | 'kg' | 'lb';

export interface Weight {
  value: number;
  unit: WeightUnit;
}

const TO_GRAMS: Record<WeightUnit, number> = { g: 1, kg: 1000, lb: 453.59237 };

export function toGrams(weight: Weight): number {
  return weight.value * TO_GRAMS[weight.unit];
}

export function heavier(a: Weight, b: Weight): Weight {
  return toGrams(a) >= toGrams(b) ? a : b;
}

/** Carriers bill on the greater of actual and volumetric weight. */
export function billableWeight(actual: Weight, volumetric: Weight): Weight {
  return heavier(actual, volumetric);
}

export function volumetricWeight(lengthCm: number, widthCm: number, heightCm: number): Weight {
  return { value: (lengthCm * widthCm * heightCm) / 5000, unit: 'kg' };
}
