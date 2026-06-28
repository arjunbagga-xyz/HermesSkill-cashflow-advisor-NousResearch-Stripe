#!/usr/bin/env python3
"""
cashflow_advisor.py v0.3.0
Hermes Skill: cashflow-advisor

Pure analysis engine. No LLM calls — Hermes handles that via SKILL.md.
Outputs structured markdown that Hermes reads, then generates the briefing
using its own configured model (Nemotron Ultra).

Modes:
  (default)              Run full analysis, print markdown report
  --analyze-only         Output raw JSON for Hermes to process
  --save-expenses [text] Parse natural language expenses and save to config
  --demo                 Use built-in demo data (no Stripe key needed)
  --input [json]         Receive pre-fetched Stripe data from Hermes MCP
"""

import os, sys, json, argparse, yaml
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────────────────
MIN_BUFFER  = float(os.getenv("CASHFLOW_MIN_BUFFER", "5000"))
PROJ_DAYS   = int(os.getenv("CASHFLOW_PROJECTION_DAYS", "30"))
USE_DEMO    = os.getenv("USE_DEMO_DATA", "false").lower() == "true"
SKILL_DIR   = Path(__file__).parent
CONFIG_PATH = SKILL_DIR / "config.yaml"
REPORTS_DIR = Path.home() / ".hermes" / "cashflow" / "reports"
CHARTS_DIR  = Path.home() / ".hermes" / "cashflow" / "charts"


# ── Config helpers ─────────────────────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

def expenses_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("expenses"))

def load_expenses() -> tuple[list, list[str]]:
    """
    Load expenses from all active providers via the provider registry.
    Returns (expenses_list, source_summary).
    Falls back to config-only if providers package unavailable.
    """
    try:
        from providers import fetch_all_expenses
        return fetch_all_expenses(days_ahead=PROJ_DAYS)
    except ImportError:
        # providers package not available — fall back to config.yaml directly
        cfg    = load_config()
        today  = date.today()
        result = []
        for exp in cfg.get("expenses", []):
            dom = exp.get("day_of_month")
            if dom:
                target = today.replace(day=int(dom))
                if target <= today:
                    m = (today.month % 12) + 1
                    y = today.year + (1 if today.month == 12 else 0)
                    target = target.replace(year=y, month=m)
                due = (target - today).days
            else:
                due = exp.get("due_in_days", 30)
            result.append({
                "description": exp["description"],
                "amount":      int(float(exp["amount"]) * 100),
                "due_in_days": due,
                "recurring":   exp.get("recurring", True),
                "interval":    exp.get("interval", "monthly"),
            })
        return result, ["config (fallback)"]


