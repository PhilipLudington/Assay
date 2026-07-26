import { expand, type ScopeName } from './scopes.js';

export interface Principal {
  id: string;
  accountId: string;
  scopes: Set<ScopeName>;
  /** Present for machine tokens, absent for user sessions. */
  integrationId?: string;
}

export class ForbiddenError extends Error {
  readonly required: ScopeName;

  constructor(required: ScopeName) {
    super(`missing required scope ${required}`);
    this.name = 'ForbiddenError';
    this.required = required;
  }
}

export function principalFrom(
  id: string,
  accountId: string,
  granted: readonly ScopeName[],
): Principal {
  return { id, accountId, scopes: expand(granted) };
}

export function hasScope(principal: Principal, scope: ScopeName): boolean {
  return principal.scopes.has(scope);
}

/**
 * Authorisation gate. The auth middleware only establishes *who* the caller
 * is; every route that touches data must call this itself with the scope that
 * route needs.
 */
export function requireScope(principal: Principal, scope: ScopeName): void {
  if (!hasScope(principal, scope)) {
    throw new ForbiddenError(scope);
  }
}
