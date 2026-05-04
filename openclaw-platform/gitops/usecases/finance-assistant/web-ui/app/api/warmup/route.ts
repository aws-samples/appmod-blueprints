// /api/warmup — kick the session-router to provision the user's
// per-user Kata sandbox before they ask their first question. Called
// fire-and-forget from the sign-in success handler so the pod is
// already up by the time /chat renders.
//
// Belt-and-suspenders @amazon.com gate: Cognito's pre-signup Lambda
// already blocks non-amazon emails from signing up, but if a forged
// session cookie somehow reaches here we refuse to spin up a kata pod.

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

const ROUTER_URL = process.env.ROUTER_URL || "http://finance-session-router.finance-assistant.svc.cluster.local:18790";
const ALLOWED_DOMAIN = "amazon.com";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const session = token ? await verifySession(token) : null;
  if (!session) return NextResponse.json({ error: "unauth" }, { status: 401 });

  const email = (session.email || "").toLowerCase();
  const domain = email.includes("@") ? email.split("@").pop() : "";
  if (domain !== ALLOWED_DOMAIN) {
    console.warn(`[warmup] denied: sub=${session.sub} email-domain=${domain}`);
    return NextResponse.json({ error: "domain-not-allowed" }, { status: 403 });
  }

  // Reconstruct x-amzn-oidc-data the same way /api/chat does.
  const claims = Buffer.from(JSON.stringify({ sub: session.sub, email: session.email })).toString("base64url");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "x-amzn-oidc-data": `app.${claims}.sig`,
  };

  try {
    // Generous timeout — a first-time provision includes Karpenter
    // scheduling + image pull + gateway boot. This endpoint is called
    // fire-and-forget from the browser, so a long wait doesn't block
    // the user's UI; it only extends the server fetch.
    const r = await fetch(`${ROUTER_URL}/warmup`, {
      method: "POST",
      headers,
      body: "{}",
      signal: AbortSignal.timeout(300000),
    });
    const text = await r.text().catch(() => "");
    return new NextResponse(text || JSON.stringify({ status: r.ok ? "ready" : "error" }), {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error("[warmup] fetch failed:", (e as Error).message);
    return NextResponse.json({ error: "router-unreachable" }, { status: 502 });
  }
}
