import { NextRequest, NextResponse } from "next/server";
import { respondMfa } from "@/lib/cognito";
import { setSessionCookie } from "@/lib/set-session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { email, session, code } = await req.json().catch(() => ({}));
  if (!email || !session || !code) return NextResponse.json({ error: "email, session, code required" }, { status: 400 });
  const r = await respondMfa(email, session, code);
  if (r.kind === "ok") {
    const res = NextResponse.json({ ok: true, email: r.email });
    return setSessionCookie(res, { sub: r.sub, email: r.email, idToken: r.idToken, refreshToken: r.refreshToken });
  }
  return NextResponse.json({ error: r.kind === "error" ? r.message : "MFA failed", code: r.kind === "error" ? r.code : "" }, { status: 401 });
}