# ── Expense parser (NLP → config) ─────────────────────────────────────────────
def parse_expenses_from_text(text: str) -> list:
    """
    Parse natural language expense descriptions into structured config objects.
    Called by Hermes after asking the user to describe their fixed expenses.

    Uses the NVIDIA NIM API if NVIDIA_API_KEY is set.
    Falls back to a simple heuristic parser if not.

    Returns a list of expense dicts ready to write to config.yaml.
    """
    api_key = os.getenv("NVIDIA_API_KEY")
    model   = os.getenv("NEMOTRON_MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1")

    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key,
            )
            prompt = f"""Parse these expense descriptions into structured JSON.
Return ONLY a valid JSON array — no preamble, no markdown fences.

Input: "{text}"

Each object must have:
  description   string   expense name
  amount        number   amount in USD (convert "28k" → 28000, "$4.5k" → 4500)
  day_of_month  integer  day of month it's due (1–28)
  recurring     boolean  true for repeating, false for one-off
  interval      string   "monthly" | "biweekly" | "weekly" | "once"

Rules:
- Biweekly payroll = TWO objects with different day_of_month values
- If a specific day isn't mentioned, use 1 for first-of-month expenses
- Ignore Stripe fees (we handle those automatically)

Example output for "payroll $28k twice a month on 1st and 15th, rent $4500 on 7th":
[
  {{"description":"Payroll","amount":28000,"day_of_month":1,"recurring":true,"interval":"biweekly"}},
  {{"description":"Payroll","amount":28000,"day_of_month":15,"recurring":true,"interval":"biweekly"}},
  {{"description":"Office Rent","amount":4500,"day_of_month":7,"recurring":true,"interval":"monthly"}}
]"""

            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)

        except Exception as e:
            print(f"⚠️  LLM parse failed ({e}), falling back to heuristic", file=sys.stderr)

    # ── Heuristic fallback (no API key) ───────────────────────────────────────
    # Simple pattern: looks for "$X" amounts and keywords
    import re
    expenses = []
    lines    = re.split(r'[,\n;]', text)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        amount_match = re.search(r'\$?([\d,]+\.?\d*)\s*k?\b', line, re.I)
        if not amount_match:
            continue
        raw_amt = amount_match.group(1).replace(",", "")
        amount  = float(raw_amt) * 1000 if 'k' in amount_match.group(0).lower() else float(raw_amt)
        day_match = re.search(r'\b(\d{1,2})(st|nd|rd|th)?\b', line)
        dom = int(day_match.group(1)) if day_match and 1 <= int(day_match.group(1)) <= 28 else 1
        recurring = not any(w in line.lower() for w in ["once", "one-off", "annual", "yearly"])
        interval  = "biweekly" if any(w in line.lower() for w in ["biweekly", "twice", "2x"]) else "monthly"
        desc_raw  = re.sub(r'\$[\d,\.]+k?\s*', '', line, flags=re.I).strip()
        desc      = desc_raw[:50] if desc_raw else "Expense"
        expenses.append({
            "description":  desc,
            "amount":       amount,
            "day_of_month": dom,
            "recurring":    recurring,
            "interval":     interval,
        })
    return expenses

def save_expenses(expenses: list):
    """Merge parsed expenses into config.yaml."""
    cfg = load_config()
    cfg.setdefault("expenses", [])
    cfg["expenses"] = expenses   # replace, not append
    save_config(cfg)
    print(f"✓ {len(expenses)} expense(s) saved to {CONFIG_PATH}")
    for e in expenses:
        print(f"  · {e['description']:<30} ${e['amount']:>10,.0f}  day {e['day_of_month']}")


# ── Demo data ──────────────────────────────────────────────────────────────────
def get_demo_data() -> dict:
    now = datetime.now()
    def ts(d): return int((now + timedelta(days=d)).timestamp())
    def ago(d): return int((now - timedelta(days=d)).timestamp())

    return {
        "balance": {
            "available": [{"amount": 1_250_000, "currency": "usd"}],
            "pending":   [{"amount": 2_200_000, "currency": "usd"}]
        },
        "payouts": [{
            "id": "po_demo_001", "amount": 2_200_000,
            "arrival_date": ts(4), "status": "pending", "currency": "usd"
        }],
        "charges": [
            {"amount": 299_900, "created": ago(1),  "status": "succeeded", "customer_email": "billing@acme.com"},
            {"amount": 149_900, "created": ago(2),  "status": "succeeded", "customer_email": "pay@globex.com"},
            {"amount": 499_900, "created": ago(3),  "status": "succeeded", "customer_email": "accounting@wayne.com"},
            {"amount": 299_900, "created": ago(5),  "status": "failed",    "customer_email": "billing@initech.com"},
            {"amount": 299_900, "created": ago(8),  "status": "succeeded", "customer_email": "finance@umbrella.com"},
            {"amount": 149_900, "created": ago(12), "status": "succeeded", "customer_email": "ops@vandelay.com"},
        ],
        "invoices": [
            {
                "id": "in_001", "amount_due": 1_500_000, "due_date": ts(8),
                "status": "open", "customer_email": "billing@nakatomi.com",
                "description": "Q2 Enterprise License — Nakatomi Corp"
            },
            {
                "id": "in_002", "amount_due": 350_000, "due_date": ts(2),
                "status": "open", "customer_email": "ap@cyberdyne.com",
                "description": "Professional Services — June"
            }
        ],
        "subscriptions": [
            {"id": "s1", "amount": 299_900, "current_period_end": ts(18), "status": "active",   "customer_email": "billing@acme.com"},
            {"id": "s2", "amount": 149_900, "current_period_end": ts(22), "status": "active",   "customer_email": "pay@globex.com"},
            {"id": "s3", "amount": 499_900, "current_period_end": ts(27), "status": "active",   "customer_email": "accounting@wayne.com"},
            {"id": "s4", "amount": 299_900, "current_period_end": ts(21), "status": "active",   "customer_email": "finance@umbrella.com"},
            {"id": "s5", "amount": 149_900, "current_period_end": ts(24), "status": "active",   "customer_email": "ops@vandelay.com"},
            {"id": "s6", "amount": 299_900, "current_period_end": ts(3),  "status": "past_due", "customer_email": "billing@initech.com"},
        ],
        # Demo expenses — normally come from config.yaml
        "expenses": [
            {"description": "AWS / Infrastructure",   "amount": 320_000,   "due_in_days": 2,  "recurring": True},
            {"description": "Payroll — Bi-weekly",    "amount": 2_800_000, "due_in_days": 3,  "recurring": True},
            {"description": "SaaS Tools",             "amount": 85_000,    "due_in_days": 5,  "recurring": True},
            {"description": "Office Rent",            "amount": 450_000,   "due_in_days": 7,  "recurring": True},
            {"description": "Annual Cyber Insurance", "amount": 700_000,   "due_in_days": 12, "recurring": False},
            {"description": "Payroll — Bi-weekly",    "amount": 2_800_000, "due_in_days": 17, "recurring": True},
        ],
        "capital_offers": [{
            "id": "fo_demo_001",
            "object": "capital.financing_offer",
            "status": "delivered",
            "offered_terms": {
                "advance_amount": 2_500_000,
                "fee_amount":       250_000,
                "withhold_rate":       0.12,
                "currency": "usd"
            },
            "financing_type": "cash_advance",
            "expires_at": int((datetime.now() + timedelta(days=14)).timestamp()),
        }],
        "active_financing": None,
    }


