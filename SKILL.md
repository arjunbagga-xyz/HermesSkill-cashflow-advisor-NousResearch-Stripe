---
name: cashflow-advisor
version: 0.3.0
description: >
  Daily or weekly SMB cash flow briefing with Stripe Capital integration.
  Detects gaps, evaluates Capital offers, generates an acceptance link,
  and re-projects the 30-day balance post-funding. Asks for fixed expenses
  in plain English on first run and remembers them.
author: arjun
license: MIT
tags: [finance, stripe, stripe-capital, cash-flow, smb, scheduling]

requires_mcp:
  - stripe

env:
  required: []
  optional:
    - STRIPE_SECRET_KEY              # Omit for demo mode
    - CASHFLOW_MIN_BUFFER            # Warn threshold, default 5000
    - CASHFLOW_PROJECTION_DAYS       # Default 30
    - USE_DEMO_DATA                  # "true" to force demo
    - STRIPE_CONNECTED_ACCOUNT_ID    # For Connect platforms — enables deep acceptance link
    - CAPITAL_REFRESH_URL            # Connect platform redirect on link expiry
    - CAPITAL_RETURN_URL             # Connect platform redirect after acceptance

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
  - "what are my upcoming expenses"
---

# Cash Flow Advisor v0.3

You are running the Cash Flow Advisor skill. Follow these steps in order.
Do not skip steps. Do not proceed to the next step until the current one is
complete.

---

## Step 0 — Check expenses are configured

Run:
```
python cashflow_advisor.py --analyze-only --demo
```

Check the `expenses_configured` field in the JSON output.

**If `expenses_configured` is false AND this is not demo mode:**

Ask the user exactly this:

> Before I can give you a complete picture, I need to know your fixed
> expenses — things like payroll, rent, and recurring bills that don't
> go through Stripe. Describe them in plain English and I'll save them.
>
> Example: *"Payroll is $28k twice a month on the 1st and 15th, rent
> $4,500 on the 7th, AWS about $3,200 monthly."*

Wait for their response. Then run:
```
python cashflow_advisor.py --save-expenses "[their response verbatim]"
```

The script will parse the text using Nemotron, write the expenses to
`config.yaml`, and confirm what was saved. Show the user the confirmation.

After saving, continue to Step 1.

**If `expenses_configured` is true:** skip to Step 1 immediately.

---

## Step 1 — Fetch Stripe data

**If `STRIPE_SECRET_KEY` is set**, use Stripe MCP tools:

```
stripe_retrieve_balance
stripe_list_payouts          { status: "pending", limit: 20 }
stripe_list_invoices         { status: "open", limit: 50 }
stripe_list_subscriptions    { status: "all", limit: 100 }
stripe_list_charges          { created: { gte: 30_days_ago }, limit: 100 }
```

Also fetch Capital data (direct API if MCP doesn't expose it):
```
GET /v1/capital/financing_offers     → available offers
GET /v1/capital/financing_summary    → active loan repayment status
```

Pass the collected JSON to the analysis engine:
```
python cashflow_advisor.py --input '[json string]'
```

**If `STRIPE_SECRET_KEY` is not set**, run in demo mode:
```
python cashflow_advisor.py --demo
```

---

## Step 2 — Run analysis and render output

The script prints markdown directly to stdout. Capture it and display it
in the chat pane. Hermes renders it as formatted text automatically.

If the script prints `NO_EXPENSES_CONFIGURED`, return to Step 0.

If the script emits a line ending in `[[as_document]]`, route that file
path to the preview pane as a document.

---

## Step 3 — Generate briefing

Using the markdown output from Step 2 as context, generate a sharp CFO-style
briefing. Use your own judgment and Nemotron's reasoning capabilities.

Structure:
- **Status line** (🟢 / 🟡 / 🔴) with one sentence summary
- **Position** — specific numbers, most urgent fact first
- **Capital decision** — if an offer is available, be decisive: state the
  advance amount, flat fee, whether it covers the gap, and give one clear
  instruction. Compare the fee to the cost of missing payroll.
- **Actions** — numbered 1–3 in urgency order. If Capital is recommended,
  action 1 is the acceptance link from the markdown output.
- **Outlook** — one sentence on what the 30-day position looks like if
  action 1 is taken today.

Do not repeat the tables already shown. The briefing goes after the
structured markdown, not instead of it.

---

## Step 4 — Handle follow-up

Common follow-ups and how to handle them:

**"Add/update my expenses"**
Ask the user to describe the change, then run:
```
python cashflow_advisor.py --save-expenses "[new description]"
```

**"What if I take the Capital offer?"**
The capital projection is already in the markdown output (`capital_projection`
in the JSON). Summarise how the 30-day balance changes with Capital accepted.

**"Show me the chart"**
The chart was already sent to the preview pane. If the user missed it,
re-emit the chart path with `[[as_document]]`.

**"Run the analysis again"**
Restart from Step 1.

---

## Scheduling

Register daily at 8am:
```
hermes schedule add "0 8 * * *" "run cashflow-advisor skill"
```

Weekly (Monday mornings):
```
hermes schedule add "0 8 * * 1" "run cashflow-advisor skill"
```

---

## Capital API: what is and isn't automated

| Step | Automated? | How |
|------|-----------|-----|
| Detect gap | ✅ Yes | 30-day projection |
| Fetch Capital offer | ✅ Yes | Stripe API |
| Evaluate offer vs gap | ✅ Yes | Python + Nemotron |
| Generate acceptance link | ✅ Yes | `stripe.AccountLink.create()` (Connect) or dashboard URL |
| **Accept the offer** | **❌ One click** | **User action — intentional** |
| Confirm funds landed | ✅ Yes | `capital.financing_offer.paid_out` webhook |

The human in the loop on acceptance is intentional. Agents should not
autonomously take out loans. Everything else is handled.

---

## Files

| File | Purpose |
|------|---------|
| `cashflow_advisor.py` | Analysis engine, expense parser, Capital logic, chart, markdown output |
| `SKILL.md` | This file — Hermes execution instructions |
| `config.yaml` | User config — expenses (auto-populated), schedule, thresholds |
