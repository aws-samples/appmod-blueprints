"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useScroll, useTransform, useSpring } from "framer-motion";
import {
  ShieldCheck, Cpu, Lock, Sparkles, ArrowRight, Send,
  TrendingUp, Home, GraduationCap, Target, Zap, Eye,
  LineChart, Wallet, Calculator, CheckCircle2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AuthModal from "./AuthModal";

// All "Sign in" / "Get started" buttons go to the app's OAuth kickoff
// route. Middleware + /api/auth/* handle the rest.
// Tiny event bus — sibling components across this file dispatch
// "open-auth" to open the modal without prop-drilling.
const openAuth = (tab: "signin" | "signup" = "signin") => {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("open-auth", { detail: { tab } }));
  }
};

const DEMO_REPLIES: Record<string, string> = {
  savings: `Here's a framework to think about it — not a prescription.

**Order-of-operations rule of thumb**

1. **401(k) to match** — anything else with a guaranteed 50–100% return is illegal.
2. **HSA, if you qualify** — triple tax advantage: deductible, grows tax-free, withdrawals for medical expenses tax-free. Often better than a 401(k) dollar for dollar.
3. **High-interest debt** — above ~6%, the math favors paying down over investing.
4. **Max tax-advantaged space** — 401(k) to limit, IRA/Roth per rules.
5. **Taxable brokerage** — flexibility, long-term capital gains rates.

**For your situation specifically**: the question I'd want to answer first is *what is this money for, and when?* A 529 optimizes for education; a taxable brokerage optimizes for "I want flexibility"; a backdoor Roth optimizes for tax-free growth over decades. These aren't substitutes — they're different tools.

Want to work through a concrete split with numbers?`,
  retirement: `Good question to pressure-test. Let me lay out the assumptions that matter most, then stress-test.

**Baseline assumptions**

- Target: $2M in today's dollars at age 55
- Current: $400k at age 38 (17 years out)
- Unknown: contribution rate, expected real return, inflation

**The 3% rule math** (real returns, after inflation)

If you assume a **5% real return** and contribute $30k/year:
> ≈ $918k + $766k = **$1.68M** (shortfall ~$320k)

If you can push contributions to **$45k/year**:
> ≈ $918k + $1.15M = **$2.07M** (just over target)

**Sensitivities**

- Real return 4% instead of 5%: target drops to ~$1.75M at $45k/year → miss
- 2 extra years of work to 57: huge, compounding is most of the gain late
- Health insurance gap 55 → 65 pre-Medicare: plan for $10–20k/year cost

I'd want to see your actual expected expenses next — $2M is only meaningful against a spending plan. Want to build that?`,
  rent: `The rent-vs-buy math has four inputs that dominate. Most online calculators get two of them wrong.

**The inputs that matter**

1. **Unrecoverable cost** of owning: mortgage interest + property tax + maintenance (~1%/yr) + HOA + transaction cost amortized over holding period
2. **Unrecoverable cost** of renting: the rent itself
3. **Opportunity cost** of the down payment (what it would earn invested)
4. **Expected appreciation** (nobody knows)

**For your $900k / 20% down / 7% scenario**

> Interest on $720k at 7% ≈ $50k/yr (year 1)
> + Property tax ~1.2% = $10.8k
> + Maintenance ~1% = $9k
> + Opportunity cost on $180k at 5% real = $9k
> = **~$79k/yr** unrecoverable

If comparable rent is **below $6,600/month**, renting is cheaper on unrecoverable basis. Above that, buying starts to win — and the gap widens as you pay down principal.

Want to run your specific rent number and holding period?`,
  default: `Good question. Before I answer, two things I want to be clear about:

I'm an **educational thinking partner**, not a fiduciary. I don't know your accounts and can't recommend specific funds or stocks. For material decisions — retirement plan rollovers, Roth conversions above ~$10k, estate planning, insurance beyond term life — you should talk to a CFP, CPA, or estate attorney as appropriate.

With that said: most financial questions have a common structure. **What is the money for? When do you need it? What happens if you're wrong?** Those three questions resolve 80% of "should I X or Y" situations.

Sign in and we can work through the specifics with your actual numbers, run scenario math, and save the analysis to your private workspace.`,
};