# ── Stripe fetch ───────────────────────────────────────────────────────────────
def fetch_stripe() -> dict:
    try:
        import stripe
    except ImportError:
        sys.exit("pip install stripe")

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

    balance  = stripe.Balance.retrieve()
    payouts  = list(stripe.Payout.list(limit=20, status="pending").auto_paging_iter())
    invoices = list(stripe.Invoice.list(status="open", limit=50).auto_paging_iter())
    subs     = list(stripe.Subscription.list(status="all", limit=100).auto_paging_iter())
    ago30    = int((datetime.now() - timedelta(days=30)).timestamp())
    charges  = list(stripe.Charge.list(created={"gte": ago30}, limit=100).auto_paging_iter())

    expenses, expense_sources = load_expenses()

    return {
        "balance":          dict(balance),
        "payouts":          [dict(p) for p in payouts],
        "invoices":         [dict(i) for i in invoices],
        "subscriptions":    [dict(s) for s in subs],
        "charges":          [dict(c) for c in charges],
        "expenses":         expenses,
        "expense_sources":  expense_sources,
        "capital_offers":   _fetch_capital_offers(stripe),
        "active_financing": _fetch_financing_summary(stripe),
    }

def _fetch_capital_offers(stripe_mod) -> list:
    try:
        offers = stripe_mod.capital.FinancingOffer.list(limit=10)
        return [dict(o) for o in offers.auto_paging_iter()
                if o.get("status") in ("undelivered", "delivered")]
    except Exception:
        try:
            import requests
            r = requests.get(
                "https://api.stripe.com/v1/capital/financing_offers",
                auth=(os.environ.get("STRIPE_SECRET_KEY", ""), ""),
                params={"limit": 10}, timeout=10
            )
            return [o for o in r.json().get("data", [])
                    if o.get("status") in ("undelivered", "delivered")] if r.ok else []
        except Exception:
            return []

def _fetch_financing_summary(stripe_mod) -> Optional[dict]:
    try:
        s = stripe_mod.capital.FinancingSummary.retrieve()
        return dict(s) if s and s.get("details") else None
    except Exception:
        return None

