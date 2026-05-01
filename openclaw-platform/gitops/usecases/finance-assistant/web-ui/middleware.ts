// App-layer auth gate.
//
// /api/chat — protected; 401 when no valid session cookie
// /app      — protected; redirect to / (landing) where the modal opens
// everything else on /  — public (landing page + static assets + auth APIs)

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify } from "jose";

const SESSION_COOKIE = "fa_session";

function secret(): Uint8Array | null {
  const s = process.env.SESSION_SECRET;
  if (!s) return null;
  return new TextEncoder().encode(s);
}

async function sessionOk(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const key = secret();
  if (!key) return false;
  try { await jwtVerify(token, key); return true; } catch { return false; }
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const token = req.cookies.get(SESSION_COOKIE)?.value;

  if (pathname.startsWith("/app")) {
    if (!(await sessionOk(token))) {
      // No redirect loop — send them to landing with a hash that the
      // client picks up to auto-open the auth modal.
      const landing = new URL("/", req.url);
      landing.hash = "signin";
      return NextResponse.redirect(landing);
    }
    return NextResponse.next();
  }

  if (pathname === "/api/chat") {
    if (!(await sessionOk(token))) {
      return NextResponse.json({ error: "unauth" }, { status: 401 });
    }
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/app/:path*", "/api/chat"],
};
