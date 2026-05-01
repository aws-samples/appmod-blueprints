import { NextRequest, NextResponse } from "next/server";
import { signUp } from "@/lib/cognito";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { email, password, name } = await req.json().catch(() => ({}));
  if (!email || !password) return NextResponse.json({ error: "email and password required" }, { status: 400 });
  const r = await signUp(email, password, name);
  if (r.kind === "ok") return NextResponse.json({ ok: true, destination: r.destination });
  return NextResponse.json({ error: r.message, code: r.code }, { status: 400 });
}
