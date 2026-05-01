// Server action: sign the session JWT and set the HttpOnly cookie on the
// response. Called from the various /api/auth/* routes once an OAuth or
// Cognito API call has produced a valid idToken.

import { NextResponse } from "next/server";
import { signSession, SESSION_COOKIE } from "./auth";

export async function setSessionCookie(res: NextResponse, params: {
  sub: string; email?: string; idToken: string; refreshToken?: string; ttlSeconds?: number;
}) {
  const jwt = await signSession({
    sub: params.sub,
    email: params.email,
    id_token: params.idToken,
    refresh_token: params.refreshToken,
    ttlSeconds: params.ttlSeconds ?? 3600,
  });
  res.cookies.set({
    name: SESSION_COOKIE,
    value: jwt,
    httpOnly: true, secure: true, sameSite: "lax", path: "/",
    maxAge: params.ttlSeconds ?? 3600,
  });
  return res;
}
