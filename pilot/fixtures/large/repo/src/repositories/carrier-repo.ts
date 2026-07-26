import type { Carrier, ServiceLevel } from '../domain/carrier.js';
import { supportsService } from '../domain/carrier.js';
import { BaseRepo } from './base-repo.js';

export class CarrierRepo extends BaseRepo<Carrier> {
  async active(): Promise<Carrier[]> {
    return (await this.findAll()).filter((carrier) => carrier.active);
  }

  async supporting(level: ServiceLevel, originCountry: string): Promise<Carrier[]> {
    return (await this.active()).filter(
      (carrier) =>
        supportsService(carrier, level) && carrier.originCountries.includes(originCountry),
    );
  }

  async update(id: string, patch: Partial<Carrier>): Promise<Carrier | undefined> {
    const existing = this.rows.get(id);
    if (!existing) {
      return undefined;
    }
    const next = { ...existing, ...patch, id: existing.id };
    this.rows.set(id, next);
    return structuredClone(next);
  }
}
