import { NextRequest, NextResponse } from "next/server";
import { forgotPassword, confirmForgotPassword } from "@/lib/cognito";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Two phases on one endpoint, discriminated by whether `code`+`newPassword`
// are present. First call starts the reset (sends email); second call
// confirms it with the code + new password.
export async function POST(req: NextRequest) {
  const { email, code, newPassword } = await req.json().catch(() => ({}));
  if (!email) return NextResponse.json({ error: "email required" }, { status: 400 });

  if (!code) {
    const r = await forgotPassword(email);
    if (r.kind === "ok") return NextResponse.json({ ok: true });
    return NextResponse.json({ error: r.message, code: r.code }, { status: 400 });
  }

  if (!newPassword) return NextResponse.json({ error: "newPassword required with code" }, { status: 400 });
  const r = await confirmForgotPassword(email, code, newPassword);
  if (r.kind === "ok") return NextResponse.json({ ok: true });
  return NextResponse.json({ error: r.message, code: r.code }, { status: 400 });
}
