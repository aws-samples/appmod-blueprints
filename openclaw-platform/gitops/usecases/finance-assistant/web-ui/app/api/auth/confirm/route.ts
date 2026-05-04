import { NextRequest, NextResponse } from "next/server";
import { confirmSignUp, signIn } from "@/lib/cognito";
import { setSessionCookie } from "@/lib/set-session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// After a user enters the email verification code, confirm with Cognito
// and then immediately sign them in so they land on /app without a
// second password prompt. Password was collected during /signup and is
// replayed here — we ask the client to send it back.
export async function POST(req: NextRequest) {
  const { email, code, password } = await req.json().catch(() => ({}));
  if (!email || !code) return NextResponse.json({ error: "email and code required" }, { status: 400 });

  const confirm = await confirmSignUp(email, code);
  if (confirm.kind === "error") return NextResponse.json({ error: confirm.message, code: confirm.code }, { status: 400 });

  if (!password) return NextResponse.json({ ok: true });

  const r = await signIn(email, password);
  if (r.kind === "ok") {
    const res = NextResponse.json({ ok: true, email: r.email });
    return setSessionCookie(res, { sub: r.sub, email: r.email });
  }
  return NextResponse.json({ ok: true });
}
