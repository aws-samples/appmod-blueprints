// session-router: one Sandbox + PVC per authenticated Cognito user.
//
// Flow per /chat request:
//  1. Read x-amzn-oidc-data (JWT injected by ALB Cognito auth) → sub claim
//  2. Hash sub → short stable id, used as the per-user suffix
//  3. Ensure per-user PVC, Sandbox, and Service exist (create lazily)
//  4. Wait for the Sandbox pod to be Ready (cold-start hidden from UI with
//     heartbeats on the SSE stream)
//  5. Proxy the /chat request to that user's finance-sandbox-<id>:18790
//  6. Touch last-seen annotation so the idle-reaper CronJob leaves it alone
//
// No secrets pass through this process. It holds no LiteLLM key, no
// Bedrock creds. Its only privileges are the narrow RBAC in k8s/rbac.yaml:
// CRUD on Sandbox, Service, PVC in the finance-assistant namespace.

const http = require("http");
const crypto = require("crypto");
const k8s = require("@kubernetes/client-node");

const PORT = parseInt(process.env.PORT || "18790", 10);
const NAMESPACE = process.env.NAMESPACE || "finance-assistant";
const SANDBOX_TEMPLATE = process.env.SANDBOX_TEMPLATE || "/etc/router/sandbox-template.json";
const SANDBOX_READY_TIMEOUT_MS = parseInt(process.env.SANDBOX_READY_TIMEOUT_MS || "60000", 10);
const IDLE_TTL_SECONDS = parseInt(process.env.IDLE_TTL_SECONDS || "1800", 10);
// Read-only mode: do NOT provision per-user sandboxes; proxy to the
// legacy shared sandbox. Phase-4 safety net — lets us smoke-test the
// router's SSE proxy path before flipping real user traffic to the
// per-user model.
const READ_ONLY = process.env.ROUTER_READ_ONLY === "true";
const LEGACY_BACKEND = process.env.LEGACY_BACKEND || "finance-sandbox.finance-assistant.svc.cluster.local";

// ALB verifies the Cognito JWT and signs x-amzn-oidc-data itself before
// forwarding. In front of this router must be the ALB Cognito auth chain
// — we rely on that upstream verification. If you relocate this behind a
// different gateway, add JWKS verification here.
function extractUserSub(req) {
  const oidc = req.headers["x-amzn-oidc-data"];
  if (!oidc) return null;
  const parts = oidc.split(".");
  if (parts.length < 2) return null;
  try {
    const payload = JSON.parse(Buffer.from(parts[1], "base64").toString("utf8"));
    return payload.sub || payload.email || null;
  } catch {
    return null;
  }
}

function userSuffix(sub) {
  // 10 hex chars = 40 bits, comfortable for label/name length (<=63) and
  // avoids collisions inside a single tenant pool.
  return crypto.createHash("sha256").update(sub).digest("hex").slice(0, 10);
}

const kc = new k8s.KubeConfig();
kc.loadFromDefault();
const coreApi = kc.makeApiClient(k8s.CoreV1Api);
const customApi = kc.makeApiClient(k8s.CustomObjectsApi);

const SANDBOX_GROUP = "agents.x-k8s.io";
const SANDBOX_VERSION = "v1alpha1";
const SANDBOX_PLURAL = "sandboxes";

let sandboxTemplate = null;
function loadTemplate() {
  if (sandboxTemplate) return sandboxTemplate;
  const fs = require("fs");
  sandboxTemplate = JSON.parse(fs.readFileSync(SANDBOX_TEMPLATE, "utf8"));
  return sandboxTemplate;
}

