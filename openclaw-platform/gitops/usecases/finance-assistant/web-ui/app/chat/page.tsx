"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Shield, Sparkles, Cpu, ShieldCheck, Lock, TrendingUp, Home, GraduationCap, Target, Menu, X, LogOut, User, Plus } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/cn";

type Msg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;            // epoch ms
  responseMs?: number;          // assistant-only: end-to-end response time
};

const SUGGESTIONS = [
  { icon: TrendingUp, title: "Savings framework", body: "I earn $250k combined, max 401ks, have $3k/mo extra. How should I think about splitting it between a 529, taxable brokerage, backdoor Roth, and HSA?" },
  { icon: Home,       title: "Rent vs buy",        body: "Help me think through the rent vs buy math for a $900k home in the Bay Area, putting 20% down, with a 7% mortgage. What variables matter most?" },
  { icon: GraduationCap, title: "529 vs UTMA",     body: "What's the real tradeoff between a 529 and a UTMA for my kid's future education? I'm not sure they'll go to college." },
  { icon: Target, title: "Retirement math",        body: "I want to retire at 55 with $2M in today's dollars. I'm 38 with $400k saved. Walk me through what assumptions matter and how to stress-test my plan." },
];

// Client-only session id resolution — pulling from localStorage at module
// scope yields different values on the Next SSR pass vs hydration, which
// trips React hydration error #418. Resolve on mount instead.
function useSessionId(): string {
  const [id, setId] = useState<string>("web");
  useEffect(() => {
    try {
      const existing = localStorage.getItem("finassist.session");
      if (existing) { setId(existing); return; }
      const fresh = `web-${Date.now().toString(36)}`;
      localStorage.setItem("finassist.session", fresh);
      setId(fresh);
    } catch { /* no localStorage — leave as "web" */ }
  }, []);
  return id;
}

// Per-user history key. Keyed on Cognito sub so different accounts on the
// same browser don't cross-contaminate. Falls back to a shared key
// pre-login; gets migrated after /api/auth/me resolves.
function historyKey(sub?: string) {
  return sub ? `finassist.history.${sub}` : `finassist.history`;
}

function loadHistory(sub?: string): Msg[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(historyKey(sub));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Msg[];
    if (!Array.isArray(parsed)) return [];
    // Trim to last 200 messages so localStorage doesn't blow past 5MB.
    return parsed.slice(-200);
  } catch { return []; }
}

function saveHistory(sub: string | undefined, msgs: Msg[]) {
  if (typeof window === "undefined") return;
  try { localStorage.setItem(historyKey(sub), JSON.stringify(msgs.slice(-200))); } catch {}
}

function fmtTime(ms: number): string {
  const d = new Date(ms);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const hh = d.getHours() % 12 || 12;
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ampm = d.getHours() < 12 ? "AM" : "PM";
  if (sameDay) return `${hh}:${mm} ${ampm}`;
  const mon = d.toLocaleString(undefined, { month: "short" });
  return `${mon} ${d.getDate()} · ${hh}:${mm} ${ampm}`;
}

function fmtElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60); const rem = Math.round(s - m * 60);
  return `${m}m ${rem}s`;
}

