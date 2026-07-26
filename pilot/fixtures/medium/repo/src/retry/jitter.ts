export type JitterMode = 'none' | 'full' | 'equal';

export interface Random {
  next(): number;
}

export const systemRandom: Random = { next: () => Math.random() };

/**
 * Spreads retries so a batch of jobs that failed together does not come back
 * in lockstep.
 */
export function applyJitter(delayMs: number, mode: JitterMode, random: Random = systemRandom): number {
  switch (mode) {
    case 'none':
      return delayMs;
    case 'full':
      return Math.round(random.next() * delayMs);
    case 'equal':
      return Math.round(delayMs / 2 + random.next() * (delayMs / 2));
  }
}