function renderForUser(suffix, sub) {
  const tpl = JSON.parse(JSON.stringify(loadTemplate()));
  const name = `finance-sandbox-${suffix}`;
  const pvcName = `finance-workspace-${suffix}`;

  // Sandbox
  tpl.sandbox.metadata.name = name;
  tpl.sandbox.metadata.namespace = NAMESPACE;
  tpl.sandbox.metadata.labels = {
    ...(tpl.sandbox.metadata.labels || {}),
    "finance.x-k8s.io/user-suffix": suffix,
    app: name,
  };
  tpl.sandbox.metadata.annotations = {
    ...(tpl.sandbox.metadata.annotations || {}),
    // Only the suffix is stored; sub itself never touches etcd.
    "finance.x-k8s.io/sub-hash": crypto.createHash("sha256").update(sub).digest("hex").slice(0, 16),
    "finance.x-k8s.io/last-seen": new Date().toISOString(),
  };
  tpl.sandbox.spec.podTemplate.metadata = tpl.sandbox.spec.podTemplate.metadata || {};
  tpl.sandbox.spec.podTemplate.metadata.labels = {
    ...(tpl.sandbox.spec.podTemplate.metadata.labels || {}),
    app: name,
    "finance.x-k8s.io/user-suffix": suffix,
  };
  // Swap the workspace volume from emptyDir → the user's PVC.
  const volumes = tpl.sandbox.spec.podTemplate.spec.volumes;
  const ws = volumes.find((v) => v.name === "workspace");
  if (ws) {
    delete ws.emptyDir;
    ws.persistentVolumeClaim = { claimName: pvcName };
  }

  // PVC
  tpl.pvc.metadata.name = pvcName;
  tpl.pvc.metadata.namespace = NAMESPACE;
  tpl.pvc.metadata.labels = {
    "finance.x-k8s.io/user-suffix": suffix,
  };

  // Service — selector on per-user label, so each user gets a dedicated
  // internal DNS name and one user's pod can't be matched by another's svc.
  tpl.service.metadata.name = name;
  tpl.service.metadata.namespace = NAMESPACE;
  tpl.service.metadata.labels = {
    "finance.x-k8s.io/user-suffix": suffix,
    app: name,
  };
  tpl.service.spec.selector = { app: name };

  return { name, pvcName, rendered: tpl };
}

// Retry transient k8s API errors. The kubernetes client raises plain
// Error("HTTP request failed") for ECONN/EAI/socket-closed — those are
// retriable. 404 / 409 / 422 are intentional flow-control and must pass
// through unchanged.
async function withRetry(label, fn, { attempts = 4, baseMs = 500 } = {}) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try { return await fn(); }
    catch (e) {
      const status = e?.response?.statusCode;
      if (status === 404 || status === 409 || status === 422) throw e;
      lastErr = e;
      const wait = baseMs * Math.pow(2, i);
      console.warn(`[router] ${label} failed (attempt ${i + 1}/${attempts}): ${e?.message || e}; retry in ${wait}ms`);
      await new Promise((r) => setTimeout(r, wait));
    }
  }
  throw lastErr;
}

async function ensureUserSandbox(suffix, sub) {
  const { name, pvcName, rendered } = renderForUser(suffix, sub);

  // PVC — created once and kept. The per-user workspace survives pod
  // restarts but is deleted when the user is de-provisioned.
  try {
    await withRetry("PVC get", () => coreApi.readNamespacedPersistentVolumeClaim(pvcName, NAMESPACE));
  } catch (e) {
    if (e?.response?.statusCode === 404) {
      await withRetry("PVC create", () => coreApi.createNamespacedPersistentVolumeClaim(NAMESPACE, rendered.pvc));
    } else { throw e; }
  }

  // Sandbox — created lazily. If present, patch last-seen so the reaper
  // keeps it.
  try {
    await withRetry("Sandbox get", () => customApi.getNamespacedCustomObject(
      SANDBOX_GROUP, SANDBOX_VERSION, NAMESPACE, SANDBOX_PLURAL, name,
    ));
    await withRetry("Sandbox patch", () => customApi.patchNamespacedCustomObject(
      SANDBOX_GROUP, SANDBOX_VERSION, NAMESPACE, SANDBOX_PLURAL, name,
      { metadata: { annotations: { "finance.x-k8s.io/last-seen": new Date().toISOString() } } },
      undefined, undefined, undefined,
      { headers: { "Content-Type": "application/merge-patch+json" } },
    ));
  } catch (e) {
    if (e?.response?.statusCode === 404) {
      await withRetry("Sandbox create", () => customApi.createNamespacedCustomObject(
        SANDBOX_GROUP, SANDBOX_VERSION, NAMESPACE, SANDBOX_PLURAL, rendered.sandbox,
      ));
    } else { throw e; }
  }

  // Service — so the sandbox gets a per-user DNS name.
  try {
    await withRetry("Service get", () => coreApi.readNamespacedService(name, NAMESPACE));
  } catch (e) {
    if (e?.response?.statusCode === 404) {
      await withRetry("Service create", () => coreApi.createNamespacedService(NAMESPACE, rendered.service));
    } else { throw e; }
  }

  return { name };
}