def generate_acceptance_link(connected_account_id: Optional[str] = None) -> str:
    """
    Generate a Stripe Account Link for Capital offer acceptance.
    - Connect platform: creates a fresh deep-link directly to the acceptance page
    - Direct account:   returns the dashboard URL (no Account Link API available)
    """
    account_id = connected_account_id or os.getenv("STRIPE_CONNECTED_ACCOUNT_ID")
    if not account_id:
        return "https://dashboard.stripe.com/capital"

    try:
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        link = stripe.AccountLink.create(
            account    = account_id,
            refresh_url= os.getenv("CAPITAL_REFRESH_URL", "https://yourplatform.com/capital/refresh"),
            return_url = os.getenv("CAPITAL_RETURN_URL",  "https://yourplatform.com/capital/accepted"),
            type       = "capital_financing_offer",
        )
        return link.url
    except Exception as e:
        print(f"ℹ️  Account Link unavailable ({e}) — using dashboard URL", file=sys.stderr)
        return "https://dashboard.stripe.com/capital"


# ── Analysis ───────────────────────────────────────────────────────────────────
def analyze(data: dict) -> dict:
    today     = date.today()
    available = data["balance"]["available"][0]["amount"] / 100
    pending_b = data["balance"]["pending"][0]["amount"]   / 100

    active          = data.get("active_financing")
    active_withhold = active["details"].get("withhold_rate", 0.0) if active and active.get("details") else 0.0

    events = []

    for p in data.get("payouts", []):
        arr = date.fromtimestamp(p["arrival_date"])
        if arr >= today:
            events.append({"date": str(arr), "type": "payout", "direction": "in",
                           "amount": round(p["amount"] / 100 * (1 - active_withhold), 2),
                           "label": "Stripe payout"})

    for inv in data.get("invoices", []):
        if inv.get("due_date"):
            due = date.fromtimestamp(inv["due_date"])
            if due >= today:
                events.append({"date": str(due), "type": "invoice", "direction": "in",
                               "amount": inv["amount_due"] / 100,
                               "label": inv.get("description", f"Invoice {inv['id']}"),
                               "customer": inv.get("customer_email", "")})

    for sub in data.get("subscriptions", []):
        renewal = date.fromtimestamp(sub["current_period_end"])
        if sub["status"] in ("active", "trialing") and today <= renewal <= today + timedelta(days=PROJ_DAYS):
            events.append({"date": str(renewal), "type": "subscription_renewal", "direction": "in",
                           "amount": round(sub["amount"] / 100 * (1 - active_withhold), 2),
                           "label": "Subscription renewal",
                           "customer": sub.get("customer_email", "")})
        elif sub["status"] == "past_due":
            events.append({"date": str(today), "type": "failed_payment", "direction": "risk",
                           "amount": sub["amount"] / 100,
                           "label": "Past-due subscription",
                           "customer": sub.get("customer_email", "")})

    for exp in data.get("expenses", []):
        due_date = today + timedelta(days=exp["due_in_days"])
        if due_date >= today:
            events.append({"date": str(due_date), "type": "expense", "direction": "out",
                           "amount": exp["amount"] / 100, "label": exp["description"],
                           "recurring": exp.get("recurring", False)})

    events.sort(key=lambda e: e["date"])

    daily_positions, gaps = [], []
    running = available

    for i in range(PROJ_DAYS):
        day     = today + timedelta(days=i)
        day_str = str(day)
        day_evts = [e for e in events if e["date"] == day_str]
        day_in   = sum(e["amount"] for e in day_evts if e["direction"] == "in")
        day_out  = sum(e["amount"] for e in day_evts if e["direction"] == "out")
        running  = round(running + day_in - day_out, 2)

        daily_positions.append({
            "date": day_str, "balance": running,
            "in": round(day_in, 2), "out": round(day_out, 2),
            "events": day_evts,
        })

        if running < 0:
            gaps.append({"date": day_str, "shortfall": round(abs(running), 2), "severity": "critical"})
        elif running < MIN_BUFFER:
            gaps.append({"date": day_str, "balance": running, "severity": "warning"})

    at_risk   = sum(e["amount"] for e in events if e["direction"] == "risk")
    min_bal   = min(p["balance"] for p in daily_positions)
    critical  = [g for g in gaps if g["severity"] == "critical"]
    risk_score = 90 if critical else (55 if gaps else max(0, int(20 - (min_bal / MIN_BUFFER) * 20)))

    succeeded      = [c for c in data.get("charges", []) if c.get("status") == "succeeded"]
    avg_daily_vol  = sum(c["amount"] / 100 for c in succeeded) / 30 if succeeded else 500.0

    return {
        "as_of":                 str(today),
        "current_balance":       round(available, 2),
        "pending_payout":        round(pending_b, 2),
        "min_projected_balance": round(min_bal, 2),
        "total_inflow_30d":      round(sum(p["in"]  for p in daily_positions), 2),
        "total_outflow_30d":     round(sum(p["out"] for p in daily_positions), 2),
        "at_risk_revenue":       round(at_risk, 2),
        "risk_score":            risk_score,
        "critical_gaps":         gaps,
        "upcoming_events":       events[:25],
        "daily_positions":       daily_positions,
        "avg_daily_stripe_vol":  round(avg_daily_vol, 2),
        "active_financing":      active,
        "expenses_configured":   bool(data.get("expenses")),
        "expense_sources":       data.get("expense_sources", []),
    }


