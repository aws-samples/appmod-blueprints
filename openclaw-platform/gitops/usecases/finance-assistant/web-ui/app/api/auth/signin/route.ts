import { NextRequest, NextResponse } from "next/server";
import { signIn } from "@/lib/cognito";
import { setSessionCookie } from "@/lib/set-session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { email, password } = await req.json().catch(() => ({}));
  if (!email || !password) return NextResponse.json({ error: "email and password required" }, { status: 400 });

  const r = await signIn(email, password);
  if (r.kind === "ok") {
    const res = NextResponse.json({ ok: true, email: r.email });
    return setSessionCookie(res, { sub: r.sub, email: r.email, idToken: r.idToken, refreshToken: r.refreshToken });
  }
  if (r.kind === "mfa") return NextResponse.json({ challenge: "mfa", session: r.session, email: r.email });
  if (r.kind === "new_password") return NextResponse.json({ challenge: "new_password", session: r.session, email: r.email });
  return NextResponse.json({ error: r.message, code: r.code }, { status: 401 });
}
