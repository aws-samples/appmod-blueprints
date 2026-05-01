// /api/auth/me — return {sub, email} for the current session, or 401.
// Used by /app/page.tsx to greet the user.

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const s = await verifySession(token);
  if (!s) return NextResponse.json({ error: "unauth" }, { status: 401 });
  return NextResponse.json({ sub: s.sub, email: s.email });
}