export default function Page() {
  const sessionId = useSessionId();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [me, setMe] = useState<{ email?: string; sub?: string } | null>(null);
  useEffect(() => {
    fetch("/api/auth/me").then((r) => r.ok ? r.json() : null).then((profile) => {
      setMe(profile);
      if (profile?.sub) {
        setMessages(loadHistory(profile.sub));
      }
      // Defensive warmup: if the user landed on /chat with a valid cookie
      // but their sandbox was reaped after 30 min idle, this re-provisions
      // it while they're still deciding what to ask. The server-side
      // /api/warmup enforces the @amazon.com gate; we also check here to
      // avoid the roundtrip for non-matching domains.
      const domain = (profile?.email || "").toLowerCase().split("@").pop();
      if (domain === "amazon.com") {
        fetch("/api/warmup", { method: "POST", keepalive: true }).catch(() => {});
      }
    }).catch(() => setMe(null));
  }, []);

  // Persist on every message change
  useEffect(() => {
    if (me?.sub && messages.length > 0) saveHistory(me.sub, messages);
  }, [messages, me?.sub]);

  const [thinking, setThinking] = useState(false);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + "px";
    }
  }, [input]);

  async function send(body?: string) {
    const content = (body ?? input).trim();
    if (!content || streaming) return;
    setInput("");
    const sendStart = Date.now();
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content, createdAt: sendStart };
    const asstMsg: Msg = { id: crypto.randomUUID(), role: "assistant", content: "", createdAt: sendStart };
    setMessages((m) => [...m, userMsg, asstMsg]);
    setStreaming(true);
    setThinking(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: content, sessionId }),
      });
      if (!res.body) throw new Error("no body");
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const event = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (!event.startsWith("data:")) continue;
          const data = event.slice(5).trim();
          if (data === "[DONE]") continue;
          try {
            const j = JSON.parse(data);
            if (j.status === "provisioning") setStatusLabel("Starting your private Kata VM…");
            if (j.status === "ready") setStatusLabel("Loading your workspace…");
            if (j.status === "thinking") { setStatusLabel(null); setThinking(true); }
            if (j.delta) {
              setStatusLabel(null);
              setThinking(false);
              acc += j.delta;
              setMessages((m) => {
                const copy = m.slice();
                copy[copy.length - 1] = { ...copy[copy.length - 1], content: acc };
                return copy;
              });
            }
            if (j.error) {
              acc = `⚠️ ${j.error}`;
              setMessages((m) => {
                const copy = m.slice();
                copy[copy.length - 1] = { ...copy[copy.length - 1], content: acc };
                return copy;
              });
            }
          } catch {}
        }
      }
      // Stamp the final assistant message with response time
      const elapsed = Date.now() - sendStart;
      setMessages((m) => {
        const copy = m.slice();
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") {
          copy[copy.length - 1] = { ...last, responseMs: elapsed, createdAt: Date.now() };
        }
        return copy;
      });
    } catch (e) {
      setMessages((m) => {
        const copy = m.slice();
        copy[copy.length - 1] = { ...copy[copy.length - 1], content: `⚠️ Connection error: ${(e as Error).message}` };
        return copy;
      });
    } finally {
      setStreaming(false);
      setThinking(false);
      setStatusLabel(null);
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  function clearHistory() {
    if (streaming) return;
    if (!confirm("Clear this chat history? This cannot be undone.")) return;
    setMessages([]);
    if (me?.sub) { try { localStorage.removeItem(historyKey(me.sub)); } catch {} }
    const s = `web-${Date.now().toString(36)}`;
    try { localStorage.setItem("finassist.session", s); } catch {}
    window.location.reload();
  }

  const empty = messages.length === 0;

  return (
    <main className="flex h-screen w-screen overflow-hidden">
      {/* Sidebar */}
      <AnimatePresence>
        {(sidebarOpen || typeof window !== "undefined" && window.innerWidth >= 1024) && (
          <motion.aside
            initial={{ x: -320 }} animate={{ x: 0 }} exit={{ x: -320 }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed lg:static lg:flex z-40 h-full w-72 flex-col border-r border-ink-800/60 glass"
          >
            <div className="flex items-center gap-3 p-5 border-b border-ink-800/60">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-accent-400 to-gold-500 flex items-center justify-center text-ink-950 font-bold">F</div>
              <div>
                <div className="text-sm font-semibold">Finance Assistant</div>
                <div className="text-xs text-ink-400">Kata VM · Bedrock</div>
              </div>
              <button onClick={() => setSidebarOpen(false)} className="lg:hidden ml-auto text-ink-400 hover:text-ink-100"><X size={18}/></button>
            </div>

            <div className="p-5 space-y-6 overflow-y-auto flex-1">
              <div>
                <div className="text-[10px] uppercase tracking-widest text-ink-500 font-semibold mb-3">Trust</div>
                <TrustRow icon={<ShieldCheck size={14}/>} label="Hardware-isolated" value="Kata QEMU" />
                <TrustRow icon={<Lock size={14}/>}        label="No account access" value="Read-only" />
                <TrustRow icon={<Shield size={14}/>}      label="PII + denied topics" value="Bedrock Guardrail" />
                <TrustRow icon={<Cpu size={14}/>}         label="Model"          value="Claude Sonnet 4.6" />
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-widest text-ink-500 font-semibold mb-3">Session</div>
                <div className="text-xs text-ink-400 font-mono">{sessionId}</div>
                <div className="text-[11px] text-ink-500 mt-2">Persists across page reloads. Clear localStorage to reset.</div>
              </div>
            </div>

            <div className="p-5 border-t border-ink-800/60">
              {me?.email && (
                <div className="flex items-center gap-2.5 mb-3 px-2 py-2 rounded-lg bg-ink-900/60 border border-ink-800/80">
                  <div className="w-7 h-7 shrink-0 rounded-full bg-gradient-to-br from-accent-500/30 to-gold-500/20 border border-accent-500/40 flex items-center justify-center text-accent-400">
                    <User size={13}/>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] font-medium text-ink-100 truncate">{me.email}</div>
                    <div className="text-[10px] text-ink-500">Signed in</div>
                  </div>
                </div>
              )}
              <a
                href="/api/auth/logout"
                className="flex items-center gap-2 w-full px-2.5 py-2 rounded-lg text-[12px] text-ink-300 hover:text-ink-50 hover:bg-ink-900/80 border border-transparent hover:border-ink-800 transition"
              >
                <LogOut size={13}/>
                <span>Sign out</span>
              </a>
              <div className="mt-4 text-[11px] leading-relaxed text-ink-500">
                Educational only. Not a fiduciary, CFP, or CPA. For material decisions consult a licensed professional.
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Main column */}
      <section className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center gap-3 px-6 py-4 border-b border-ink-800/60 glass">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden text-ink-300 hover:text-ink-100"><Menu size={20}/></button>
          <Sparkles size={16} className="text-accent-400"/>
          <h1 className="text-sm font-semibold tracking-tight">Personal Finance Assistant</h1>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-500/10 border border-accent-500/30 text-accent-400 uppercase tracking-wider">OpenClaw · Kata VM</span>
          <button
            onClick={clearHistory}
            disabled={streaming}
            title="Clear history and start a new chat"
            className="ml-4 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] text-ink-300 hover:text-ink-50 hover:bg-ink-900/80 border border-ink-800 hover:border-accent-500/40 transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Plus size={12}/>
            <span>New chat</span>
          </button>
          <div className="ml-auto flex items-center gap-2 text-xs text-ink-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"/>
            <span>Connected</span>
          </div>
        </header>

        {/* Messages / empty state */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-8">
          {empty ? (
            <EmptyState onPick={(p) => send(p)} />
          ) : (
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((m, i) => {
                // Suppress the trailing empty assistant bubble while
                // ThinkingIndicator is rendering its own F avatar —
                // otherwise users see two F avatars stacked.
                if ((thinking || statusLabel) && i === messages.length - 1 && m.role === "assistant" && !m.content) return null;
                return <Message key={m.id} msg={m} />;
              })}
              {(thinking || statusLabel) && <ThinkingIndicator label={statusLabel}/>}
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="border-t border-ink-800/60 glass">
          <div className="max-w-3xl mx-auto p-4">
            <div className="relative flex items-end gap-3 rounded-2xl border border-ink-800 bg-ink-900/80 focus-within:border-accent-500/50 focus-within:ring-2 focus-within:ring-accent-500/20 transition">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKey}
                rows={1}
                placeholder="Ask about budgeting, retirement math, tax concepts, or paste a document to understand…"
                className="flex-1 bg-transparent resize-none p-4 text-sm placeholder:text-ink-500 focus:outline-none max-h-[200px]"
                disabled={streaming}
              />
              <button
                onClick={() => send()}
                disabled={streaming || !input.trim()}
                className={cn(
                  "m-2 rounded-xl w-10 h-10 flex items-center justify-center transition-all",
                  streaming || !input.trim()
                    ? "bg-ink-800 text-ink-500 cursor-not-allowed"
                    : "btn-gradient hover:brightness-110 shadow-lg shadow-accent-500/20"
                )}
              >
                <Send size={16}/>
              </button>
            </div>
            <div className="text-[11px] text-ink-500 mt-2 px-1 flex justify-between">
              <span>Press <kbd className="px-1.5 py-0.5 bg-ink-800 border border-ink-700 rounded text-[10px] font-mono">Enter</kbd> to send · <kbd className="px-1.5 py-0.5 bg-ink-800 border border-ink-700 rounded text-[10px] font-mono">Shift+Enter</kbd> for newline</span>
              <span>Responses run inside an isolated Kata VM.</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function TrustRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 py-1.5 text-xs">
      <span className="text-accent-400">{icon}</span>
      <span className="text-ink-300">{label}</span>
      <span className="ml-auto text-ink-400 font-mono text-[11px]">{value}</span>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (s: string) => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}
      className="max-w-3xl mx-auto">
      <div className="text-center space-y-3 mb-10">
        <motion.div initial={{ scale: 0.9 }} animate={{ scale: 1 }} className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent-500/10 border border-accent-500/30 text-[11px] text-accent-400 uppercase tracking-widest">
          <ShieldCheck size={12}/> Private · Hardware-isolated
        </motion.div>
        <h2 className="text-3xl md:text-4xl font-semibold tracking-tight bg-gradient-to-br from-ink-50 to-ink-400 bg-clip-text text-transparent">
          Think about money clearly.
        </h2>
        <p className="text-ink-400 max-w-xl mx-auto text-sm md:text-base">
          An educational thinking partner. No account access, no specific security picks, no guaranteed returns — just frameworks, math, and honest tradeoffs.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        {SUGGESTIONS.map((s, i) => (
          <motion.button
            key={s.title}
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * i, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            onClick={() => onPick(s.body)}
            className="group text-left rounded-xl border border-ink-800 bg-ink-900/40 hover:border-accent-500/40 hover:bg-ink-900/80 p-4 transition-all"
          >
            <div className="flex items-center gap-2 mb-2">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-accent-500/30 to-gold-500/20 border border-accent-500/30 flex items-center justify-center text-accent-400">
                <s.icon size={14}/>
              </div>
              <span className="text-sm font-medium group-hover:text-accent-400 transition">{s.title}</span>
            </div>
            <p className="text-xs text-ink-400 leading-relaxed line-clamp-3">{s.body}</p>
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}

function Message({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
      className={cn("flex gap-3", isUser ? "justify-end" : "")}>
      {!isUser && (
        <div className="w-8 h-8 shrink-0 rounded-lg bg-gradient-to-br from-accent-400 to-gold-500 flex items-center justify-center text-ink-950 font-bold text-xs mt-1">
          F
        </div>
      )}
      <div className={cn("flex flex-col", isUser ? "items-end" : "items-start", "max-w-[85%] gap-1")}>
        <div className={cn(
          "rounded-2xl px-4 py-3",
          isUser
            ? "bg-gradient-to-br from-accent-500 to-accent-600 text-white shadow-lg shadow-accent-500/20"
            : "bg-ink-900/80 border border-ink-800"
        )}>
          {isUser ? (
            <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
          ) : (
            <div className="prose-finance text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                {msg.content || "…"}
              </ReactMarkdown>
            </div>
          )}
        </div>
        <div className={cn("text-[10px] text-ink-500 font-mono px-1 flex items-center gap-2", isUser ? "justify-end" : "justify-start")}>
          <span>{fmtTime(msg.createdAt)}</span>
          {!isUser && typeof msg.responseMs === "number" && (
            <span className="text-accent-500/70">· {fmtElapsed(msg.responseMs)}</span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ThinkingIndicator({ label }: { label?: string | null }) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
      <div className="w-8 h-8 shrink-0 rounded-lg bg-gradient-to-br from-accent-400 to-gold-500 flex items-center justify-center text-ink-950 font-bold text-xs mt-1">F</div>
      <div className="rounded-2xl px-4 py-3 bg-ink-900/80 border border-ink-800 text-sm text-ink-400 flex items-center gap-2">
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-accent-400 animate-bounce" style={{animationDelay:"0ms"}}/>
          <span className="w-1.5 h-1.5 rounded-full bg-accent-400 animate-bounce" style={{animationDelay:"150ms"}}/>
          <span className="w-1.5 h-1.5 rounded-full bg-accent-400 animate-bounce" style={{animationDelay:"300ms"}}/>
        </div>
        <span className="text-xs">{label || "Reasoning inside the Kata VM…"}</span>
      </div>
    </motion.div>
  );
}
