# Cash Flow Advisor
### Hermes Agent Skill · Stripe Capital Integration

> An autonomous Hermes skill that monitors your Stripe account, detects upcoming cash flow gaps, evaluates available Stripe Capital offers against the cost of inaction, and projects the cash flows — allowing the Hermes Agent to tell you exactly what to do.

---

## The Problem

58% of small businesses fail due to cash flow problems — not because they're unprofitable, but because money arrives at the wrong time. A $28,000 payroll is due on Thursday. A $22,000 Stripe payout arrives Friday. The business has $12,500 in the bank. Nobody notices until Wednesday night.

Existing tools show dashboards. This skill acts.

---

## What It Does

1. **Multi-Source Data Ingestion**: Consolidates balances, pending payouts, invoices, subscriptions, and charges from **Stripe** alongside stubs for **QuickBooks**, **Xero**, and **Plaid**.
2. **Resilient Local Config**: Loads manual/fixed expenses from `config.yaml` with robust YAML syntax parsing error-handling to prevent crashes.
3. **Intelligent Recurring Expense Discovery**: Scans QuickBooks/bank transaction files via the `--detect-expenses` tool using regex heuristics to suggest additions to your expense configuration.
4. **Interactive Expense Configuration**: Allows the Hermes Agent or terminal users to list, add, or delete fixed expenses on the fly (e.g. `--add-expense`, `--delete-expense`, `--list-expenses`).
5. **Accurate 30-Day Projections**: Re-computes daily cash projections, modeling a precise Stripe Capital withholding drag up to the full `advance + fee` cap. Avoids double-counting on transit payouts.
6. **Decisive CFO-style Briefing**: Generates clean cash flow reports and resolution options. The Hermes Agent LLM natively acts as the CFO to formulate the morning briefing and specific capital recommendation.
7. **Webhook Simulation Handler**: Listens for confirmation events like `capital.financing_offer.paid_out` via a `--webhook` CLI parameter, logging events to a local ledger.
8. **Runs Unattended**: Scheduled via `hermes schedule add` at 8am daily or weekly.

---


---

## The Capital Integration

The critical insight: Stripe Capital offers are **pre-approved by Stripe** based on your processing history. The money exists. The question is whether it's cheaper to take the offer than to face the gap.

The skill automates everything except the final click:

| Step | What | How |
|------|------|-----|
| Detect gap | 30-day projection drops below zero | Python analysis |
| Fetch offer | `GET /v1/capital/financing_offers` | Stripe API |
| Evaluate | Flat fee vs. cost of missing payroll | Nemotron Ultra |
| Recommend | Specific amount, cost, repayment impact | Streaming LLM |
| **Accept** | **One click in Stripe Dashboard** | **Human (intentional)** |
| Confirm | `capital.financing_offer.paid_out` webhook | Stripe |

The human in the loop is intentional. Agents should not autonomously take out loans. The agent does the analysis; the human decides.

---

## Demo

```powershell
# Install deps (only openai is needed for the full experience)
pip install openai matplotlib

# Set your NVIDIA API key
$env:NVIDIA_API_KEY = "nvapi-..."

# Run
python demo.py
```

No Stripe key needed. The demo runs on a realistic built-in scenario:  
12-person SaaS startup · $12,500 available · $28,000 payroll in 3 days · $22,000 Stripe payout in 4 · **$25,000 Capital offer available**.

### What you see

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  💰  CASH FLOW ADVISOR  ·  Hermes Agent Skill  v0.2.0
      Stripe Capital × NVIDIA Nemotron Ultra 253B
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  STEP 1 / 4  ·  CONNECTING TO STRIPE
  Checking Capital offers...            ✗  1 OFFER AVAILABLE — $25,000

  STEP 3 / 4  ·  STRIPE CAPITAL EVALUATION
  Advance           $25,000
  Flat fee          $2,500   (10% · no interest, no compounding)
  IF ACCEPTED TODAY:
  Balance becomes   $37,500   (covers payroll with $9,500 buffer)
  30-day low        -$1,490   vs -$22,050 without Capital

  STEP 4 / 4  ·  NEMOTRON ULTRA 253B  ·  GENERATING BRIEFING
  [streaming Nemotron response...]

  ONE ACTION REQUIRED
  →  dashboard.stripe.com/capital
```

---

## Live Mode (real Stripe account)

```powershell
$env:STRIPE_SECRET_KEY = "sk_live_..."   # or sk_test_...
$env:NVIDIA_API_KEY    = "nvapi-..."
python cashflow_advisor.py
```

Add known expenses (payroll, rent) to `config.yaml` — Stripe doesn't know about bank transfers.

---

## Schedule in Hermes

```
# Daily at 8am
hermes schedule add "0 8 * * *" "run cashflow-advisor skill"

# Weekly (Monday)
hermes schedule add "0 8 * * 1" "run cashflow-advisor skill"
```

Reports save to `%USERPROFILE%\.hermes\cashflow\reports\`  
Charts save to `%USERPROFILE%\.hermes\cashflow\charts\`

---

## Files

| File | Purpose |
|------|---------|
| `cashflow_advisor.py` | Production engine — analysis, Capital logic, chart generation |
| `SKILL.md` | Hermes skill manifest — MCP tool calls, scheduling, trigger phrases |
| `config.yaml` | User config — expenses, schedule, alert thresholds |

---

## Tech Stack

- **Hermes Agent** (Nous Research) — skill runtime, scheduling, MCP integration, and native LLM reasoning
- **Stripe API** — balance, payouts, invoices, subscriptions, Capital offers
- **Python** — analysis engine, repayment modelling, matplotlib chart

---

## Why This Wins

Instead of creating problems and business logics that collapse upon themsevles, I am trying to solve problems faced by real businesses in real world in real time. Cashflows are never steady, and that causes reputation damage, losses, etc. Lets streamline that first.
Also, this can be a huge organic marketer for stripe capital. * wink wink *
