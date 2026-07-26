import type { Carrier, ServiceLevel } from '../domain/carrier.js';
import type { CarrierRepo } from '../repositories/carrier-repo.js';

export class UnknownCarrierError extends Error {
  constructor(id: string) {
    super(`carrier ${id} not found`);
    this.name = 'UnknownCarrierError';
  }
}

export class CarrierService {
  constructor(private readonly carriers: CarrierRepo) {}

  async list(): Promise<Carrier[]> {
    return this.carriers.findAll();
  }

  async byId(id: string): Promise<Carrier> {
    const carrier = await this.carriers.findById(id);
    if (!carrier) {
      throw new UnknownCarrierError(id);
    }
    return carrier;
  }

  async eligible(level: ServiceLevel, originCountry: string): Promise<Carrier[]> {
    return this.carriers.supporting(level, originCountry);
  }

  async setActive(id: string, active: boolean): Promise<Carrier> {
    const updated = await this.carriers.update(id, { active });
    if (!updated) {
      throw new UnknownCarrierError(id);
    }
    return updated;
  }
}
