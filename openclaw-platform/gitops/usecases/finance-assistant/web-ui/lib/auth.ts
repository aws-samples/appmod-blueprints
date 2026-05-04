// Cognito OAuth Authorization Code flow, app-managed.
//
// The ALB is a dumb HTTPS router. Next.js owns the redirect dance,
// exchanges the code for tokens, verifies the ID token against
// Cognito JWKS, and issues an HttpOnly session cookie.
//
// We store only id_token and refresh_token in the cookie. Access
// token is not needed since our only downstream is the in-cluster
// adapter/router — not a separate API server.

import { SignJWT, jwtVerify, createRemoteJWKSet, type JWTPayload } from "jose";

export const COGNITO_REGION   = process.env.COGNITO_REGION   || "us-west-2";
export const USER_POOL_ID     = process.env.COGNITO_USER_POOL_ID     || "";
export const CLIENT_ID        = process.env.COGNITO_CLIENT_ID        || "";
export const CLIENT_SECRET    = process.env.COGNITO_CLIENT_SECRET    || "";
export const DOMAIN_PREFIX    = process.env.COGNITO_DOMAIN_PREFIX    || "";
export const APP_URL          = process.env.APP_URL                  || "";
export const SESSION_SECRET   = process.env.SESSION_SECRET           || "";

export const COGNITO_BASE = `https://${DOMAIN_PREFIX}.auth.${COGNITO_REGION}.amazoncognito.com`;
export const REDIRECT_URI = `${APP_URL}/api/auth/callback`;
export const ISSUER       = `https://cognito-idp.${COGNITO_REGION}.amazonaws.com/${USER_POOL_ID}`;

export const SESSION_COOKIE = "fa_session";

// Cognito JWKS for verifying id_tokens. jose caches this.
const jwks = createRemoteJWKSet(new URL(`${ISSUER}/.well-known/jwks.json`));

function secretKey(): Uint8Array {
  if (!SESSION_SECRET) {
    throw new Error("SESSION_SECRET env var not set — refuse to sign cookies with a known key");
  }
  return new TextEncoder().encode(SESSION_SECRET);
}

export type Session = {
  sub: string;
  email?: string;
  exp: number;
};

export async function signSession(s: Omit<Session, "exp"> & { ttlSeconds?: number }): Promise<string> {
  const ttl = s.ttlSeconds ?? 3600;
  return await new SignJWT({
    sub: s.sub, email: s.email,
  } as JWTPayload)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${ttl}s`)
    .sign(secretKey());
}

export async function verifySession(token: string): Promise<Session | null> {
  try {
    const { payload } = await jwtVerify(token, secretKey());
    return {
      sub: payload.sub as string,
      email: payload.email as string | undefined,
      exp: payload.exp as number,
    };
  } catch { return null; }
}

// Build the Cognito /oauth2/authorize URL. `state` is a one-time nonce
// we verify on callback — required to prevent CSRF on the OAuth flow.
export function authorizeUrl(state: string, scope = "openid email profile"): string {
  const u = new URL(`${COGNITO_BASE}/oauth2/authorize`);
  u.searchParams.set("response_type", "code");
  u.searchParams.set("client_id", CLIENT_ID);
  u.searchParams.set("redirect_uri", REDIRECT_URI);
  u.searchParams.set("scope", scope);
  u.searchParams.set("state", state);
  return u.toString();
}

// Exchange authorization code for id_token + refresh_token.
export async function exchangeCode(code: string): Promise<{ idToken: string; refreshToken?: string } | null> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
  });
  const headers: Record<string, string> = { "Content-Type": "application/x-www-form-urlencoded" };
  if (CLIENT_SECRET) {
    const basic = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString("base64");
    headers["Authorization"] = `Basic ${basic}`;
  }
  const res = await fetch(`${COGNITO_BASE}/oauth2/token`, { method: "POST", headers, body });
  if (!res.ok) {
    console.error("[auth] token exchange failed:", res.status, await res.text().catch(() => ""));
    return null;
  }
  const j = await res.json();
  return { idToken: j.id_token, refreshToken: j.refresh_token };
}

// Verify Cognito id_token and return the claims.
export async function verifyIdToken(idToken: string): Promise<{ sub: string; email?: string } | null> {
  try {
    const { payload } = await jwtVerify(idToken, jwks, {
      issuer: ISSUER,
      audience: CLIENT_ID,
    });
    return { sub: payload.sub as string, email: payload.email as string | undefined };
  } catch (e) {
    console.error("[auth] id_token verify failed:", (e as Error).message);
    return null;
  }
}

export function logoutUrl(): string {
  const u = new URL(`${COGNITO_BASE}/logout`);
  u.searchParams.set("client_id", CLIENT_ID);
  u.searchParams.set("logout_uri", APP_URL);
  return u.toString();
}