# ── Capital analysis ───────────────────────────────────────────────────────────
def analyze_capital_options(data: dict, analysis: dict) -> dict:
    offers    = data.get("capital_offers", [])
    gaps      = [g for g in analysis["critical_gaps"] if g["severity"] == "critical"]
    pending   = analysis["pending_payout"]
    avg_vol   = analysis["avg_daily_stripe_vol"]
    today     = date.today()

    first_gap  = gaps[0] if gaps else None
    gap_amount = first_gap["shortfall"] if first_gap else 0

    options = []

    # 1. Instant payout
    if pending > 0:
        fee = round(max(2.0, pending * 0.015), 2)
        options.append({
            "type": "instant_payout", "label": "Stripe instant payout",
            "available": pending, "cost": fee,
            "covers_gap": pending >= gap_amount,
            "gap_surplus": round(pending - gap_amount, 2),
            "can_automate": True,
            "description": f"${pending:,.0f} instant payout · ${fee:.2f} fee · arrives in hours",
        })

    # 2. Stripe Capital
    capital_analyses = []
    for offer in offers:
        terms       = offer.get("offered_terms", {})
        advance     = terms.get("advance_amount", 0) / 100
        fee         = terms.get("fee_amount", 0)     / 100
        withhold    = terms.get("withhold_rate", 0.10)
        total_repay = advance + fee
        daily_impact = round(avg_vol * withhold, 2)
        est_days    = round(total_repay / daily_impact) if daily_impact else 999
        fee_pct     = round(fee / advance * 100, 1) if advance else 0
        expires     = offer.get("expires_at")
        days_left   = round((expires - datetime.now().timestamp()) / 86400) if expires else None

        ca = {
            "offer_id": offer["id"], "type": "stripe_capital",
            "label": "Stripe Capital cash advance",
            "advance": advance, "fee": fee, "fee_pct": fee_pct,
            "total_repayment": total_repay,
            "withhold_rate": withhold,
            "daily_repayment_impact": daily_impact,
            "est_days_to_repay": est_days,
            "covers_gap": advance >= gap_amount,
            "gap_surplus": round(advance - gap_amount, 2),
            "expires_in_days": days_left,
            "can_automate": False,
            "cost": fee,
            "description": (
                f"${advance:,.0f} advance · ${fee:,.0f} flat fee ({fee_pct}%) · "
                f"{withhold*100:.0f}% repayment rate · ~${daily_impact:,.2f}/day withheld"
            ),
        }
        capital_analyses.append(ca)
        options.append(ca)

    # 3. Invoice acceleration
    future_invoices = [
        e for e in analysis["upcoming_events"]
        if e["direction"] == "in" and e["type"] == "invoice"
        and e.get("date", "") > str(today)
    ]
    if future_invoices:
        early_pay_pct  = float(load_config().get("early_pay_discount_pct", 2))
        accel_total    = sum(e["amount"] for e in future_invoices[:3])
        discount_cost  = round(accel_total * (early_pay_pct / 100), 2)
        options.append({
            "type": "invoice_acceleration", "label": "Early-pay discount to customers",
            "available": accel_total, "cost": discount_cost,
            "covers_gap": accel_total >= gap_amount,
            "gap_surplus": round(accel_total - gap_amount, 2),
            "can_automate": False,
            "description": (
                f"Offer {early_pay_pct:.0f}% discount on "
                f"${accel_total:,.0f} outstanding invoices · costs ${discount_cost:,.0f}"
            ),
        })

    options.sort(key=lambda o: (not o["covers_gap"], o.get("cost", 9999)))

    # Capital repayment projection
    capital_projection = None
    if capital_analyses:
        best = capital_analyses[0]
        capital_projection = _project_with_capital(
            analysis["daily_positions"],
            analysis["current_balance"],
            best["advance"],
            best["withhold_rate"],
        )

    return {
        "has_gaps":           bool(gaps),
        "first_gap":          first_gap,
        "gap_amount":         gap_amount,
        "options":            options,
        "capital_offers":     capital_analyses,
        "capital_projection": capital_projection,
        "recommended":        options[0] if options else None,
    }

