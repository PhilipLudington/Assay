export const Scope = {
  ShipmentsRead: 'shipments:read',
  ShipmentsWrite: 'shipments:write',
  CarriersRead: 'carriers:read',
  CarriersWrite: 'carriers:write',
  WebhooksReceive: 'webhooks:receive',
  Admin: 'admin',
} as const;

export type ScopeName = (typeof Scope)[keyof typeof Scope];

/** A granted scope also grants everything it implies, transitively. */
const IMPLIES: Record<ScopeName, readonly ScopeName[]> = {
  [Scope.Admin]: [
    Scope.ShipmentsWrite,
    Scope.CarriersWrite,
    Scope.WebhooksReceive,
  ],
  [Scope.ShipmentsWrite]: [Scope.ShipmentsRead],
  [Scope.CarriersWrite]: [Scope.CarriersRead],
  [Scope.ShipmentsRead]: [],
  [Scope.CarriersRead]: [],
  [Scope.WebhooksReceive]: [],
};

export function expand(granted: readonly ScopeName[]): Set<ScopeName> {
  const out = new Set<ScopeName>();
  const queue = [...granted];
  while (queue.length > 0) {
    const scope = queue.pop();
    if (scope === undefined || out.has(scope)) {
      continue;
    }
    out.add(scope);
    queue.push(...IMPLIES[scope]);
  }
  return out;
}
