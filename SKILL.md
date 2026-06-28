---
name: cashflow-advisor
version: 0.4.0
description: >
  Daily or weekly SMB cash flow briefing with Stripe Capital integration.
  Detects gaps, evaluates Capital offers, models repayment impact, generates
  an acceptance link, and re-projects the 30-day balance post-funding.
author: arjun
license: MIT
tags: [finance, stripe, stripe-capital, cash-flow, smb, nemotron, scheduling, mcp]

requires_mcp:
  - stripe

env:
  required: []
  optional:
    - CASHFLOW_MIN_BUFFER        # Default: 5000
    - CASHFLOW_PROJECTION_DAYS   # Default: 30
    - USE_DEMO_DATA              # Set "true" to force demo mode

schedule:
  daily:  "0 8 * * *"
  weekly: "0 8 * * 1"

trigger_phrases:
  - "cash flow report"
  - "morning financial briefing"
  - "analyze my stripe finances"
  - "do I have enough to make payroll"
  - "should I take the stripe capital offer"
  - "how much capital do I need"
  - "fill the cash flow gap"
---

# Cash Flow Advisor v0.4 — MCP Mode + Stripe Capital

Pulls Stripe data via **Hermes Stripe MCP server**, loads fixed expenses from config.yaml,
builds a 30-day cash position projection, checks for available Capital offers, models the
repayment impact, and formats a clean text report. Since this skill runs
natively inside the Hermes Agent (which is an LLM itself), the agent acts
directly as the CFO to formulate the briefing commentary based on the script's
projected balance tables, shortfalls, and borrowing suggestions.

## What's new in v0.4

- **MCP-only architecture** — no direct Stripe API calls, no secret keys in skill
- Receives pre-fetched Stripe data via `--input` JSON from Hermes MCP tools
- Falls back to demo mode when no integrations configured
- Fetches available Stripe Capital financing offers via MCP
- Checks active financing summary (existing loans in repayment) via MCP
- Evaluates three gap resolution options ranked by cost:
    1. Instant payout (~1.5% fee, fully automated via API)
    2. Stripe Capital advance (flat fee, one dashboard click)
    3. Invoice acceleration (2% early-pay discount to customers)
- Projects the 30-day balance both WITHOUT and WITH Capital accepted
- Generates a dual-scenario matplotlib chart (base vs Capital)
  sent to Hermes Desktop preview pane via [[as_document]]
- Nemotron prompt updated to reason about Capital vs gap risk

## Important: What Capital can and cannot do via API

AUTOMATED (no human needed):
  - List available Capital offers        → `stripe.capital.FinancingOffer.list()` (via MCP)
  - Retrieve offer terms                 → `stripe.capital.FinancingOffer.retrieve()` (via MCP)
  - Check active financing summary       → `stripe.capital.FinancingSummary.retrieve()` (via MCP)
  - Model repayment impact on cash flow  → done in Python
  - Listen for payout confirmation       → `capital.financing_offer.paid_out` webhook

REQUIRES ONE USER ACTION:
  - Accepting the offer                  → `dashboard.stripe.com/capital` (one click)

This is by design. The agent handles all analysis and recommendation.
The human decides "yes/no" and clicks once. Funds land same day.

## Stripe MCP tool calls (Hermes native mode)

When running inside Hermes with Stripe MCP connected, the agent calls:

  stripe_retrieve_balance
  stripe_list_payouts          { status: "pending", limit: 20 }
  stripe_list_invoices         { status: "open", limit: 50 }
  stripe_list_subscriptions    { status: "all", limit: 100 }
  stripe_list_charges          { created: { gte: 30_days_ago }, limit: 100 }
  stripe_capital_financing_offers  { limit: 10 }
  stripe_capital_financing_summary { }

The collected JSON is passed to the analysis engine:
  python cashflow_advisor.py --input '{...}'

## Execution

Standalone (demo mode — no credentials needed):
  python cashflow_advisor.py             # auto-detects demo mode
  python cashflow_advisor.py --demo      # force demo data
  python cashflow_advisor.py --no-chart  # skip ASCII chart

Interactive Expense Management:
  python cashflow_advisor.py --list-expenses
  python cashflow_advisor.py --add-expense "Office Rent, 4500, 7, True, monthly"
  python cashflow_advisor.py --delete-expense "Office Rent"

