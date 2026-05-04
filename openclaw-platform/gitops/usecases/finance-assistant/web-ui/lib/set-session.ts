// Server action: sign the session JWT and set the HttpOnly cookie on the
// response. Called from the various /api/auth/* routes once Cognito has
// accepted the user. We deliberately do NOT store the Cognito id_token
// or refresh_token in the cookie — the combined JWT overflows Chromium's
// 4KB per-cookie limit and the browser silently drops it. The only
// claims we ever read downstream are `sub` and `email`.

import { NextResponse } from "next/server";
import { signSession, SESSION_COOKIE } from "./auth";

export async function setSessionCookie(res: NextResponse, params: {
  sub: string; email?: string; ttlSeconds?: number;
}) {
  const jwt = await signSession({
    sub: params.sub,
    email: params.email,
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
