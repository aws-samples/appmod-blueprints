"use client";

// AuthModal — Stripe-style overlay. Opens on top of the blurred landing
// page. Tabs for Sign in / Sign up. Smooth transitions between states
// (credentials → MFA → confirm email → reset password).
//
// Talks to /api/auth/* which in turn talks to Cognito. No client-side
// AWS SDK, no tokens in localStorage — session cookie is HttpOnly and
// set by the server on success.

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Mail, Lock, User, ArrowRight, Loader2, CheckCircle2, KeyRound } from "lucide-react";

type Tab = "signin" | "signup" | "forgot";
type Stage =
  | { k: "creds" }
  | { k: "mfa"; session: string }
  | { k: "confirm_email" }   // post-signup: enter the 6-digit code
  | { k: "forgot_code" }     // forgot password: enter code + new password
  | { k: "success"; to: string };

export default function AuthModal({ open, onClose, initialTab = "signin" }: {
  open: boolean; onClose: () => void; initialTab?: Tab;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [stage, setStage] = useState<Stage>({ k: "creds" });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTab(initialTab); setStage({ k: "creds" }); setErr(null); setCode(""); setNewPassword("");
      setTimeout(() => emailRef.current?.focus(), 200);
    }
  }, [open, initialTab]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function post(path: string, body: Record<string, unknown>) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, ...j };
  }

  // Fire-and-forget warmup so the per-user Kata sandbox is provisioned
  // in the background while we play the success animation and the
  // browser navigates to /chat. By the time the user types their first
  // question, the pod is usually up. Three fences against non-@amazon.com
  // provisioning: (1) Cognito pre-signup Lambda, (2) this client check,
  // (3) server-side /api/warmup domain check.
  function kickWarmup() {
    const domain = (email || "").toLowerCase().split("@").pop();
    if (domain !== "amazon.com") return;
    try {
      fetch("/api/warmup", { method: "POST", keepalive: true }).catch(() => {});
    } catch { /* fire-and-forget */ }
  }

  async function submitSignIn(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setLoading(true);
    const j = await post("/api/auth/signin", { email, password });
    setLoading(false);
    if (j.ok) { kickWarmup(); setStage({ k: "success", to: "/chat" }); setTimeout(() => { window.location.href = "/chat"; }, 600); return; }
    if (j.challenge === "mfa") { setStage({ k: "mfa", session: j.session }); return; }
    setErr(friendly(j));
  }

  async function submitSignUp(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setLoading(true);
    const j = await post("/api/auth/signup", { email, password, name });
    if (!j.ok) { setLoading(false); setErr(friendly(j)); return; }
    // Amazon-domain users are auto-confirmed by the pre-signup Lambda, so
    // try signing in immediately. Only show the "check your inbox" stage
    // when signin reports the account is still unconfirmed.
    const s = await post("/api/auth/signin", { email, password });
    setLoading(false);
    if (s.ok) { kickWarmup(); setStage({ k: "success", to: "/chat" }); setTimeout(() => { window.location.href = "/chat"; }, 600); return; }
    if (s.code === "UserNotConfirmedException") { setStage({ k: "confirm_email" }); return; }
    setErr(friendly(s));
  }

  async function submitConfirm(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setLoading(true);
    const j = await post("/api/auth/confirm", { email, code, password });
    setLoading(false);
    if (j.ok) { kickWarmup(); setStage({ k: "success", to: "/chat" }); setTimeout(() => { window.location.href = "/chat"; }, 600); return; }
    setErr(friendly(j));
  }

  async function submitMfa(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setLoading(true);
    const session = (stage.k === "mfa") ? stage.session : "";
    const j = await post("/api/auth/mfa", { email, session, code });
    setLoading(false);
    if (j.ok) { kickWarmup(); setStage({ k: "success", to: "/chat" }); setTimeout(() => { window.location.href = "/chat"; }, 600); return; }
    setErr(friendly(j));
  }

  async function submitForgotStart(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setLoading(true);
    const j = await post("/api/auth/forgot", { email });
    setLoading(false);
    if (j.ok) { setStage({ k: "forgot_code" }); return; }
    setErr(friendly(j));
  }

  async function submitForgotConfirm(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setLoading(true);
    const j = await post("/api/auth/forgot", { email, code, newPassword });
    setLoading(false);
    if (j.ok) {
      // Sign the user in with the new password for a smooth handoff.
      const s = await post("/api/auth/signin", { email, password: newPassword });
      if (s.ok) { setStage({ k: "success", to: "/chat" }); setTimeout(() => { window.location.href = "/chat"; }, 600); return; }
      setTab("signin"); setStage({ k: "creds" }); setPassword("");
      return;
    }
    setErr(friendly(j));
  }

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        key="auth-backdrop"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[100] flex items-center justify-center p-4"
        onClick={onClose}
      >
        <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-md"/>
        <motion.div
          key="auth-card"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 10, scale: 0.98 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          onClick={(e) => e.stopPropagation()}
          className="relative w-full max-w-md rounded-2xl border border-ink-800 bg-ink-950/95 shadow-2xl shadow-black/60 overflow-hidden"
        >
          {/* Top accent bar */}
          <div className="h-1 bg-gradient-to-r from-accent-400 via-accent-500 to-gold-500"/>

          <button onClick={onClose} className="absolute top-4 right-4 p-1.5 rounded-lg text-ink-400 hover:text-ink-100 hover:bg-ink-900/80 transition">
            <X size={16}/>
          </button>

          <div className="p-8">
            {/* Logo + title */}
            <div className="flex items-center gap-2.5 mb-7">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-accent-400 via-accent-500 to-gold-500 flex items-center justify-center text-ink-950 font-bold text-sm shadow-lg shadow-accent-500/30">
                F
              </div>
              <div>
                <div className="text-sm font-semibold text-ink-50">Finance Assistant</div>
                <div className="text-[11px] text-ink-500">Think about money clearly.</div>
              </div>
            </div>

            {/* Tabs — hidden once we leave credentials stage */}
            {stage.k === "creds" && tab !== "forgot" && (
              <div className="flex gap-1 mb-6 p-1 rounded-lg bg-ink-900 border border-ink-800">
                <TabBtn active={tab === "signin"} onClick={() => { setTab("signin"); setErr(null); }}>Sign in</TabBtn>
                <TabBtn active={tab === "signup"} onClick={() => { setTab("signup"); setErr(null); }}>Create account</TabBtn>
              </div>
            )}

            {err && (
              <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}
                className="mb-4 px-3 py-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300">
                {err}
              </motion.div>
            )}

            <AnimatePresence mode="wait">
              {/* ─── SUCCESS ─── */}
              {stage.k === "success" && (
                <motion.div key="success" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="py-4 text-center">
                  <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mx-auto mb-3">
                    <CheckCircle2 size={20} className="text-emerald-400"/>
                  </div>
                  <div className="text-sm font-medium text-ink-100">Signed in — taking you to the assistant…</div>
                </motion.div>
              )}

              {/* ─── CREDENTIALS: SIGN IN ─── */}
              {stage.k === "creds" && tab === "signin" && (
                <motion.form key="signin" onSubmit={submitSignIn}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <Field icon={<Mail size={14}/>} label="Email" type="email" value={email} setValue={setEmail} placeholder="you@company.com" inputRef={emailRef}/>
                  <Field icon={<Lock size={14}/>} label="Password" type="password" value={password} setValue={setPassword} placeholder="••••••••••••"/>
                  <div className="text-right -mt-2 mb-4">
                    <button type="button" onClick={() => { setTab("forgot"); setErr(null); }}
                      className="text-[11px] text-accent-400 hover:text-accent-300 font-medium">
                      Forgot password?
                    </button>
                  </div>
                  <SubmitBtn loading={loading}>Sign in <ArrowRight size={14}/></SubmitBtn>
                </motion.form>
              )}

              {/* ─── CREDENTIALS: SIGN UP ─── */}
              {stage.k === "creds" && tab === "signup" && (
                <motion.form key="signup" onSubmit={submitSignUp}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <Field icon={<User size={14}/>}  label="Name"      type="text"     value={name}     setValue={setName}     placeholder="Your name" inputRef={emailRef}/>
                  <Field icon={<Mail size={14}/>}  label="Email"     type="email"    value={email}    setValue={setEmail}    placeholder="you@company.com"/>
                  <Field icon={<Lock size={14}/>}  label="Password"  type="password" value={password} setValue={setPassword} placeholder="14+ chars with upper, lower, number, symbol"/>
                  <SubmitBtn loading={loading}>Create account <ArrowRight size={14}/></SubmitBtn>
                  <div className="text-[11px] text-ink-500 mt-4 leading-relaxed text-center">
                    By continuing you agree this is an educational tool — not financial advice.
                  </div>
                </motion.form>
              )}

              {/* ─── FORGOT: start ─── */}
              {stage.k === "creds" && tab === "forgot" && (
                <motion.form key="forgot-start" onSubmit={submitForgotStart}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="text-sm text-ink-300 mb-5 leading-relaxed">Enter your email and we&apos;ll send you a code to reset your password.</div>
                  <Field icon={<Mail size={14}/>} label="Email" type="email" value={email} setValue={setEmail} placeholder="you@company.com" inputRef={emailRef}/>
                  <SubmitBtn loading={loading}>Send reset code <ArrowRight size={14}/></SubmitBtn>
                  <button type="button" onClick={() => { setTab("signin"); setErr(null); }} className="mt-4 block mx-auto text-[12px] text-ink-400 hover:text-ink-200">← Back to sign in</button>
                </motion.form>
              )}

              {/* ─── FORGOT: code + new password ─── */}
              {stage.k === "forgot_code" && (
                <motion.form key="forgot-confirm" onSubmit={submitForgotConfirm}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="text-sm text-ink-300 mb-5 leading-relaxed">
                    We emailed a code to <span className="text-ink-100 font-medium">{email}</span>. Enter it below with a new password.
                  </div>
                  <Field icon={<KeyRound size={14}/>} label="Code"          type="text"     value={code}        setValue={setCode}        placeholder="123456"/>
                  <Field icon={<Lock size={14}/>}      label="New password"  type="password" value={newPassword} setValue={setNewPassword} placeholder="••••••••••••"/>
                  <SubmitBtn loading={loading}>Reset password <ArrowRight size={14}/></SubmitBtn>
                </motion.form>
              )}

              {/* ─── MFA ─── */}
              {stage.k === "mfa" && (
                <motion.form key="mfa" onSubmit={submitMfa}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="text-sm text-ink-300 mb-5 leading-relaxed">
                    Enter the code from your authenticator app.
                  </div>
                  <Field icon={<KeyRound size={14}/>} label="6-digit code" type="text" value={code} setValue={setCode} placeholder="123456" inputRef={emailRef}/>
                  <SubmitBtn loading={loading}>Verify <ArrowRight size={14}/></SubmitBtn>
                </motion.form>
              )}

              {/* ─── CONFIRM EMAIL (post signup) ─── */}
              {stage.k === "confirm_email" && (
                <motion.form key="confirm-email" onSubmit={submitConfirm}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="text-sm text-ink-300 mb-5 leading-relaxed">
                    Check your inbox — we sent a 6-digit code to <span className="text-ink-100 font-medium">{email}</span>.
                  </div>
                  <Field icon={<KeyRound size={14}/>} label="Verification code" type="text" value={code} setValue={setCode} placeholder="123456" inputRef={emailRef}/>
                  <SubmitBtn loading={loading}>Verify &amp; sign in <ArrowRight size={14}/></SubmitBtn>
                </motion.form>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button" onClick={onClick}
      className={`flex-1 px-3 py-2 rounded-md text-xs font-semibold transition ${
        active ? "bg-ink-950 text-ink-50 shadow-inner shadow-black/40" : "text-ink-400 hover:text-ink-200"
      }`}
    >
      {children}
    </button>
  );
}