def _project_with_capital(
    base_positions: list, current_balance: float,
    advance: float, withhold_rate: float
) -> list:
    projected = []
    running   = current_balance + advance
    to_repay  = advance
    repaid    = 0.0

    for pos in base_positions:
        withheld  = min(pos["in"] * withhold_rate, to_repay - repaid) if repaid < to_repay else 0.0
        repaid   += withheld
        running   = round(running + (pos["in"] - withheld) - pos["out"], 2)
        projected.append({
            "date": pos["date"], "balance": running,
            "in": round(pos["in"] - withheld, 2),
            "out": pos["out"], "withheld": round(withheld, 2),
        })

    return projected


# ── Chart ──────────────────────────────────────────────────────────────────────
def generate_chart(analysis: dict, capital_data: dict) -> Optional[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        return None

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    positions = analysis["daily_positions"]
    labels    = [p["date"][5:] for p in positions]
    balances  = [p["balance"]  for p in positions]
    cap_proj  = capital_data.get("capital_projection")
    cap_bals  = [p["balance"] for p in cap_proj] if cap_proj else None

    BG, CARD  = "#0B0F1A", "#111827"
    G, AM, RD = "#639922", "#EF9F27", "#E24B4A"
    BL, MUTED = "#5B8EE6", "#888780"
    TEXT      = "#C8C4BC"

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(CARD)
    xs = list(range(len(labels)))

    ax.axhline(0,          color=RD,   lw=0.8, ls="--", alpha=0.6)
    ax.axhline(MIN_BUFFER, color=AM,   lw=0.8, ls="--", alpha=0.6)
    ax.fill_between(xs, balances, 0,
                    where=[b < 0 for b in balances],
                    color=RD, alpha=0.10, interpolate=True)

    for i in range(len(balances) - 1):
        v = balances[i]
        c = RD if v < 0 else (AM if v < MIN_BUFFER else G)
        ax.plot([xs[i], xs[i+1]], [balances[i], balances[i+1]], color=c, lw=2.2)

    if cap_bals:
        ax.plot(xs, cap_bals, color=BL, lw=2.0, alpha=0.9, label="With Capital")
        ax.fill_between(xs, cap_bals, balances,
                        where=[c > b for c, b in zip(cap_bals, balances)],
                        color=BL, alpha=0.07, interpolate=True)

    tick_idx = list(range(0, len(labels), 5))
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([labels[i] for i in tick_idx], color=MUTED, fontsize=9)
    ax.tick_params(colors=MUTED)
    for sp in ax.spines.values(): sp.set_edgecolor("#222")
    ax.grid(axis="y", color="#1e2433", lw=0.7)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"-${abs(v)/1000:.0f}k" if v < 0 else f"${v/1000:.0f}k")
    )

    handles = [mpatches.Patch(color=G,  label="Base projection")]
    if cap_bals: handles.append(mpatches.Patch(color=BL, label="With Capital"))
    ax.legend(handles=handles, facecolor="#111827", edgecolor="#333",
              labelcolor=TEXT, fontsize=9, loc="upper right")

    title = f"30-Day Cash Flow · {analysis['as_of']}"
    if capital_data.get("capital_offers"):
        o = capital_data["capital_offers"][0]
        title += f"   (Capital offer: ${o['advance']:,.0f} available)"
    ax.set_title(title, color=TEXT, fontsize=11, pad=10)
    plt.tight_layout()

    path = CHARTS_DIR / f"{analysis['as_of']}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    return path


