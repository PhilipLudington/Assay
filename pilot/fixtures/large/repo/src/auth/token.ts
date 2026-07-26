import { createHmac, timingSafeEqual } from 'node:crypto';
import { principalFrom, type Principal } from './principal.js';
import type { ScopeName } from './scopes.js';

export class InvalidTokenError extends Error {
  constructor(reason: string) {
    super(`invalid token: ${reason}`);
    this.name = 'InvalidTokenError';
  }
}

interface TokenClaims {
  sub: string;
  acc: string;
  scopes: ScopeName[];
  exp: number;
}

function sign(payload: string, secret: string): string {
  return createHmac('sha256', secret).update(payload).digest('base64url');
}

export function verifyToken(token: string, secret: string, now: number): Principal {
  const [payload, signature] = token.split('.');
  if (!payload || !signature) {
    throw new InvalidTokenError('malformed');
  }

  const expected = Buffer.from(sign(payload, secret));
  const actual = Buffer.from(signature);
  if (expected.length !== actual.length || !timingSafeEqual(expected, actual)) {
    throw new InvalidTokenError('bad signature');
  }

  let claims: TokenClaims;
  try {
    claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as TokenClaims;
  } catch {
    throw new InvalidTokenError('unparseable payload');
  }

  if (claims.exp <= now / 1000) {
    throw new InvalidTokenError('expired');
  }
  return principalFrom(claims.sub, claims.acc, claims.scopes ?? []);
}
