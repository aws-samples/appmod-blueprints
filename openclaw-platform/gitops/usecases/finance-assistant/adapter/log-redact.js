// log-redact: tiny stdout/stderr filter shared by adapter + session-router.
// Purpose: belt-and-braces pass over everything we write, so an unexpected
// code path that dumps env/context doesn't put a live token in CloudWatch.
//
// The real fix is not putting secrets in env at all (see PR4 changes to
// sandbox.yaml + adapter). This is the second line of defense.
//
// Usage:
//   require("./log-redact").install();
// at the top of any entrypoint. Wraps process.stdout.write /
// process.stderr.write so even console.log goes through the filter.

"use strict";

const PATTERNS = [
  // LiteLLM virtual key shape: sk- + 20-40 url-safe chars
  { re: /\bsk-[A-Za-z0-9_-]{16,64}\b/g, replace: "sk-[REDACTED]" },
  // AWS access key id
  { re: /\b(AKIA|ASIA)[A-Z0-9]{16}\b/g, replace: "[AWS_KEY_REDACTED]" },
  // AWS secret-key-shaped value (40 base64url chars). False-positive risk is
  // real, but we accept it on stdout — real data in stdout is always a bug.
  { re: /\b[A-Za-z0-9/+=]{40}\b/g, replace: "[40CHAR_REDACTED]" },
  // JWT (3 base64url segments dot-joined, first segment starts with eyJ)
  { re: /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, replace: "[JWT_REDACTED]" },
  // 32+ hex char strings — catches the existing GATEWAY_AUTH_TOKEN shape
  { re: /\b[a-f0-9]{48,}\b/g, replace: "[HEX_TOKEN_REDACTED]" },
];

function redact(chunk) {
  if (chunk == null) return chunk;
  const s = typeof chunk === "string" ? chunk : chunk.toString("utf8");
  let out = s;
  for (const { re, replace } of PATTERNS) out = out.replace(re, replace);
  return typeof chunk === "string" ? out : Buffer.from(out, "utf8");
}

function install() {
  for (const stream of [process.stdout, process.stderr]) {
    const orig = stream.write.bind(stream);
    stream.write = (chunk, enc, cb) => orig(redact(chunk), enc, cb);
  }
}

module.exports = { install, redact };