# ── Markdown output (for Hermes chat pane) ────────────────────────────────────
def render_markdown(analysis: dict, capital_data: dict, acceptance_link: str) -> str:
    """
    Clean markdown output for Hermes chat pane.
    Hermes renders this as formatted text — no ANSI codes.
    """
    today   = analysis["as_of"]
    score   = analysis["risk_score"]
    status  = "🔴 Critical" if score >= 70 else ("🟡 Watch" if score >= 40 else "🟢 Healthy")
    lines   = []
    a       = lines.append

    a(f"## 💰 Cash Flow Briefing · {today}")
    a(f"**Status:** {status} · Risk score {score}/100")
    if "expense_sources" in analysis:
        sources = analysis.get("expense_sources", [])
        if sources:
            a(f"**Expense sources:** {' · '.join(sources)}")
    a("")

    # Position
    a("### Position")
    a("| | |")
    a("|---|---|")
    a(f"| Available now | **${analysis['current_balance']:,.0f}** |")
    a(f"| Pending payout | ${analysis['pending_payout']:,.0f} *(arrives in ~4 days)* |")
    a(f"| 30-day projected low | {'**' if analysis['min_projected_balance'] < 0 else ''}${analysis['min_projected_balance']:,.0f}{'**' if analysis['min_projected_balance'] < 0 else ''} |")
    a(f"| 30-day inflow | ${analysis['total_inflow_30d']:,.0f} |")
    a(f"| 30-day outflow | ${analysis['total_outflow_30d']:,.0f} |")
    if analysis["at_risk_revenue"] > 0:
        a(f"| At-risk MRR | ⚠️ ${analysis['at_risk_revenue']:,.0f} *(past-due)* |")
    a("")

    # Gaps
    critical = [g for g in analysis["critical_gaps"] if g["severity"] == "critical"]
    warnings = [g for g in analysis["critical_gaps"] if g["severity"] == "warning"]
    if critical or warnings:
        a("### ⚠️ Cash Flow Gaps")
        a("| Day | Date | Event | Gap |")
        a("|---|---|---|---|")
        today_date = date.today()
        for g in (critical + warnings)[:6]:
            gap_day = (date.fromisoformat(g["date"]) - today_date).days
            evts    = [e for e in analysis["upcoming_events"]
                       if e["date"] == g["date"] and e["direction"] == "out"]
            label   = evts[0]["label"] if evts else "Multiple expenses"
            sev     = "🔴" if g["severity"] == "critical" else "🟡"
            amount  = f"-${g['shortfall']:,.0f}" if g["severity"] == "critical" else f"${g['balance']:,.0f}"
            a(f"| {sev} Day {gap_day} | {g['date']} | {label} | {amount} |")
        a("")

    # Capital
    if capital_data.get("capital_offers"):
        o       = capital_data["capital_offers"][0]
        cap_min = min(p["balance"] for p in capital_data["capital_projection"]) \
                  if capital_data.get("capital_projection") else None

        a("### 💳 Stripe Capital Offer Available")
        a("| | |")
        a("|---|---|")
        a(f"| Advance | **${o['advance']:,.0f}** |")
        a(f"| Flat fee | ${o['fee']:,.0f} *({o['fee_pct']}% · no interest, no compounding)* |")
        a(f"| Repayment | {o['withhold_rate']*100:.0f}% withheld from each Stripe transaction |")
        a(f"| Daily impact | −${o['daily_repayment_impact']:,.2f}/day from Stripe payouts |")
        a(f"| Est. repayment | ~{o['est_days_to_repay']} days at current volume |")
        if o.get("expires_in_days"):
            a(f"| Offer expires | {o['expires_in_days']} days |")
        a("")
        if cap_min is not None:
            a(f"**If accepted today:** balance becomes "
              f"${analysis['current_balance'] + o['advance']:,.0f} · "
              f"30-day low improves from "
              f"${analysis['min_projected_balance']:,.0f} → ${cap_min:,.0f}")
            a("")
        a(f"**→ [Accept this offer]({acceptance_link})**")
        a("")

    # Upcoming events
    a("### Upcoming Events")
    a("| Date | | Description | Amount |")
    a("|---|---|---|---|")
    today_date = date.today()
    for e in analysis["upcoming_events"][:10]:
        day  = (date.fromisoformat(e["date"]) - today_date).days
        icon = "🟢" if e["direction"] == "in" else ("🔴" if e["direction"] == "out" else "⚠️")
        sign = "+" if e["direction"] == "in" else ("-" if e["direction"] == "out" else "?")
        a(f"| Day {day} | {icon} | {e['label']} | {sign}${e['amount']:,.0f} |")
    a("")

    # Options
    if capital_data.get("options"):
        a("### Resolution Options *(ranked by cost)*")
        for i, opt in enumerate(capital_data["options"][:3]):
            covered = "✅ covers gap" if opt["covers_gap"] else "⚠️ partial"
            auto    = "automated" if opt["can_automate"] else "1 action required"
            a(f"{i+1}. **{opt['label']}** — {opt['description']} · {covered} · {auto}")
        a("")

    # Expenses warning
    if not analysis.get("expenses_configured"):
        a("---")
        a("⚠️ **No fixed expenses configured.** The projection above only includes Stripe "
          "activity. Tell me your payroll, rent, and recurring bills and I'll factor them in.")

    return "\n".join(lines)


