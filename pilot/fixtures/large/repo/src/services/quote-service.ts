import type { Address } from '../domain/address.js';
import { isDomestic } from '../domain/address.js';
import type { Carrier, ServiceLevel } from '../domain/carrier.js';
import { add, money, scale, type Money } from '../domain/money.js';
import { toGrams, type Weight } from '../domain/weight.js';
import type { CarrierService } from './carrier-service.js';

export interface QuoteRequest {
  origin: Address;
  destination: Address;
  weight: Weight;
  serviceLevel: ServiceLevel;
}

export interface Quote {
  carrierId: string;
  carrierName: string;
  serviceLevel: ServiceLevel;
  price: Money;
  estimatedDays: number;
}

const SERVICE_DAYS: Record<ServiceLevel, number> = {
  economy: 5,
  standard: 3,
  express: 2,
  overnight: 1,
};

const INTERNATIONAL_SURCHARGE = 1.4;

export class QuoteService {
  constructor(private readonly carriers: CarrierService) {}

  async quotesFor(request: QuoteRequest): Promise<Quote[]> {
    const eligible = await this.carriers.eligible(
      request.serviceLevel,
      request.origin.countryCode,
    );
    return eligible
      .map((carrier) => this.priceFor(carrier, request))
      .sort((a, b) => a.price.amountMinor - b.price.amountMinor);
  }

  priceFor(carrier: Carrier, request: QuoteRequest): Quote {
    const kg = toGrams(request.weight) / 1000;
    const variable = money(Math.round(carrier.pricePerKgMinor * kg), carrier.basePrice.currency);
    let price = add(carrier.basePrice, variable);
    if (!isDomestic(request.origin, request.destination)) {
      price = scale(price, INTERNATIONAL_SURCHARGE);
    }
    return {
      carrierId: carrier.id,
      carrierName: carrier.name,
      serviceLevel: request.serviceLevel,
      price,
      estimatedDays: SERVICE_DAYS[request.serviceLevel],
    };
  }
}