Webhook Simulation:
  python cashflow_advisor.py --webhook '{"type": "capital.financing_offer.paid_out", "data": {...}}'

LLM-based Recurring Expense Detection:
  python cashflow_advisor.py --detect-expenses transactions.csv

MCP mode (Hermes passes pre-fetched Stripe data via --input):
  python cashflow_advisor.py --input '{...}'

Raw analysis only (no LLM, JSON output):
  python cashflow_advisor.py --analyze-only --output json

## Output

Terminal / Chat:
  The consolidated cash flow projection table, shortfall gaps, and resolution recommendations printed as structured text.

Saved Locally:
  Report saved to %USERPROFILE%\.hermes\cashflow\reports\[date].md
  Chart saved to %USERPROFILE%\.hermes\cashflow\charts\[date].png (if matplotlib is enabled)

## Scheduling

Daily at 8am:
  hermes schedule add "0 8 * * *" "run cashflow-advisor skill"

Weekly (Monday):
  hermes schedule add "0 8 * * 1" "run cashflow-advisor skill"

## What the output looks like

============================================================
💰 CASH FLOW & EXPENSE REPORT — 2026-06-28
============================================================

── CURRENT BALANCES ────────────────────────────────────────
  Available now:    $12,500.00
  Pending payout:   $22,000.00 (in Stripe pipeline)

── UPCOMING FIXED EXPENSES ─────────────────────────────────
  • AWS / Infrastructure                $  3,200.00   (due in 2 days, recurring)
  • Payroll — Bi-weekly                 $ 28,000.00   (due in 3 days, recurring)
  • SaaS Tools                          $    850.00   (due in 5 days, recurring)
  • Office Rent                         $  4,500.00   (due in 7 days, recurring)

── 30-DAY CASH FLOW PROJECTION ─────────────────────────────
  Date         | Net In       | Outflow      | Projected Balance 
  ------------------------------------------------------------
  2026-06-28   | $      0.00 | $      0.00 | $       12,500.00
  2026-06-30   | $  3,500.00 | $  3,200.00 | $       12,800.00
  2026-07-01   | $      0.00 | $ 28,000.00 | $      -15,200.00 🔴 CRITICAL GAP
  2026-07-02   | $ 22,000.00 | $      0.00 | $        6,800.00
    └─ [PAYOUT] Stripe payout: $22,000.00 (inflow)
  ...

── CRITICAL GAPS DETECTED ──────────────────────────────────
  ✗ 2026-07-01 (Day 3): shortage of -$15,200.00 (Due to: Payroll — Bi-weekly)
  ✗ 2026-07-15 (Day 17): shortage of -$18,550.00 (Due to: Payroll — Bi-weekly)

── FUNDING & LOAN SUGGESTIONS ──────────────────────────────
  We identified 3 resolution option(s) ranked by cost:

  1. [INSTANT_PAYOUT] Stripe instant payout
     Description:  Request $22,000 instant payout · fee: $330 · arrives within hours
     Cost:         $330.00 | COVERS GAP
     Action:       stripe.Payout.create(amount=None, currency='usd', method='instant')

  2. [INVOICE_ACCELERATION] Early-payment discount to customers
     Description:  Offer 2% discount on $18,500 outstanding invoices · costs $370
     Cost:         $370.00 | COVERS GAP
     Action:       Offer 2% early-pay discount to 2 customers

  3. [STRIPE_CAPITAL] Stripe Capital cash advance
     Description:  $25,000 advance · $2,500 flat fee (10.0%) · 12% repayment rate
     Cost:         $2,500.00 | COVERS GAP
     Action:       Accept at dashboard.stripe.com/capital · funds land same day
============================================================

The executing Hermes Agent LLM will read the report tables above and perform the following conversational actions in the chat:
1. **CFO Briefing**: Append a professional CFO Briefing under `── AI CFO BRIEFING (Hermes) ──` to analyze gap severities and recommend borrowing resolutions.
2. **Missing Expenses Query**: Actively ask the user in natural language if any unlisted expenses were missed, explaining that they can be registered via the chat using: `--add-expense "Description, Amount, DayOfMonth"`.
3. **Integration Setup Offer**: If the checklist reports any integrations as `DISABLED`, actively ask the user if they would like to enable QuickBooks, Xero, or Plaid in config.yaml.

## References

- `references/mcp-refactor-pattern.md` — How to refactor skills for MCP-only architecture (passes security scanner)