# ── Save ───────────────────────────────────────────────────────────────────────
def save_report(md: str, analysis: dict, capital_data: dict, chart_path: Optional[Path]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{analysis['as_of']}.md"
    img  = f"![chart]({chart_path})\n\n" if chart_path else ""
    path.write_text(
        f"{img}{md}\n\n---\n\n"
        f"```json\n{json.dumps({'analysis': analysis, 'capital': capital_data}, indent=2)}\n```\n"
    )
    return path


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Cash Flow Advisor v0.3")
    parser.add_argument("--demo",          action="store_true")
    parser.add_argument("--analyze-only",  action="store_true", help="Output raw JSON")
    parser.add_argument("--no-chart",      action="store_true")
    parser.add_argument("--input",         type=str, help="Pre-fetched Stripe JSON (MCP mode)")
    parser.add_argument("--save-expenses", type=str, metavar="TEXT",
                        help="Parse natural language expenses and save to config.yaml")
    args = parser.parse_args()

    # Expense elicitation mode
    if args.save_expenses:
        expenses = parse_expenses_from_text(args.save_expenses)
        if not expenses:
            print("Could not parse any expenses from that text. Try again with amounts and dates.")
            sys.exit(1)
        save_expenses(expenses)
        return

    # Data source
    if args.input:
        raw = json.loads(args.input)
        raw.setdefault("expenses", load_expenses())
        raw.setdefault("capital_offers", [])
        raw.setdefault("active_financing", None)
        data = raw
    elif args.demo or USE_DEMO or not os.getenv("STRIPE_SECRET_KEY"):
        data = get_demo_data()
    else:
        data = fetch_stripe()

    # Warn if no expenses configured (non-demo)
    if not args.demo and not USE_DEMO and not data.get("expenses"):
        print("NO_EXPENSES_CONFIGURED")   # Hermes reads this and triggers elicitation
        return

    # Analyze
    analysis     = analyze(data)
    capital_data = analyze_capital_options(data, analysis)

    if args.analyze_only:
        print(json.dumps({"analysis": analysis, "capital": capital_data}, indent=2))
        return

    # Chart
    chart_path = generate_chart(analysis, capital_data) if not args.no_chart else None

    # Acceptance link
    acceptance_link = generate_acceptance_link()

    # Markdown output (Hermes renders this in chat)
    md = render_markdown(analysis, capital_data, acceptance_link)
    print(md)

    if chart_path:
        print(f"\n{chart_path} [[as_document]]")

    # Save
    path = save_report(md, analysis, capital_data, chart_path)
    print(f"\n*Report saved: {path}*", file=sys.stderr)


if __name__ == "__main__":
    main()
