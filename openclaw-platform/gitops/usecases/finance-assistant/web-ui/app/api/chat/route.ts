// /api/chat — SSE proxy to the in-cluster adapter or session-router.
//
// Auth: middleware.ts already verified the session cookie before we get
// here. We decode the session to extract the user's sub and forward it
// to the backend in an x-amzn-oidc-data-shaped header so the router can
// route to the per-user sandbox without ALB auth.

import { NextRequest } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

const LEGACY_URL  = process.env.LEGACY_ADAPTER_URL || "http://finance-sandbox.finance-assistant.svc.cluster.local:18790";
const ROUTER_URL  = process.env.ROUTER_URL || "http://finance-session-router.finance-assistant.svc.cluster.local:18790";
const USE_ROUTER  = process.env.USE_SESSION_ROUTER === "true";
const ADAPTER_URL = USE_ROUTER ? ROUTER_URL : LEGACY_URL;

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = await req.text();

  // Reconstruct an x-amzn-oidc-data shaped header: three dot-joined
  // base64 segments, middle segment = JSON claims. session-router only
  // parses the middle segment for `sub`, so the signature is irrelevant.
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const session = token ? await verifySession(token) : null;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (session) {
    const claims = Buffer.from(JSON.stringify({ sub: session.sub, email: session.email })).toString("base64url");
    headers["x-amzn-oidc-data"] = `app.${claims}.sig`;
  }

  const upstream = await fetch(`${ADAPTER_URL}/chat`, {
    method: "POST",
    headers,
    body,
    // Next.js undici has aggressive default socket timeouts that kill long
    // SSE streams from the kata sandbox (first-turn plugin install + LLM
    // can exceed 60s). Signal with a generous 15min timeout.
    signal: AbortSignal.timeout(900000),
    // @ts-expect-error node fetch
    duplex: "half",
  });

  // Manually pump bytes from upstream into a ReadableStream so Next's
  // default Response(body) wrapping does not abort on upstream close.
  // Swallow "terminated"/"other side closed" from the reader — the
  // adapter legitimately closes the connection when it writes [DONE].
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      if (!upstream.body) { controller.close(); return; }
      reader = upstream.body.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value) controller.enqueue(value);
        }
      } catch (e) {
        const msg = (e as Error).message || "";
        // Expected at end-of-stream from the adapter; don't surface.
        if (!/terminated|other side closed|AbortError/i.test(msg)) {
          console.error("[api/chat] upstream read error:", msg);
          try {
            controller.enqueue(new TextEncoder().encode(
              `data: ${JSON.stringify({ error: msg })}\n\ndata: [DONE]\n\n`
            ));
          } catch {}
        }
      } finally {
        try { controller.close(); } catch {}
        try { reader?.releaseLock(); } catch {}
      }
    },
    cancel() {
      // Client navigated away — cancel via reader (body is locked once
      // getReader() was called). Body-level cancel throws ERR_INVALID_STATE.
      try { reader?.cancel(); } catch {}
    },
  });

  return new Response(stream, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