async function waitForPodReady(name, deadlineMs) {
  const started = Date.now();
  while (Date.now() - started < deadlineMs) {
    try {
      const pods = await coreApi.listNamespacedPod(
        NAMESPACE, undefined, undefined, undefined, undefined,
        `app=${name}`,
      );
      const pod = pods.body.items[0];
      const ready = pod?.status?.conditions?.find((c) => c.type === "Ready");
      if (ready?.status === "True") return true;
    } catch {}
    await new Promise((r) => setTimeout(r, 750));
  }
  return false;
}

function sseWrite(res, data) { res.write(`data: ${JSON.stringify(data)}\n\n`); }

// Per-suffix prime-in-flight map + last-primed-at cache. openclaw's
// adapter spawns a fresh agent subprocess per /chat and cannot tolerate
// two concurrent runs against the same sandbox — the second exits 1.
// So we dedupe: concurrent warmups for the same user share one promise,
// and the user's real /chat await the same promise before proxying.
const inflightPrime = new Map();      // suffix -> Promise
const lastPrimedAt = new Map();       // suffix -> ms epoch
const PRIME_TTL_MS = 60_000;          // skip re-prime if <60s since last

function runPrime(sandboxName, suffix) {
  const host = `${sandboxName}.${NAMESPACE}.svc.cluster.local`;
  const body = JSON.stringify({ message: "ok", sessionId: `prime-${suffix}` });
  return new Promise((resolve) => {
    const req = http.request(
      { host, port: 18790, path: "/chat", method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } },
      (r) => { r.on("data", () => {}); r.on("end", resolve); r.on("error", resolve); },
    );
    req.on("error", resolve);
    req.setTimeout(120000, () => { try { req.destroy(); } catch {} resolve(); });
    req.write(body); req.end();
  });
}

// Fire a throwaway chat at the user's adapter so the gateway pays the
// per-session init tax (runtime-plugins, model-resolution, auth) before
// the user asks their real first question. Deduped per-suffix so
// concurrent warmups don't double-fire and crash the adapter.
async function primeAgent(sandboxName, suffix) {
  const lastAt = lastPrimedAt.get(suffix) || 0;
  if (Date.now() - lastAt < PRIME_TTL_MS) return; // recently primed, skip
  let p = inflightPrime.get(suffix);
  if (p) { await p; return; }
  p = runPrime(sandboxName, suffix)
    .finally(() => { inflightPrime.delete(suffix); lastPrimedAt.set(suffix, Date.now()); });
  inflightPrime.set(suffix, p);
  await p;
}

// Await any in-flight prime for this suffix before proxying user chat.
// Returning early if nothing pending keeps the hot path cheap.
async function waitForNoPrime(suffix) {
  const p = inflightPrime.get(suffix);
  if (p) await p;
}

