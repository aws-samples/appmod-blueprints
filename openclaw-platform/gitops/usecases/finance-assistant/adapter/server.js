// Adapter sidecar: translates OpenAI-style /chat/completions SSE
// into openclaw `agent --local` CLI calls. Runs inside the sandbox pod,
// next to the openclaw gateway container, in the same Kata VM.
//
// Endpoints:
//   GET  /healthz                 -> liveness
//   POST /chat  {message, sessionId}  -> SSE stream of the reply text
//
// System prompt lives at /etc/openclaw/system-prompt.md and is
// prepended to the user message on the first turn per session.

// Redact first thing — catches every subsequent console.log/error that
// might touch a secret-shaped string. File-mounted secrets (below) are
// the primary defense; this is defense-in-depth.
require("./log-redact").install();

const http = require("http");
const fs = require("fs");
const { spawn } = require("child_process");

const PORT = parseInt(process.env.PORT || "18790", 10);
const OPENCLAW_CMD = process.env.OPENCLAW_CMD || "openclaw";
const rawArgs = process.env.OPENCLAW_ARGS || "";
const OPENCLAW_ARGS = rawArgs.trim() ? rawArgs.trim().split(/\s+/) : [];
// 15 min. Cold-start on a fresh per-user sandbox installs openclaw's
// bundled plugins (amazon-bedrock SDK, acpx, etc.) before the first
// response; that can take 60-120s on top of normal LLM time. Short
// timeouts truncate the response and make the UI look frozen.
const DEFAULT_TIMEOUT_MS = parseInt(process.env.ADAPTER_TIMEOUT_MS || "900000", 10);

// Secrets are mounted as tmpfs files at /var/run/openclaw/*.
// We read them into locals at startup, then drop the env var (if any)
// so a downstream `env` dump cannot leak the value. The openclaw CLI
// still reads its config from /home/node/.openclaw/openclaw.json where
// the gateway container has already substituted these values in.
function readSecretFile(path) {
  try { return fs.readFileSync(path, "utf8").trim(); } catch { return ""; }
}
const LITELLM_API_KEY = readSecretFile("/var/run/openclaw/litellm-api-key") || process.env.LITELLM_API_KEY || "";
const GATEWAY_AUTH_TOKEN = readSecretFile("/var/run/openclaw/gateway-auth-token") || process.env.GATEWAY_AUTH_TOKEN || "";
// Strip from env so child processes can't inherit them.
delete process.env.LITELLM_API_KEY;
delete process.env.GATEWAY_AUTH_TOKEN;

// System prompt is mounted at /etc/openclaw/system-prompt.md and copied to
// /workspace/BOOT.md by the openclaw container; the boot-md hook loads it
// into the gateway once per gateway lifetime so we do not re-prepend it.
const primedSessions = new Set();

function runOpenclaw(sessionId, message) {
  return new Promise((resolve, reject) => {
    // No --local: call the already-warm gateway instead of cold-starting
    // a fresh agent process per turn. Cuts ~15s off every response.
    const args = [
      ...OPENCLAW_ARGS,
      "agent",
      "--session-id", sessionId,
      "--thinking", "off",
      "--json",
      "-m", message,
    ];
    const child = spawn(OPENCLAW_CMD, args, {
      // Minimal env: only what the openclaw CLI actually needs. Secrets
      // are deliberately excluded — the CLI reads them from its config
      // file the gateway container wrote.
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        NODE_ENV: process.env.NODE_ENV || "production",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`openclaw timeout after ${DEFAULT_TIMEOUT_MS}ms`));
    }, DEFAULT_TIMEOUT_MS);

    child.stdout.on("data", (d) => { stdout += d.toString(); });
    child.stderr.on("data", (d) => { stderr += d.toString(); });
    child.on("close", (code) => {
      clearTimeout(timer);
      const candidates = [stdout, stderr];
      for (const src of candidates) {
        const jsonStart = src.indexOf("{\n");
        if (jsonStart < 0) continue;
        try {
          const parsed = JSON.parse(src.slice(jsonStart));
          const payloads = parsed?.result?.payloads ?? parsed?.payloads;
          if (!payloads) continue;
          const text = payloads?.[0]?.text ?? "";
          const stopReason = parsed?.result?.meta?.stopReason
            ?? parsed?.meta?.stopReason
            ?? parsed?.status
            ?? "unknown";
          return resolve({ text, stopReason, parsed });
        } catch { continue; }
      }
      console.error(`[adapter] openclaw exit ${code}`);
      console.error(`[adapter] stdout(${stdout.length}):`, stdout.slice(0, 500));
      console.error(`[adapter] stderr(${stderr.length}):`, stderr.slice(0, 500));
      reject(new Error(`openclaw exit ${code}; stdout=${stdout.length}B stderr=${stderr.length}B`));
    });
  });
}

function sseWrite(res, data) {
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

async function streamReplyAsSse(res, text) {
  // openclaw currently returns the whole reply synchronously, so there is
  // no token stream to forward. Emit the full text as one SSE delta — the
  // previous code chopped it into 6-char chunks with 12ms sleeps between
  // them, which added ~2s of pointless latency *after* the model was done.
  // True per-token streaming is a follow-up (needs the openclaw WS client).
  sseWrite(res, { delta: text });
  sseWrite(res, { done: true });
  res.write("data: [DONE]\n\n");
  res.end();
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain" });
    return res.end("ok\n");
  }

  if (req.method === "POST" && req.url === "/chat") {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", async () => {
      let heartbeat;
      try {
        const { message, sessionId = "web" } = JSON.parse(body || "{}");
        if (!message || typeof message !== "string") {
          res.writeHead(400, { "Content-Type": "application/json" });
          return res.end(JSON.stringify({ error: "message required" }));
        }

        let payload = message;
        // System prompt is loaded by the boot-md hook at gateway startup
        // (from /workspace/BOOT.md). Do not prepend per turn.

        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          "Connection": "keep-alive",
          "X-Accel-Buffering": "no",
        });
        sseWrite(res, { status: "thinking" });
        heartbeat = setInterval(() => {
          try { res.write(": ping\n\n"); } catch {}
        }, 10000);

        const { text, stopReason } = await runOpenclaw(sessionId, payload);
        clearInterval(heartbeat);
        if (stopReason === "error" || !text) {
          sseWrite(res, { error: text || "agent error", stopReason });
          res.write("data: [DONE]\n\n");
          return res.end();
        }
        await streamReplyAsSse(res, text);
      } catch (e) {
        clearInterval(heartbeat);
        console.error("[adapter] error:", e.message);
        try {
          sseWrite(res, { error: e.message });
          res.write("data: [DONE]\n\n");
          res.end();
        } catch {}
      }
    });
    return;
  }

  res.writeHead(404);
  res.end();
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[adapter] listening on :${PORT}`);
});
