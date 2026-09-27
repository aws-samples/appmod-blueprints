#!/usr/bin/env python3
"""
a2a-chat-ui — Keycloak-gated A2A chat front-end for an OAP Strands agent.

Flow: the browser logs in with Keycloak username/password (user1/…). The backend
does an OIDC Resource-Owner-Password (direct grant) to Keycloak, validates the
token, and sets a short signed session cookie. Only then may the browser chat.
The chat itself is proxied server-side to the agent's in-cluster A2A endpoint
(no CORS, no token to the browser). Multi-turn via a stable contextId per tab.

Env:
  AGENT_A2A_URL       agent A2A JSON-RPC URL (default: in-cluster stable svc)
  KEYCLOAK_TOKEN_URL  Keycloak token endpoint (default: public CloudFront Keycloak)
  KEYCLOAK_CLIENT_ID  public client with Direct Access Grants (default peeks-agent-chat)
  KEYCLOAK_CLIENT_SECRET  optional (confidential client)
  SESSION_SECRET      HMAC key for the session cookie (default: random per pod)
  SESSION_TTL         seconds (default 3600)
  PORT                listen port (default 8080)
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

AGENT_A2A_URL = os.getenv("AGENT_A2A_URL", "http://agent-stable.default.svc.cluster.local:8083/")
KEYCLOAK_TOKEN_URL = os.getenv(
    "KEYCLOAK_TOKEN_URL",
    "https://d2pefdj59hxapj.cloudfront.net/keycloak/realms/platform/protocol/openid-connect/token",
)
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "a2a-chat")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32)).encode()
SESSION_TTL = int(os.getenv("SESSION_TTL", "3600"))
PORT = int(os.getenv("PORT", "8080"))
COOKIE = os.getenv("SESSION_COOKIE", "a2a_chat_session")

APP_TITLE = os.getenv("APP_TITLE", "A2A Agent Chat")
app = FastAPI(title=APP_TITLE)


# ── signed session cookie (stdlib HMAC, no extra deps) ────────────────────
def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def _verify(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expect = hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None


def _session(request: Request) -> dict | None:
    tok = request.cookies.get(COOKIE)
    return _verify(tok) if tok else None


@app.get("/health")
async def health():
    return {"status": "healthy", "agent_url": AGENT_A2A_URL, "keycloak": KEYCLOAK_TOKEN_URL}


@app.get("/config")
async def config():
    return {
        "title": APP_TITLE,
        "agentLabel": os.getenv("AGENT_LABEL", "agent"),
        "intro": os.getenv("APP_INTRO", "Ask the agent. It reasons and can run read-only inspection, then proposes GitOps fixes."),
    }


@app.get("/me")
async def me(request: Request):
    s = _session(request)
    return {"authenticated": bool(s), "username": s.get("user") if s else None}


@app.post("/login")
async def login(request: Request, response: Response):
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)

    data = {
        "grant_type": "password",
        "client_id": KEYCLOAK_CLIENT_ID,
        "username": username,
        "password": password,
        "scope": "openid",
    }
    if KEYCLOAK_CLIENT_SECRET:
        data["client_secret"] = KEYCLOAK_CLIENT_SECRET
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(KEYCLOAK_TOKEN_URL, data=data)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"keycloak unreachable: {exc}"}, status_code=502)
    if r.status_code != 200:
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

    cookie = _sign({"user": username, "exp": int(time.time()) + SESSION_TTL})
    resp = JSONResponse({"authenticated": True, "username": username})
    secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    resp.set_cookie(COOKIE, cookie, httponly=True, secure=secure, samesite="lax", max_age=SESSION_TTL, path="/")
    return resp


@app.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ── async job store ───────────────────────────────────────────────────────
# A recon can take several minutes; a synchronous /api/send would be cut by the
# CloudFront (~30s) / ALB (60s idle) edge timeout, returning an HTML 504 page
# that the browser's res.json() cannot parse ("Unexpected token '<'"). Instead
# /api/send spawns a background task and returns a jobId immediately; the
# browser polls /api/result (fast GETs, never hit the edge timeout).
_JOBS: dict = {}          # jobId -> {"status","response"|"error","contextId","ts"}
_JOB_TTL = 1800           # keep finished jobs 30 min
_AGENT_TIMEOUT = 600      # allow long multi-tool recons server-side


async def _run_agent_job(job_id: str, text: str, context_id: str) -> None:
    rpc = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": str(uuid.uuid4()),
            "contextId": context_id,
        }},
    }
    try:
        async with httpx.AsyncClient(timeout=_AGENT_TIMEOUT) as client:
            r = await client.post(AGENT_A2A_URL, json=rpc)
            r.raise_for_status()
            data = r.json()
        _JOBS[job_id] = {"status": "done", "response": _extract_text(data),
                         "contextId": context_id, "ts": time.time()}
    except Exception as exc:  # noqa: BLE001
        _JOBS[job_id] = {"status": "error", "error": str(exc),
                         "contextId": context_id, "ts": time.time()}


def _prune_jobs() -> None:
    now = time.time()
    for k in [k for k, v in list(_JOBS.items()) if now - v.get("ts", now) > _JOB_TTL]:
        _JOBS.pop(k, None)


@app.post("/api/send")
async def send(request: Request):
    if not _session(request):
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    body = await request.json()
    text = (body.get("message") or "").strip()
    context_id = body.get("contextId") or str(uuid.uuid4())
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    _prune_jobs()
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {"status": "pending", "contextId": context_id, "ts": time.time()}
    asyncio.create_task(_run_agent_job(job_id, text, context_id))
    return {"jobId": job_id, "contextId": context_id, "status": "pending"}


@app.get("/api/result")
async def result(request: Request, jobId: str = ""):
    if not _session(request):
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    job = _JOBS.get(jobId)
    if not job:
        return {"status": "unknown"}
    job["ts"] = time.time()  # keep alive while the browser is polling
    if job["status"] == "done":
        return {"status": "done", "response": job["response"], "contextId": job["contextId"]}
    if job["status"] == "error":
        return {"status": "error", "error": job["error"], "contextId": job["contextId"]}
    return {"status": "pending", "contextId": job["contextId"]}


@app.post("/api/suggest")
async def suggest(request: Request):
    """Return 3 short, contextual follow-up prompts based on the last Q/A.
    Uses a FRESH contextId so it never pollutes the visible conversation."""
    if not _session(request):
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    import re
    body = await request.json()
    q = (body.get("question") or "").strip()[:600]
    a = (body.get("answer") or "").strip()[:2000]
    prompt = (
        f'A user asked: "{q}"\nYou answered:\n{a}\n\n'
        "Propose exactly 3 concise follow-up prompts (each 3-7 words, imperative, "
        "specific to what you just said) the user might send next to go deeper. "
        "Return ONLY a JSON array of 3 strings, no prose, no numbering."
    )
    rpc = {
        "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "message/send",
        "params": {"message": {
            "role": "user",
            "parts": [{"kind": "text", "text": prompt}],
            "messageId": str(uuid.uuid4()),
            "contextId": str(uuid.uuid4()),
        }},
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(AGENT_A2A_URL, json=rpc)
            r.raise_for_status()
            text = _extract_text(r.json())
    except Exception:  # noqa: BLE001
        return {"suggestions": []}
    sug = []
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            sug = [str(x).strip() for x in json.loads(m.group(0)) if str(x).strip()][:3]
        except Exception:  # noqa: BLE001
            sug = []
    if not sug:  # fallback: bullet/line extraction
        for line in text.splitlines():
            c = line.strip().lstrip("-*0123456789.\u2022 ").strip(' "')
            if 2 <= len(c.split()) <= 9:
                sug.append(c)
            if len(sug) == 3:
                break
    return {"suggestions": sug[:3]}


def _extract_text(data: dict) -> str:
    result = data.get("result", data)
    parts = (result.get("message") or {}).get("parts") if isinstance(result, dict) else None
    if not parts and isinstance(result, dict):
        parts = result.get("parts")
    if not parts and isinstance(result, dict):
        for a in result.get("artifacts", []) or []:
            if a.get("parts"):
                parts = a["parts"]
                break
    if parts:
        # A2A streams the answer as many token-fragment parts; concatenate them
        # verbatim (the model's own newlines live inside individual parts).
        texts = [p.get("text", "") for p in parts if p.get("text")]
        return "".join(texts)
    return str(result)


app.mount("/", StaticFiles(directory="static", html=True), name="static")
