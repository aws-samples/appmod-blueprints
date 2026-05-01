// /api/auth/logout — clear our session cookie and return to landing.
//
// We don't bounce through Cognito's /logout endpoint because we're
// using direct API auth (not hosted UI), so there's no Cognito browser
// session to invalidate. The idToken in our cookie is the only auth
// state, and deleting the cookie is sufficient.

import { NextResponse } from "next/server";
import { SESSION_COOKIE, APP_URL } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  // Build the redirect from APP_URL (the externally-reachable origin),
  // not req.url — behind the ALB, req.url reports the pod's internal
  // http://localhost:3000/ and the browser ends up there.
  const res = NextResponse.redirect(`${APP_URL}/`);
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