function Field({ icon, label, type, value, setValue, placeholder, inputRef }: {
  icon: React.ReactNode; label: string; type: string;
  value: string; setValue: (v: string) => void; placeholder?: string;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <div className="mb-4">
      <label className="block text-[11px] uppercase tracking-wider text-ink-400 font-semibold mb-1.5">{label}</label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-500">{icon}</span>
        <input
          ref={inputRef}
          type={type} value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder}
          required
          autoComplete={type === "password" ? "current-password" : type === "email" ? "email" : "off"}
          className="w-full pl-10 pr-3 py-2.5 rounded-lg bg-ink-900 border border-ink-800 text-sm text-ink-50 placeholder:text-ink-600 focus:border-accent-500/60 focus:ring-2 focus:ring-accent-500/20 focus:outline-none transition"
        />
      </div>
    </div>
  );
}

function SubmitBtn({ loading, children }: { loading: boolean; children: React.ReactNode }) {
  return (
    <button type="submit" disabled={loading}
      className="btn-gradient w-full rounded-lg px-4 py-2.5 text-sm font-semibold flex items-center justify-center gap-2 shadow-lg shadow-accent-500/25 transition hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed">
      {loading ? <Loader2 size={14} className="animate-spin"/> : children}
    </button>
  );
}

function friendly(j: { error?: string; code?: string }): string {
  const code = j?.code || "";
  const msg = j?.error || "";
  if (code === "NotAuthorizedException")      return "Incorrect email or password.";
  if (code === "UserNotConfirmedException")   return "Your email isn't confirmed yet — check your inbox for the code.";
  if (code === "UsernameExistsException")     return "That email is already registered — try signing in.";
  if (code === "InvalidPasswordException")    return "Password doesn't meet requirements: 14+ chars with upper, lower, number, and symbol.";
  if (code === "CodeMismatchException")       return "That code doesn't match. Check the most recent email.";
  if (code === "ExpiredCodeException")        return "Code expired — request a new one.";
  if (code === "LimitExceededException")      return "Too many attempts. Wait a minute and try again.";
  if (code === "UserNotFoundException")       return "No account found for that email.";
  // Pre-signup Lambda rejects non-@amazon.com. Cognito wraps the error as
  // "PreSignUp failed with error <python exception>." so we don't parse
  // the wrapped string — just show the policy directly.
  if (code === "UserLambdaValidationException") {
    if (/amazon\.com/i.test(msg)) return "Signup is restricted to @amazon.com email addresses.";
    return "This email address isn't allowed to sign up.";
  }
  return msg || "Something went wrong. Try again.";
}