function matchReply(q: string): string {
  const s = q.toLowerCase();
  if (/sav|invest|401|roth|hsa|bracket/.test(s)) return DEMO_REPLIES.savings;
  if (/retire|55|60|65|fire/.test(s)) return DEMO_REPLIES.retirement;
  if (/rent|buy|hous|home|mortgag/.test(s)) return DEMO_REPLIES.rent;
  return DEMO_REPLIES.default;
}

const QUICK_ASKS = [
  { icon: TrendingUp,    label: "How should I split $3k/mo between retirement, 529, and brokerage?", key: "savings" },
  { icon: Home,          label: "Walk me through rent vs buy math for a $900k home.",                 key: "rent" },
  { icon: Target,        label: "I want to retire at 55 with $2M — what assumptions matter?",          key: "retirement" },
  { icon: GraduationCap, label: "529 vs UTMA for my kid — what are the real tradeoffs?",              key: "default" },
];

export default function Landing() {
  const [authOpen, setAuthOpen] = useState(false);
  const [authTab, setAuthTab] = useState<"signin" | "signup">("signin");

  useEffect(() => {
    const h = (e: Event) => {
      const detail = (e as CustomEvent<{ tab?: "signin" | "signup" }>).detail;
      setAuthTab(detail?.tab ?? "signin");
      setAuthOpen(true);
    };
    window.addEventListener("open-auth", h);
    // Auto-open when middleware bounced an unauthenticated /app visit
    // back to / with #signin (or #signup)
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "");
      if (hash === "signin" || hash === "signup") {
        setAuthTab(hash);
        setAuthOpen(true);
        // Clean the URL so a reload doesn't re-open the modal.
        history.replaceState(null, "", window.location.pathname + window.location.search);
      }
    }
    return () => window.removeEventListener("open-auth", h);
  }, []);

  return (
    <main className="min-h-screen overflow-hidden selection:bg-accent-500/30 selection:text-ink-50">
      <AnimatedBackground />
      <Nav />
      <Hero />
      <SocialProof />
      <PreviewSection />
      <FeatureSection />
      <DeepDive />
      <TrustSection />
      <Disclosure />
      <FinalCta />
      <Footer />
      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} initialTab={authTab}/>
    </main>
  );
}

/* ─────────────── Animated background — slowly drifting mesh gradient ─────────────── */

function AnimatedBackground() {
  return (
    <div aria-hidden className="fixed inset-0 -z-10 pointer-events-none">
      <div className="absolute inset-0 bg-ink-950"/>
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 2 }}
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 20% -10%, rgba(34,211,238,0.15), transparent 60%)," +
            "radial-gradient(ellipse 60% 40% at 90% 10%, rgba(251,191,36,0.10), transparent 60%)," +
            "radial-gradient(ellipse 70% 50% at 50% 100%, rgba(6,182,212,0.08), transparent 60%)",
        }}
      />
      {/* fine grid overlay */}
      <div
        className="absolute inset-0 opacity-[0.025]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(241,245,249,1) 1px, transparent 1px), linear-gradient(90deg, rgba(241,245,249,1) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />
    </div>
  );
}