async function proxyChat(req, res, backendHost, bodyBuf) {
  return new Promise((resolve) => {
    // Caller already sent writeHead for the SSE stream and wrote at
    // least one status frame, so we do NOT touch headers here. We also
    // take the body as an argument because the outer handler has
    // already consumed the request stream — reading req again yields
    // nothing and the adapter hangs waiting for a body.
    const body = bodyBuf;
    const proxy = http.request(
      {
        host: backendHost, port: 18790, path: "/chat", method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
      },
      (upstream) => {
        upstream.on("data", (chunk) => { try { res.write(chunk); } catch {} });
        upstream.on("end", () => { try { res.end(); } catch {} resolve(); });
        upstream.on("error", () => { try { res.end(); } catch {} resolve(); });
      },
    );
    proxy.on("error", (err) => {
      try {
        sseWrite(res, { error: `upstream unavailable: ${err.code || err.message}` });
        res.write("data: [DONE]\n\n"); res.end();
      } catch {}
      resolve();
    });
    proxy.write(body); proxy.end();
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/healthz") {
    res.writeHead(200); return res.end("ok\n");
  }

  // /warmup — idempotent "ensure sandbox is provisioned and ready" for
  // this authenticated user. Called from the UI sign-in path so the pod
  // is up by the time the user asks their first question. No proxy to
  // the adapter, no chat body required. Returns JSON status.
  if (req.method === "POST" && req.url === "/warmup") {
    const sub = extractUserSub(req);
    if (!sub) {
      res.writeHead(401, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ error: "no authenticated user" }));
    }
    if (READ_ONLY) {
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ status: "skipped", reason: "router in read-only mode" }));
    }
    const suffix = userSuffix(sub);
    try {
      const { name } = await ensureUserSandbox(suffix, sub);
      const ready = await waitForPodReady(name, SANDBOX_READY_TIMEOUT_MS);
      if (!ready) {
        res.writeHead(504, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ status: "timeout", sandbox: name }));
      }
      // Pod is ready. We deliberately DO NOT prime the agent runtime
      // here — priming spawns a subprocess in the adapter that takes
      // ~18s and blocks any user chat that arrives during that window.
      // For realistic flows (user types within 30s of login), priming
      // makes first-chat latency WORSE by forcing the user to wait for
      // the prime + their own chat sequentially. Better to let the
      // user's real first question be the one that pays the init cost.
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ status: "ready", sandbox: name }));
    } catch (e) {
      const detail = e?.message || String(e);
      console.error("[router/warmup]", detail);
      const friendly = /HTTP request failed|ECONN|ETIMEDOUT|EAI_AGAIN/i.test(detail)
        ? "Could not reach your workspace — please retry in a moment."
        : `Could not start your session: ${detail}`;
      res.writeHead(502, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ error: friendly }));
    }
  }

  if (req.method !== "POST" || req.url !== "/chat") {
    res.writeHead(404); return res.end();
  }

  // Buffer the request body up-front so both extractUserSub() and the
  // downstream proxy can use it. http.IncomingMessage is a one-shot
  // readable — reading it twice returns nothing.
  const bodyChunks = [];
  for await (const chunk of req) bodyChunks.push(chunk);
  const bodyBuf = Buffer.concat(bodyChunks);

  // Phase-4 smoke test mode: pass-through to the legacy shared sandbox
  // without provisioning anything.
  if (READ_ONLY) {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    });
    await proxyChat(req, res, LEGACY_BACKEND, bodyBuf);
    return;
  }

  const sub = extractUserSub(req);
  if (!sub) {
    res.writeHead(401, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "no authenticated user" }));
  }

  const suffix = userSuffix(sub);
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
  });
  const heartbeat = setInterval(() => { try { res.write(": ping\n\n"); } catch {} }, 10000);

  try {
    sseWrite(res, { status: "provisioning" });
    const { name } = await ensureUserSandbox(suffix, sub);
    const ready = await waitForPodReady(name, SANDBOX_READY_TIMEOUT_MS);
    if (!ready) {
      clearInterval(heartbeat);
      sseWrite(res, { error: "sandbox not ready within timeout" });
      res.write("data: [DONE]\n\n"); return res.end();
    }
    // If a prime is running right now (warmup fired + user typed fast),
    // await it so we don't spawn two concurrent openclaw runs against
    // the same adapter — it can't handle that and exits 1.
    await waitForNoPrime(suffix);
    sseWrite(res, { status: "ready" });
    clearInterval(heartbeat);
    const backend = `${name}.${NAMESPACE}.svc.cluster.local`;
    await proxyChat(req, res, backend, bodyBuf);
  } catch (e) {
    clearInterval(heartbeat);
    const detail = e?.message || String(e);
    console.error("[router]", detail);
    // Friendlier message — the raw k8s client error "HTTP request failed"
    // is useless to the user. Map known cases.
    const friendly = /HTTP request failed|ECONN|ETIMEDOUT|EAI_AGAIN/i.test(detail)
      ? "Could not reach your workspace — please retry in a moment."
      : `Could not start your session: ${detail}`;
    try {
      sseWrite(res, { error: friendly });
      res.write("data: [DONE]\n\n"); res.end();
    } catch {}
  }
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[router] listening on :${PORT} (ns=${NAMESPACE}, idle_ttl=${IDLE_TTL_SECONDS}s)`);
});
