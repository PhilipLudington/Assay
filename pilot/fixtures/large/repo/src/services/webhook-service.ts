import { createHmac } from 'node:crypto';
import type { TrackingEvent } from '../domain/tracking-event.js';
import type { Logger } from '../util/logger.js';
import { withRetry } from '../util/retry.js';

export interface Subscription {
  id: string;
  accountId: string;
  url: string;
  secret: string;
  eventTypes: TrackingEvent['type'][];
  active: boolean;
}

/**
 * Fans tracking events out to customer endpoints. Everything customers see
 * downstream of a mutation flows through here, which is why a mutation that
 * never produces an event is invisible rather than merely late.
 */
export class WebhookService {
  private readonly subscriptions = new Map<string, Subscription>();

  constructor(
    private readonly logger: Logger,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  subscribe(subscription: Subscription): void {
    this.subscriptions.set(subscription.id, subscription);
  }

  unsubscribe(id: string): void {
    this.subscriptions.delete(id);
  }

  listFor(accountId: string): Subscription[] {
    return [...this.subscriptions.values()].filter((s) => s.accountId === accountId);
  }

  async dispatch(event: TrackingEvent): Promise<void> {
    const targets = [...this.subscriptions.values()].filter(
      (s) => s.active && s.eventTypes.includes(event.type),
    );
    await Promise.all(targets.map((target) => this.deliver(target, event)));
  }

  private async deliver(subscription: Subscription, event: TrackingEvent): Promise<void> {
    const body = JSON.stringify(event);
    const signature = createHmac('sha256', subscription.secret).update(body).digest('hex');
    try {
      await withRetry(async () => {
        const response = await this.fetchImpl(subscription.url, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-acme-signature': signature,
          },
          body,
        });
        if (!response.ok) {
          throw new Error(`webhook ${subscription.id} returned ${response.status}`);
        }
      });
    } catch (error) {
      this.logger.log('warn', 'webhook delivery failed', {
        subscriptionId: subscription.id,
        eventId: event.id,
        error: String(error),
      });
    }
  }
}