/* ─────────────── Nav ─────────────── */

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
      scrolled ? "backdrop-blur-xl bg-ink-950/70 border-b border-ink-900/80" : "bg-transparent"
    }`}>
      <nav className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <a href="#" className="flex items-center gap-2.5 group">
          <div className="relative w-8 h-8 rounded-lg bg-gradient-to-br from-accent-400 via-accent-500 to-gold-500 flex items-center justify-center text-ink-950 font-bold text-sm shadow-lg shadow-accent-500/20 group-hover:shadow-accent-500/40 transition">
            F
          </div>
          <span className="text-sm font-semibold tracking-tight">Finance Assistant</span>
        </a>
        <div className="hidden md:flex items-center gap-8 text-sm">
          <a href="#preview"  className="text-ink-400 hover:text-ink-50 transition">Preview</a>
          <a href="#features" className="text-ink-400 hover:text-ink-50 transition">What you can ask</a>
          <a href="#trust"    className="text-ink-400 hover:text-ink-50 transition">Why trust it</a>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => openAuth("signin")} className="hidden sm:inline text-xs font-medium text-ink-300 hover:text-ink-50 transition">Sign in</button>
          <button onClick={() => openAuth("signup")} className="btn-gradient rounded-lg px-4 py-2 text-xs font-semibold transition hover:brightness-110">
            Get started
          </button>
        </div>
      </nav>
    </header>
  );
}

/* ─────────────── Hero ─────────────── */

function Hero() {
  const { scrollY } = useScroll();
  const y = useSpring(useTransform(scrollY, [0, 500], [0, -80]), { stiffness: 90, damping: 20 });
  const opacity = useTransform(scrollY, [0, 400], [1, 0.2]);

  return (
    <section className="relative pt-32 md:pt-44 pb-20 md:pb-32">
      <motion.div style={{ y, opacity }} className="max-w-6xl mx-auto px-6 text-center">
        <motion.div
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-accent-500/10 border border-accent-500/30 text-[11px] text-accent-400 uppercase tracking-widest mb-7"
        >
          <ShieldCheck size={12}/> Hardware-isolated · Private by design
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.05 }}
          className="text-5xl sm:text-6xl md:text-8xl font-semibold tracking-tight leading-[1.02]"
        >
          <span className="bg-gradient-to-br from-ink-50 via-ink-100 to-ink-400 bg-clip-text text-transparent">A thinking partner</span>
          <br/>
          <span className="bg-gradient-to-br from-accent-400 via-accent-500 to-gold-500 bg-clip-text text-transparent">for money.</span>
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.15 }}
          className="mt-8 text-lg md:text-2xl text-ink-300 max-w-3xl mx-auto leading-[1.5]"
        >
          An educational assistant that helps you reason clearly about budgeting, retirement, tax concepts, and major purchases. <span className="text-ink-100">Frameworks and honest math</span> — never specific picks or guaranteed returns.
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.25 }}
          className="mt-12 flex items-center justify-center gap-3 flex-wrap"
        >
          <button onClick={() => openAuth("signin")} className="btn-gradient group rounded-xl px-7 py-4 text-sm font-semibold flex items-center gap-2 shadow-2xl shadow-accent-500/30 transition-all hover:shadow-accent-500/60 hover:brightness-110">
            Sign in to start
            <ArrowRight size={16} className="group-hover:translate-x-0.5 transition"/>
          </button>
          <a href="#preview" className="rounded-xl px-7 py-4 text-sm font-semibold border border-ink-700 text-ink-200 hover:border-accent-500/50 hover:bg-ink-900/40 hover:text-ink-50 transition">
            Try it live ↓
          </a>
        </motion.div>
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8, delay: 0.4 }}
          className="mt-14 flex items-center justify-center gap-8 flex-wrap text-[13px] text-ink-400"
        >
          <TrustChip icon={<Cpu size={14}/>} label="Kata VM isolation"/>
          <TrustChip icon={<Lock size={14}/>} label="No account access"/>
          <TrustChip icon={<Eye size={14}/>} label="Per-user workspace"/>
          <TrustChip icon={<ShieldCheck size={14}/>} label="Bedrock Guardrail"/>
        </motion.div>
      </motion.div>
    </section>
  );
}

function TrustChip({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-accent-400">{icon}</span>
      <span>{label}</span>
    </span>
  );
}

/* ─────────────── Social proof strip ─────────────── */

function SocialProof() {
  const items = [
    "Budget frameworks",
    "Retirement stress tests",
    "Rent vs buy math",
    "ESPP / RSU / 401(k)",
    "HSA · FSA · HDHP",
    "Backdoor Roth mechanics",
    "Home purchase tradeoffs",
    "529 vs UTMA",
  ];
  return (
    <section className="py-10 border-y border-ink-900/60 bg-ink-950/30">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center text-[11px] uppercase tracking-widest text-ink-500 font-semibold mb-5">
          Real questions people actually ask
        </div>
        <div className="flex items-center justify-center gap-x-8 gap-y-3 flex-wrap text-sm text-ink-400">
          {items.map((x) => <span key={x} className="font-medium">{x}</span>)}
        </div>
      </div>
    </section>
  );
}

/* ─────────────── Preview chat ─────────────── */

function PreviewSection() {
  return (
    <section id="preview" className="relative py-24 md:py-32">
      <div className="max-w-6xl mx-auto px-6">
        <SectionHeading
          eyebrow="Try before you sign in"
          title="Ask anything. Watch it think."
          body="A live preview — canned replies streamed word-by-word. The real chat runs inside an isolated Kata VM after you sign in."
        />
        <LivePreview/>
      </div>
    </section>
  );
}

function LivePreview() {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [msgs, setMsgs] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  async function simulate(prompt: string, forceKey?: string) {
    if (streaming) return;
    setStreaming(true);
    setMsgs((m) => [...m, { role: "user", content: prompt }, { role: "assistant", content: "" }]);
    const full = forceKey ? (DEMO_REPLIES[forceKey] || DEMO_REPLIES.default) : matchReply(prompt);
    const words = full.split(/(\s+)/);
    let acc = "";
    for (const w of words) {
      acc += w;
      await new Promise((r) => setTimeout(r, 22));
      setMsgs((m) => {
        const c = m.slice();
        c[c.length - 1] = { role: "assistant", content: acc };
        return c;
      });
    }
    setStreaming(false);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-100px" }}
      transition={{ duration: 0.6 }}
      className="rounded-3xl border border-ink-800/80 bg-gradient-to-b from-ink-900/60 to-ink-900/30 backdrop-blur-xl overflow-hidden shadow-[0_30px_80px_-20px_rgba(0,0,0,0.6)]"
    >
      {/* Browser chrome */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-800/80 bg-ink-950/40">
        <div className="flex gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-ink-700"/>
          <span className="w-2.5 h-2.5 rounded-full bg-ink-700"/>
          <span className="w-2.5 h-2.5 rounded-full bg-ink-700"/>
        </div>
        <div className="flex-1 text-center text-[11px] text-ink-500 font-mono tracking-tight">
          your-domain.example.com/app
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 uppercase tracking-wider">Live</span>
      </div>

      {/* Chat area */}
      <div ref={ref} className="h-[520px] overflow-y-auto p-6 space-y-5">
        {msgs.length === 0 ? (
          <div className="flex flex-col gap-4 items-center justify-center h-full text-center">
            <div className="text-ink-400 text-sm max-w-sm">Tap a question to see the style, or type your own below.</div>
            <div className="grid sm:grid-cols-2 gap-2.5 max-w-2xl w-full">
              {QUICK_ASKS.map((q) => (
                <button
                  key={q.label}
                  onClick={() => simulate(q.label, q.key)}
                  className="group text-left rounded-xl border border-ink-800 bg-ink-900/60 hover:border-accent-500/50 hover:bg-ink-900/90 p-3.5 transition flex items-start gap-3"
                >
                  <div className="w-8 h-8 shrink-0 rounded-lg bg-accent-500/10 border border-accent-500/30 flex items-center justify-center text-accent-400">
                    <q.icon size={15}/>
                  </div>
                  <span className="text-[13px] text-ink-200 group-hover:text-ink-50 leading-relaxed">{q.label}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          msgs.map((m, i) => <PreviewMessage key={i} role={m.role} content={m.content} last={i === msgs.length-1 && streaming}/>)
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-ink-800/80 p-4 bg-ink-950/40">
        <form
          onSubmit={(e) => { e.preventDefault(); const v = input.trim(); if (v) { setInput(""); simulate(v); } }}
          className="flex items-center gap-3 rounded-xl border border-ink-800 bg-ink-900/80 focus-within:border-accent-500/50 focus-within:ring-2 focus-within:ring-accent-500/20 transition"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about budgeting, retirement math, rent vs buy…"
            className="flex-1 bg-transparent px-4 py-3 text-sm placeholder:text-ink-500 focus:outline-none"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="m-1.5 rounded-lg w-9 h-9 flex items-center justify-center btn-gradient disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Send"
          >
            <Send size={14}/>
          </button>
        </form>
        <div className="mt-3 flex items-center justify-between text-[11px] text-ink-500">
          <span>Preview only — canned replies, no model calls.</span>
          <button onClick={() => openAuth("signin")} className="text-accent-400 hover:text-accent-300 font-medium">Sign in for the real thing →</button>
        </div>
      </div>
    </motion.div>
  );
}

function PreviewMessage({ role, content, last }: { role: "user"|"assistant"; content: string; last: boolean }) {
  const isUser = role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 ${isUser ? "justify-end" : ""}`}
    >
      {!isUser && (
        <div className="w-7 h-7 shrink-0 rounded-lg bg-gradient-to-br from-accent-400 to-gold-500 flex items-center justify-center text-ink-950 font-bold text-[11px] mt-1">F</div>
      )}
      <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${isUser ? "bg-gradient-to-br from-accent-500 to-accent-600 text-white" : "bg-ink-900/90 border border-ink-800"}`}>
        {isUser ? (
          <span className="whitespace-pre-wrap">{content}</span>
        ) : (
          <div className="prose-finance text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || "…"}</ReactMarkdown>
            {last && content && <span className="inline-block w-1.5 h-4 bg-accent-400 animate-pulse ml-0.5 align-middle"/>}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/* ─────────────── Feature grid ─────────────── */

function FeatureSection() {
  const features = [
    { icon: TrendingUp,    title: "Savings frameworks",    body: "Order-of-operations for contributions, rule-of-thumb splits, how to think about 401(k)/HSA/Roth/taxable brokerage without anyone telling you to buy VTSAX." },
    { icon: Home,          title: "Major purchase math",   body: "Rent vs buy broken down by unrecoverable cost. Total cost of owning a car beyond the sticker. How much house you can actually afford." },
    { icon: Target,        title: "Retirement stress tests", body: "Not a calculator that assumes 7% forever. A back-and-forth about what happens if return is 1% lower, if inflation is 1% higher, if you retire 2 years later." },
    { icon: Calculator,    title: "Tax concepts, explained", body: "Marginal vs effective rates. What the AMT actually does. Why backdoor Roth requires a specific sequence. No advice — just mechanics." },
    { icon: Zap,           title: "Benefits, decoded",     body: "ESPP, RSU vesting, HDHP vs PPO, HSA vs FSA. The actual numbers behind the options your employer hands you in a 200-slide deck." },
    { icon: Wallet,        title: "Your private workspace", body: "Goals, snapshots, decision log, scenarios — saved across sessions in your own isolated space. No one sees it. Not even us." },
  ];

  return (
    <section id="features" className="relative py-24 md:py-32 border-t border-ink-900/80">
      <div className="max-w-7xl mx-auto px-6">
        <SectionHeading
          eyebrow="What you can ask"
          title="Real questions. Honest answers."
          body="These are the conversations people actually have. Not hot takes. Not hype."
        />
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {features.map((f, i) => <FeatureCard key={f.title} {...f} delay={i*0.05}/>)}
        </div>
      </div>
    </section>
  );
}

function FeatureCard({
  icon: Icon, title, body, delay = 0,
}: { icon: React.ElementType; title: string; body: string; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, delay, ease: [0.16, 1, 0.3, 1] }}
      className="group relative rounded-2xl border border-ink-800 bg-gradient-to-b from-ink-900/40 to-ink-900/10 hover:from-ink-900/80 hover:to-ink-900/40 hover:border-accent-500/40 p-7 transition overflow-hidden"
    >
      <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition pointer-events-none" style={{ background: "radial-gradient(600px at 50% -10%, rgba(34,211,238,0.08), transparent 40%)" }}/>
      <div className="relative">
        <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-accent-500/25 to-gold-500/15 border border-accent-500/30 flex items-center justify-center text-accent-400 mb-5 group-hover:scale-110 transition">
          <Icon size={18}/>
        </div>
        <div className="text-base font-semibold text-ink-50 mb-2">{title}</div>
        <p className="text-sm text-ink-400 leading-relaxed">{body}</p>
      </div>
    </motion.div>
  );
}

/* ─────────────── Deep-dive section (Stripe-like side by side) ─────────────── */

function DeepDive() {
  return (
    <section className="relative py-24 md:py-36 border-t border-ink-900/80">
      <div className="max-w-6xl mx-auto px-6 grid md:grid-cols-2 gap-14 items-center">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
        >
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gold-500/10 border border-gold-500/30 text-[11px] text-gold-400 uppercase tracking-widest mb-5">
            <LineChart size={12}/> Scenario math
          </div>
          <h2 className="text-3xl md:text-5xl font-semibold tracking-tight leading-tight bg-gradient-to-br from-ink-50 to-ink-300 bg-clip-text text-transparent">
            Every assumption shown. Every sensitivity stress-tested.
          </h2>
          <p className="mt-5 text-ink-400 leading-relaxed text-[15px]">
            When you ask a "what if" question, you get the assumptions at the top, the math in the middle, and a row of sensitivities at the bottom: what happens if return is 1% lower, if inflation is 1% higher, if your horizon is 5 years shorter. No black boxes.
          </p>
          <ul className="mt-6 space-y-3 text-sm text-ink-300">
            <CheckLi>Python in a sandboxed runtime — actual math, not hand-waving</CheckLi>
            <CheckLi>Saved as <code className="font-mono text-accent-400 text-[12px] bg-ink-900/70 px-1.5 py-0.5 rounded">scenarios/*.md</code> in your private workspace</CheckLi>
            <CheckLi>Re-run later with updated numbers, see what changed</CheckLi>
          </ul>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="rounded-2xl border border-ink-800/80 bg-ink-900/60 backdrop-blur-xl p-6 font-mono text-[12.5px] leading-[1.7] text-ink-200 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.6)]"
        >
          <div className="flex items-center gap-2 mb-4 text-ink-500 text-[11px]">
            <span className="w-2 h-2 rounded-full bg-red-500/70"/>
            <span className="w-2 h-2 rounded-full bg-yellow-500/70"/>
            <span className="w-2 h-2 rounded-full bg-emerald-500/70"/>
            <span className="ml-2">retire-at-55.md</span>
          </div>
          <pre className="whitespace-pre-wrap">
<span className="text-ink-500"># Assumptions</span>
current_balance   = <span className="text-accent-400">400_000</span>
annual_contrib    = <span className="text-accent-400">45_000</span>
real_return       = <span className="text-gold-400">0.05</span>
years             = <span className="text-accent-400">17</span>

<span className="text-ink-500"># Math</span>
fv_balance   = current_balance * (<span className="text-gold-400">1</span>+real_return)**years
fv_contribs  = annual_contrib *
               ((<span className="text-gold-400">1</span>+real_return)**years - <span className="text-gold-400">1</span>) / real_return
total        = fv_balance + fv_contribs
<span className="text-emerald-400"># → $2.07M (just over target)</span>

<span className="text-ink-500"># Sensitivity</span>
<span className="text-emerald-400">#  real_return 0.04  → $1.75M   miss</span>
<span className="text-emerald-400">#  years + 2          → $2.41M   cushion</span>
          </pre>
        </motion.div>
      </div>
    </section>
  );
}

function CheckLi({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <CheckCircle2 size={16} className="text-accent-400 mt-0.5 shrink-0"/>
      <span>{children}</span>
    </li>
  );
}

/* ─────────────── Trust ─────────────── */

function TrustSection() {
  const items = [
    { icon: ShieldCheck, title: "Per-user VM isolation", body: "One kata-qemu VM per authenticated user. Another user's prompts cannot reach your workspace — the boundary is hardware, not trust." },
    { icon: Lock,        title: "No account access, ever", body: "The assistant has no read connection to your bank, brokerage, 401(k) admin, or any financial institution. It only knows what you choose to type." },
    { icon: Eye,         title: "Audited guardrails",    body: "Denied topics (specific securities, guaranteed returns, insider info). PII block (SSN, account numbers, credentials). Every response filtered, input and output." },
  ];
  return (
    <section id="trust" className="relative py-24 md:py-32 border-t border-ink-900/80">
      <div className="max-w-7xl mx-auto px-6">
        <SectionHeading
          eyebrow="Why you can trust it"
          title="Security isn't marketing copy."
          body="Each user's session runs in its own hardware-isolated Kata VM. Secrets live on tmpfs, never in env. A Bedrock guardrail blocks credentials and PII from ever touching the model."
        />
        <div className="grid md:grid-cols-3 gap-5">
          {items.map((x) => (
            <motion.div
              key={x.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.5 }}
              className="rounded-2xl border border-ink-800 bg-gradient-to-br from-ink-900/60 to-ink-900/20 p-7"
            >
              <div className="w-11 h-11 rounded-xl bg-accent-500/10 border border-accent-500/30 flex items-center justify-center text-accent-400 mb-5">
                <x.icon size={18}/>
              </div>
              <div className="text-base font-semibold text-ink-50 mb-2">{x.title}</div>
              <p className="text-sm text-ink-400 leading-relaxed">{x.body}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─────────────── Disclosure + Final CTA + Footer ─────────────── */

function Disclosure() {
  return (
    <section className="py-16 border-t border-ink-900/80">
      <div className="max-w-3xl mx-auto px-6 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-ink-900/60 border border-ink-800 text-[11px] text-ink-400 uppercase tracking-widest mb-4">
          Disclosure
        </div>
        <p className="text-sm text-ink-400 leading-relaxed">
          Educational only. This is not financial, tax, legal, or investment advice. The assistant is not a fiduciary, CFP, CPA, or broker. For material decisions — retirement plan rollovers, Roth conversions above ~$10k, estate planning, insurance beyond term life — consult a licensed professional.
        </p>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="relative py-24 md:py-32 border-t border-ink-900/80 overflow-hidden">
      <div aria-hidden className="absolute inset-0 pointer-events-none">
        <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse 60% 40% at 50% 100%, rgba(34,211,238,0.15), transparent 70%)" }}/>
      </div>
      <div className="relative max-w-3xl mx-auto px-6 text-center">
        <h2 className="text-4xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
          <span className="bg-gradient-to-br from-ink-50 to-ink-300 bg-clip-text text-transparent">Stop Googling.</span>
          <br/>
          <span className="bg-gradient-to-br from-accent-400 via-accent-500 to-gold-500 bg-clip-text text-transparent">Start thinking clearly.</span>
        </h2>
        <div className="mt-10 flex items-center justify-center gap-3 flex-wrap">
          <button onClick={() => openAuth("signin")} className="btn-gradient group rounded-xl px-8 py-4 text-sm font-semibold flex items-center gap-2 shadow-2xl shadow-accent-500/30 transition hover:shadow-accent-500/60 hover:brightness-110">
            Sign in to start
            <ArrowRight size={16} className="group-hover:translate-x-0.5 transition"/>
          </button>
          <a href="#preview" className="rounded-xl px-8 py-4 text-sm font-semibold border border-ink-700 text-ink-200 hover:border-accent-500/50 hover:text-ink-50 transition">
            Try the preview first
          </a>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-ink-900/80 py-10 bg-ink-950/40">
      <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row gap-4 items-center justify-between text-xs text-ink-500">
        <div className="flex items-center gap-2.5">
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-accent-400 to-gold-500 flex items-center justify-center text-ink-950 font-bold text-[10px]">F</div>
          <span>Finance Assistant — a private, hardware-isolated thinking partner.</span>
        </div>
        <div className="flex gap-6">
          <a href="#preview"  className="hover:text-ink-200 transition">Preview</a>
          <a href="#features" className="hover:text-ink-200 transition">Features</a>
          <a href="#trust"    className="hover:text-ink-200 transition">Trust</a>
          <button onClick={() => openAuth("signin")} className="text-accent-400 hover:text-accent-300 font-medium">Sign in →</button>
        </div>
      </div>
    </footer>
  );
}

/* ─────────────── Shared section heading ─────────────── */

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <div className="text-center mb-16 max-w-2xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
        className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent-500/10 border border-accent-500/30 text-[11px] text-accent-400 uppercase tracking-widest mb-5"
      >
        <Sparkles size={12}/> {eyebrow}
      </motion.div>
      <motion.h2
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.05 }}
        className="text-3xl md:text-5xl font-semibold tracking-tight bg-gradient-to-br from-ink-50 to-ink-300 bg-clip-text text-transparent mb-5 leading-tight"
      >
        {title}
      </motion.h2>
      <motion.p
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="text-ink-400 text-base md:text-lg leading-relaxed"
      >
        {body}
      </motion.p>
    </div>
  );
}
