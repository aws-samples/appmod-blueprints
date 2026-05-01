# Personal Financial Assistant on OpenClaw

A read-only, privacy-first financial coach that runs inside a Kata QEMU VM on EKS. No bank, brokerage, or credential access — ever. The agent is useful precisely *because* of that constraint: it becomes a thinking partner, not a transactor.

## The design principle

Most "AI financial assistants" try to be robo-advisors — they need Plaid, Yodlee, or direct broker APIs, and their value proposition is automation. That's a crowded, high-risk space: credentials leak, OAuth scopes creep, and a misbehaving agent can drain an account.

This one inverts the model. You bring the data (paste, upload, type). The agent brings reasoning, math, scenario modeling, and durable memory of *your* goals. The blast radius if it misbehaves is a bad suggestion — never a transaction.

## What it can do

### Reasoning and explanation

- Explain any concept at the depth you ask for — Roth conversion ladders, backdoor Roth mechanics, HSA triple tax advantage, bond duration, sequence-of-returns risk, ESPP lookback math, RSU vesting tax drag, AMT triggers, wash sale rules, mega backdoor Roth via after-tax 401(k).
- Decode financial documents you paste or upload — 401(k) summary plan description, fund prospectus, benefits enrollment PDF, mortgage disclosure, loan estimate, brokerage fee schedule. Surface the fees, vesting cliffs, match formulas, and gotchas in plain language.
- Translate jargon both directions — "what does 'expense ratio' mean in practice on a $50k position over 20 years" and the inverse, "what's the technical term for the thing where I can't deduct IRA contributions above a certain income."

### Scenario math and modeling

- Compound growth projections with contribution schedules, inflation adjustment, and sequence-of-returns stress.
- Mortgage amortization, refinance break-even analysis, rent vs buy over N years with tax deduction and opportunity cost modeling.
- Debt payoff strategies — avalanche vs snowball with exact interest savings.
- Retirement drawdown modeling — 4% rule, guardrails strategy, bucket strategy, Roth conversion ladder optimization across tax brackets.
- Monte Carlo narratives — "out of 10,000 sequences, your plan survives in X% of them, fails most often because of Y."
- Tax projections — marginal vs effective, bracket management for Roth conversions, capital gains harvesting windows, NIIT thresholds.

### Decision frameworks

Not "what should I do" but "here's how to think about it":

- Emergency fund sizing based on your job stability, dependents, insurance.
- When extra dollars go to mortgage payoff vs taxable investing vs 401(k) match vs HSA.
- Traditional vs Roth contribution decision given your expected retirement bracket.
- Lump sum vs DCA for a windfall, with the historical data on why.
- Term vs whole life, why advisors push whole life, how to evaluate if it's ever right for you.
- When to fire your advisor and what an AUM fee actually costs compounded.

### Durable memory (the thing most chat tools get wrong)

A conversation about retirement planning is useless if the agent forgets your savings rate next week. This assistant maintains a per-user workspace on an encrypted PVC that survives pod restarts:

- `goals.md` — what you're working toward, horizon, priorities.
- `snapshot.md` — your self-reported financial picture (the latest version you shared). Never auto-fetched.
- `scenarios/` — saved scenario models you can revisit and tweak.
- `decisions.md` — a log of decisions you've made with the reasoning, so you can revisit *why* not just *what*.
- `questions.md` — things to think about, things to ask a CFP, things to re-evaluate at the next paycheck/quarter/year.

You can `/reset`, `/export`, or `/redact` at any time. The workspace is yours.

### Document intake

Drop a PDF or image into the UI — benefits booklet, pay stub, closing disclosure, brokerage statement (redact account numbers first). The agent extracts the structure, explains the fees, and asks clarifying questions. Documents are processed *inside* the Kata VM and never leave it except as the summarized reasoning you see in chat.

### Education on hard topics

- How an advisor's AUM fee compounds against you over 30 years.
- Why "past performance" disclaimers are load-bearing.
- The math of early retirement — why 25x expenses, when the rule breaks.
- Inheritance planning basics — step-up in basis, Roth vs traditional IRA inheritance rules post-SECURE Act.
- Insurance: term life laddering, umbrella policies, long-term care insurance's actual value proposition, disability insurance gaps.
- Estate planning primer — wills vs trusts, beneficiary designations beating wills, why naming a minor directly is a bad idea.

## What it deliberately will not do

- **No account access.** No Plaid, no OAuth into your bank, no read-only broker integration. Ever. The value you'd gain (automatic balance updates) is dwarfed by the risk of credential sprawl.
- **No specific security recommendations.** "VTSAX is a good index fund" is out. "Total US market index funds with expense ratios under 0.1% exist at Vanguard, Fidelity, and Schwab — here's how to evaluate them" is in.
- **No trade execution.** Even paper trades. The agent reasons; you act.
- **No "guaranteed returns" language.** Bedrock Guardrail denies this topic explicitly.
- **No advice framing.** The system prompt forces educational framing. Decisions are always yours, with a CFP recommendation for material ones.
- **No cross-user context leaks.** Each user gets an isolated Kata VM with its own PVC. The agent cannot know about another user's situation.

## Why this is a unique problem solver

Three things stacked together that almost nothing else offers:

1. **Hardware-isolated reasoning.** Your financial picture — even the version you typed — lives inside a Kata QEMU VM. Not a shared SaaS database. Not a multi-tenant row. A VM with its own kernel on bare-metal EC2. If the agent is compromised, it can't see other users, and it cannot exfiltrate silently because it has no outbound network except to LiteLLM.
2. **No account connection, by design.** Every other assistant's pitch assumes you want automation. This one's pitch is that you want a thinking partner who will *never* become an attack vector on your accounts.
3. **Durable, user-owned memory.** Your goals, decisions, and scenarios persist across sessions on a PVC *you* control — and `/export` gives you a markdown archive any time. You own the data; the agent rents time with it.

The combination — hardware isolation, no credentials, durable user-owned memory — is genuinely rare.

## Deployment modes

### Option A — Private web UI (recommended)

A Next.js UI fronted by an ALB with Cognito auth, deployed to the same cluster. DMs land in a chat column; scenarios render as interactive charts; document uploads go inline. See `ARCHITECTURE.md`.

### Option B — Slack (same pattern as claw-bot)

For users who already live in Slack. Same Sandbox CRD, just with the Slack plugin enabled and `allowFrom` locked to your user ID.

### Option C — Both

Slack for quick questions on mobile; the web UI for scenario modeling and document upload. They share the same PVC and system prompt.

## Files in this directory

| File | Purpose |
|---|---|
| `README.md` | This document |
| `ARCHITECTURE.md` | Deployment sketch, UI recommendation, integration points |
| `sandbox.yaml` | The Sandbox CRD that launches the agent |
| `system-prompt-configmap.yaml` | Persona and behavioral constraints |
| `guardrail-overlay.tf` | Bedrock Guardrail additions for finance topics |
| `web-ui/` | Next.js UI, ALB Ingress, Cognito wiring |
| `workspace-pvc.yaml` | Encrypted PVC for durable memory |

## Disclaimers

This assistant is educational. It is not a fiduciary, not a CFP, not a CPA, not a tax attorney. For any material decision — retirement plan, large tax event, estate planning, insurance — consult a licensed professional. The guardrail will remind you; so will the assistant.
