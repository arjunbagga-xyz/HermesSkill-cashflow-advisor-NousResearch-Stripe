#!/usr/bin/env python3
"""
cashflow_advisor.py v0.4.0
Hermes Skill: cashflow-advisor

30-day cash flow projection with Stripe Capital integration.
Detects gaps, evaluates Capital offers, models repayment impact,
generates acceptance links, and listens for payout confirmation.

MCP MODE (primary): Receives pre-fetched Stripe data via --input JSON
DEMO MODE (fallback): Runs on built-in scenario data
"""

import os, sys, json, argparse, yaml
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional
from abc import ABC, abstractmethod

# Reconfigure stdout/stderr to UTF-8 on Windows to support emojis/Unicode
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Config ─────────────────────────────────────────────────────────────────────
SKILL_DIR   = Path(__file__).parent
CONFIG_PATH = SKILL_DIR / "config.yaml"

def _load_config_values():
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass
    return cfg

_cfg = _load_config_values()
alerts_cfg = _cfg.get("alerts", {})

MIN_BUFFER  = float(os.getenv("CASHFLOW_MIN_BUFFER", alerts_cfg.get("minimum_buffer", 5000)))
PROJ_DAYS   = int(os.getenv("CASHFLOW_PROJECTION_DAYS", alerts_cfg.get("projection_days", 30)))
EARLY_PAY_DISCOUNT_PCT = float(alerts_cfg.get("early_pay_discount_pct", 2.0))
# Probability that a customer accepts early-pay discount (configurable)
EARLY_PAY_ACCEPTANCE_RATE = float(alerts_cfg.get("early_pay_acceptance_rate", 0.35))
USE_DEMO    = os.getenv("USE_DEMO_DATA", "false").lower() == "true" or _cfg.get("stripe", {}).get("use_demo", False)

REPORTS_DIR = Path.home() / ".hermes" / "cashflow" / "reports"


# ── Demo Data ──────────────────────────────────────────────────────────────────
# Scenario: 12-person SaaS startup. Payroll in 3 days. Payout in 4.
# A $25,000 Capital offer is available. The skill should recommend it.

def get_demo_data() -> dict:
    now = datetime.now()
    def ts(d): return int((now + timedelta(days=d)).timestamp())
    def ago(d): return int((now - timedelta(days=d)).timestamp())

    return {
        "balance": {
            "available": [{"amount": 1_250_000, "currency": "usd"}],   # $12,500
            "pending":   [{"amount": 2_200_000, "currency": "usd"}]    # $22,000
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
                "id": "in_demo_001", "amount_due": 1_500_000, "due_date": ts(8),
                "status": "open", "customer_email": "billing@nakatomi.com",
                "description": "Q2 Enterprise License — Nakatomi Corp"
            },
            {
                "id": "in_demo_002", "amount_due": 350_000, "due_date": ts(2),
                "status": "open", "customer_email": "ap@cyberdyne.com",
                "description": "Professional Services — June"
            }
        ],
        "subscriptions": [
            {"id": "sub_001", "amount": 299_900, "current_period_end": ts(18), "status": "active",   "customer_email": "billing@acme.com"},
            {"id": "sub_002", "amount": 149_900, "current_period_end": ts(22), "status": "active",   "customer_email": "pay@globex.com"},
            {"id": "sub_003", "amount": 499_900, "current_period_end": ts(27), "status": "active",   "customer_email": "accounting@wayne.com"},
            {"id": "sub_004", "amount": 299_900, "current_period_end": ts(21), "status": "active",   "customer_email": "finance@umbrella.com"},
            {"id": "sub_005", "amount": 149_900, "current_period_end": ts(24), "status": "active",   "customer_email": "ops@vandelay.com"},
            {"id": "sub_006", "amount": 299_900, "current_period_end": ts(3),  "status": "past_due", "customer_email": "billing@initech.com"},
        ],
        "expenses": [
            {"description": "AWS / Infrastructure",    "amount": 320_000,   "due_in_days": 2,  "recurring": True},
            {"description": "Payroll — Bi-weekly",     "amount": 2_800_000, "due_in_days": 3,  "recurring": True},
            {"description": "SaaS Tools",              "amount": 85_000,    "due_in_days": 5,  "recurring": True},
            {"description": "Office Rent",             "amount": 450_000,   "due_in_days": 7,  "recurring": True},
            {"description": "Annual Cyber Insurance",  "amount": 700_000,   "due_in_days": 12, "recurring": False},
            {"description": "Payroll — Bi-weekly",     "amount": 2_800_000, "due_in_days": 17, "recurring": True},
        ],
        # ── Capital ──────────────────────────────────────────────────────────
        # Stripe has pre-approved a $25k advance. User hasn't accepted yet.
        "capital_offers": [{
            "id": "fo_demo_001",
            "object": "capital.financing_offer",
            "status": "delivered",
            "offered_terms": {
                "advance_amount": 2_500_000,   # $25,000
                "fee_amount":       250_000,   # $2,500 flat fee (10%)
                "withhold_rate":       0.12,   # 12% of each Stripe transaction
                "currency": "usd"
            },
            "financing_type": "cash_advance",
            "expires_at": int((datetime.now() + timedelta(days=14)).timestamp()),
        }],
        "active_financing": None,   # no current loan in repayment
    }


def _load_config_expenses() -> list:
    if not CONFIG_PATH.exists():
        return []
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        if not cfg or not isinstance(cfg, dict):
            print("⚠️  Config file is empty or invalid format.", file=sys.stderr)
            return []
    except yaml.YAMLError as ye:
        print(f"❌  Error parsing config.yaml: {ye}. Returning empty expenses list.", file=sys.stderr)
        return []
    except Exception as e:
        print(f"❌  Failed to load config: {e}. Returning empty expenses list.", file=sys.stderr)
        return []

    today = date.today()
    out = []
    for exp in (cfg.get("expenses") or []):
        if not exp or not isinstance(exp, dict):
            continue
        dom = exp.get("day_of_month")
        if dom:
            try:
                target = today.replace(day=dom)
                if target < today:
                    m = (today.month % 12) + 1
                    y = today.year + (1 if today.month == 12 else 0)
                    target = target.replace(year=y, month=m)
                due = (target - today).days
            except ValueError:
                due = exp.get("due_in_days", 30)
        else:
            due = exp.get("due_in_days", 30)
        out.append({
            "description": exp.get("description", "Unnamed Expense"),
            "amount":      int(exp.get("amount", 0) * 100),
            "due_in_days": due,
            "recurring":   exp.get("recurring", True),
        })
    return out


# ── Data Provider Abstractions ───────────────────────────────────────────────
class InflowProvider(ABC):
    @abstractmethod
    def fetch_inflows(self, config: dict) -> dict:
        pass

class OutflowProvider(ABC):
    @abstractmethod
    def fetch_outflows(self, config: dict) -> list:
        pass

class LocalConfigProvider(OutflowProvider):
    def fetch_outflows(self, config: dict) -> list:
        return _load_config_expenses()

class QuickBooksProvider(InflowProvider, OutflowProvider):
    def fetch_inflows(self, config: dict) -> dict:
        qb_cfg = config.get("integrations", {}).get("quickbooks", {})
        if not qb_cfg or not qb_cfg.get("enabled"):
            return {}
        print("🔗 QuickBooks integration enabled — loading invoices...", file=sys.stderr)
        # Mock/Demo data for QuickBooks Invoice
        return {
            "invoices": [{
                "id": "qb_inv_001",
                "amount_due": 850000,  # $8,500
                "due_date": int((datetime.now() + timedelta(days=12)).timestamp()),
                "status": "open",
                "customer_email": "accounting@starkindustries.com",
                "description": "QuickBooks Invoice — Stark Industries Consulting"
            }]
        }

    def fetch_outflows(self, config: dict) -> list:
        qb_cfg = config.get("integrations", {}).get("quickbooks", {})
        if not qb_cfg or not qb_cfg.get("enabled"):
            return []
        print("🔗 QuickBooks integration enabled — loading bills...", file=sys.stderr)
        # Mock/Demo data for QuickBooks Bills
        return [{
            "description": "QuickBooks Bill — Stark Tower Maintenance",
            "amount": 250000,  # $2,500
            "due_in_days": 10,
            "recurring": True
        }]

class XeroProvider(InflowProvider, OutflowProvider):
    def fetch_inflows(self, config: dict) -> dict:
        xero_cfg = config.get("integrations", {}).get("xero", {})
        if not xero_cfg or not xero_cfg.get("enabled"):
            return {}
        print("🔗 Xero integration enabled — loading invoices...", file=sys.stderr)
        # Mock/Demo data for Xero Invoice
        return {
            "invoices": [{
                "id": "xero_inv_001",
                "amount_due": 420000,  # $4,200
                "due_date": int((datetime.now() + timedelta(days=15)).timestamp()),
                "status": "open",
                "customer_email": "ap@oscorp.com",
                "description": "Xero Invoice — Oscorp R&D Services"
            }]
        }

    def fetch_outflows(self, config: dict) -> list:
        xero_cfg = config.get("integrations", {}).get("xero", {})
        if not xero_cfg or not xero_cfg.get("enabled"):
            return []
        print("🔗 Xero integration enabled — loading accounts payable...", file=sys.stderr)
        # Mock/Demo data for Xero Bills
        return [{
            "description": "Xero Bill — OsCorp Raw Materials",
            "amount": 120000,  # $1,200
            "due_in_days": 14,
            "recurring": False
        }]

class PlaidProvider(OutflowProvider):
    def fetch_outflows(self, config: dict) -> list:
        plaid_cfg = config.get("integrations", {}).get("plaid", {})
        if not plaid_cfg or not plaid_cfg.get("enabled"):
            return []
        print("🔗 Plaid bank feed enabled — loading recurring outflows...", file=sys.stderr)
        # Mock/Demo data for Plaid detected recurring outflows
        return [{
            "description": "Plaid Bank Feed — Recurring Utilities (Comcast)",
            "amount": 35000,  # $350
            "due_in_days": 8,
            "recurring": True
        }]

class DataSourceManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.inflow_providers = []
        self.outflow_providers = []
        self.config = self._load_config()
        self._register_providers()

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _register_providers(self):
        # Always register local YAML expenses
        self.outflow_providers.append(LocalConfigProvider())

        # If integrations config is enabled, add others
        ints = self.config.get("integrations", {})
        if ints:
            if ints.get("quickbooks", {}).get("enabled"):
                qb = QuickBooksProvider()
                self.inflow_providers.append(qb)
                self.outflow_providers.append(qb)
            if ints.get("xero", {}).get("enabled"):
                x = XeroProvider()
                self.inflow_providers.append(x)
                self.outflow_providers.append(x)
            if ints.get("plaid", {}).get("enabled"):
                self.outflow_providers.append(PlaidProvider())

    def fetch_all(self, use_demo: bool = False) -> dict:
        """
        Merge all data sources.
        """
        if use_demo:
            return get_demo_data()

        # If no integrations enabled, default to demo mode
        ints = self.config.get("integrations", {})
        has_integrations = any(ints.get(k, {}).get("enabled") for k in ("quickbooks", "xero", "plaid") if ints.get(k))

        if not has_integrations:
            print("ℹ️  No integrations enabled. Falling back to Demo mode.", file=sys.stderr)
            return get_demo_data()

        merged = {
            "balance": {
                "available": [{"amount": 0, "currency": "usd"}],
                "pending":   [{"amount": 0, "currency": "usd"}]
            },
            "payouts": [],
            "invoices": [],
            "subscriptions": [],
            "charges": [],
            "expenses": [],
            "capital_offers": [],
            "active_financing": None
        }

        # Query all inflow providers (QuickBooks, Xero)
        for provider in self.inflow_providers:
            res = provider.fetch_inflows(self.config)
            if not res:
                continue

            if "balance" in res:
                merged["balance"]["available"][0]["amount"] += res["balance"].get("available", [{"amount": 0}])[0].get("amount", 0)
                merged["balance"]["pending"][0]["amount"]   += res["balance"].get("pending",   [{"amount": 0}])[0].get("amount", 0)

            merged["payouts"].extend(res.get("payouts", []))
            merged["invoices"].extend(res.get("invoices", []))
            merged["subscriptions"].extend(res.get("subscriptions", []))
            merged["charges"].extend(res.get("charges", []))
            merged["capital_offers"].extend(res.get("capital_offers", []))
            if res.get("active_financing"):
                merged["active_financing"] = res["active_financing"]

        # Query all outflow providers
        for provider in self.outflow_providers:
            outflows = provider.fetch_outflows(self.config)
            merged["expenses"].extend(outflows)

        return merged


# ── Core Analysis ──────────────────────────────────────────────────────────────
def analyze(data: dict) -> dict:
    today      = date.today()
    available  = data["balance"]["available"][0]["amount"] / 100
    pending_b  = data["balance"]["pending"][0]["amount"]   / 100

    # If there's an active Capital loan, Stripe already withholds before payout
    active          = data.get("active_financing")
    active_withhold = 0.0
    if active and active.get("details"):
        active_withhold = active["details"].get("withhold_rate", 0.0)

    events = []

    for p in data.get("payouts", []):
        arr = date.fromtimestamp(p["arrival_date"])
        if arr >= today:
            net = p["amount"] / 100  # Payouts in transit are already net of active withholding
            events.append({"date": str(arr), "type": "payout",
                           "amount": round(net, 2), "label": "Stripe payout", "direction": "in"})

    for inv in data.get("invoices", []):
        if inv.get("due_date"):
            due = date.fromtimestamp(inv["due_date"])
            if due >= today:
                # Apply active withholding to Stripe invoices since they will go through processing
                net = inv["amount_due"] / 100 * (1 - active_withhold)
                events.append({"date": str(due), "type": "invoice",
                               "amount": round(net, 2),
                               "label":  inv.get("description", f"Invoice {inv['id']}"),
                               "direction": "in", "customer": inv.get("customer_email", "")})

    for sub in data.get("subscriptions", []):
        renewal = date.fromtimestamp(sub["current_period_end"])
        if sub["status"] in ("active", "trialing") and today <= renewal <= today + timedelta(days=PROJ_DAYS):
            net = sub["amount"] / 100 * (1 - active_withhold)
            events.append({"date": str(renewal), "type": "subscription_renewal",
                           "amount": round(net, 2), "label": "Subscription renewal",
                           "direction": "in", "customer": sub.get("customer_email", "")})
        elif sub["status"] == "past_due":
            # Past due — track as risk, but also estimate eventual collection (conservative 50%)
            events.append({"date": str(today), "type": "failed_payment",
                           "amount": sub["amount"] / 100, "label": "⚠ Past-due subscription",
                           "direction": "risk", "customer": sub.get("customer_email", "")})
            # Also add a delayed inflow at 50% probability, 14 days out
            delayed_date = today + timedelta(days=14)
            if delayed_date <= today + timedelta(days=PROJ_DAYS):
                events.append({"date": str(delayed_date), "type": "delayed_collection",
                               "amount": round(sub["amount"] / 100 * 0.5, 2),
                               "label": "Delayed collection (est. 50%)",
                               "direction": "in", "customer": sub.get("customer_email", "")})

    for exp in data.get("expenses", []):
        due_date = today + timedelta(days=exp["due_in_days"])
        if due_date >= today:
            events.append({"date": str(due_date), "type": "expense",
                           "amount": exp["amount"] / 100, "label": exp["description"],
                           "direction": "out", "recurring": exp.get("recurring", False)})

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
            "net": round(day_in - day_out, 2), "events": day_evts,
        })

        if running < 0:
            gaps.append({"date": day_str, "shortfall": round(abs(running), 2), "severity": "critical"})
        elif running < MIN_BUFFER:
            gaps.append({"date": day_str, "balance": running, "severity": "warning"})

    at_risk = sum(e["amount"] for e in events if e["direction"] == "risk")
    min_bal = min(p["balance"] for p in daily_positions)
    critical = [g for g in gaps if g["severity"] == "critical"]

    # Risk score: 0-100, configurable thresholds
    risk_score = 90 if critical else (55 if gaps else max(0, int(20 - (min_bal / MIN_BUFFER) * 20)))

    # Estimate average daily Stripe volume from last 30 days
    succeeded    = [c for c in data.get("charges", []) if c.get("status") == "succeeded"]
    avg_daily_vol = sum(c["amount"] / 100 for c in succeeded) / 30 if succeeded else 500.0

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
    }


# ── Capital Analysis ───────────────────────────────────────────────────────────
def analyze_capital_options(data: dict, analysis: dict) -> dict:
    """
    For each critical gap, evaluate resolution options ranked by cost:
      1. Instant payout (if pending balance exists — cheapest, ~1.5% fee)
      2. Stripe Capital offer (if available — flat fee, same-day funds)
      3. Invoice acceleration (early-pay discount to customers)

    Also generates a Capital repayment projection showing the 30-day
    balance with advance received and repayment withholding applied.
    """
    offers    = data.get("capital_offers", [])
    gaps      = [g for g in analysis["critical_gaps"] if g["severity"] == "critical"]
    pending   = analysis["pending_payout"]
    avg_vol   = analysis["avg_daily_stripe_vol"]
    today     = date.today()

    first_gap  = gaps[0] if gaps else None
    gap_amount = first_gap["shortfall"] if first_gap else 0

    options = []

    # ── Option 1: Instant payout ─────────────────────────────────────────────
    if pending > 0:
        fee = round(max(2.0, pending * 0.015), 2)   # Stripe instant payout: ~1.5%
        options.append({
            "type":         "instant_payout",
            "label":        "Stripe instant payout",
            "available":    pending,
            "cost":         fee,
            "covers_gap":   pending >= gap_amount,
            "gap_surplus":  round(pending - gap_amount, 2),
            "can_automate": True,   # can trigger via API: stripe.Payout.create(method='instant')
            "action":       "stripe.Payout.create(amount=None, currency='usd', method='instant')",
            "description":  f"Request ${pending:,.0f} instant payout · fee: ${fee:.2f} · arrives within hours",
        })

    # ── Option 2: Stripe Capital ──────────────────────────────────────────────
    capital_analyses = []
    for offer in offers:
        terms        = offer.get("offered_terms", {})
        advance      = terms.get("advance_amount", 0) / 100
        fee          = terms.get("fee_amount",     0) / 100
        withhold     = terms.get("withhold_rate", 0.10)
        total_repay  = advance + fee
        daily_impact = round(avg_vol * withhold, 2)
        est_days     = round(total_repay / daily_impact) if daily_impact else 999
        fee_pct      = round(fee / advance * 100, 1) if advance else 0

        expires      = offer.get("expires_at")
        days_left    = round((expires - datetime.now().timestamp()) / 86400) if expires else None

        ca = {
            "offer_id":              offer["id"],
            "type":                  "stripe_capital",
            "label":                 "Stripe Capital cash advance",
            "advance":               advance,
            "fee":                   fee,
            "fee_pct":               fee_pct,
            "total_repayment":       total_repay,
            "withhold_rate":         withhold,
            "daily_repayment_impact": daily_impact,
            "est_days_to_repay":     est_days,
            "covers_gap":            advance >= gap_amount,
            "gap_surplus":           round(advance - gap_amount, 2),
            "expires_in_days":       days_left,
            "financing_type":        offer.get("financing_type", "cash_advance"),
            "can_automate":          False,   # requires one user click
            "dashboard_url":         "https://dashboard.stripe.com/capital",
            "cost":                  fee,
            "action":                f"Accept at dashboard.stripe.com/capital · funds land same day",
            "description": (
                f"${advance:,.0f} advance · ${fee:,.0f} flat fee ({fee_pct}%) · "
                f"{withhold*100:.0f}% repayment rate · ~${daily_impact:,.2f}/day withheld · "
                f"~{est_days} days to repay"
                + (f" · expires in {days_left}d" if days_left else "")
            ),
        }
        capital_analyses.append(ca)
        options.append(ca)

    # ── Option 3: Invoice acceleration (with probability model) ────────────────
    future_invoices = [
        e for e in analysis["upcoming_events"]
        if e["direction"] == "in" and e["type"] == "invoice"
        and e.get("date", "") > str(today)
    ]
    if future_invoices and first_gap:
        accel_total  = sum(e["amount"] for e in future_invoices[:3])
        # Apply acceptance probability — not all customers will take the discount
        expected_collection = round(accel_total * EARLY_PAY_ACCEPTANCE_RATE, 2)
        discount_cost = round(expected_collection * EARLY_PAY_DISCOUNT_PCT / 100.0, 2)
        options.append({
            "type":         "invoice_acceleration",
            "label":        "Early-payment discount to customers",
            "available":    expected_collection,  # expected, not face value
            "face_value":   accel_total,
            "acceptance_rate": EARLY_PAY_ACCEPTANCE_RATE,
            "cost":         discount_cost,
            "covers_gap":   expected_collection >= gap_amount,
            "gap_surplus":  round(expected_collection - gap_amount, 2),
            "can_automate": False,
            "action":       f"Offer {EARLY_PAY_DISCOUNT_PCT:.1f}% early-pay discount to {len(future_invoices[:3])} customers (est. {EARLY_PAY_ACCEPTANCE_RATE*100:.0f}% accept)",
            "description":  f"Offer {EARLY_PAY_DISCOUNT_PCT:.1f}% discount on ${accel_total:,.0f} outstanding invoices · expected collection ${expected_collection:,.0f} · costs ${discount_cost:,.0f}",
        })

    options.sort(key=lambda o: (not o["covers_gap"], o.get("cost", 9999)))

    # ── Capital repayment projection ──────────────────────────────────────────
    capital_projection = None
    if capital_analyses:
        best = capital_analyses[0]
        capital_projection = _project_with_capital(
            base_positions  = analysis["daily_positions"],
            current_balance = analysis["current_balance"],
            advance         = best["advance"],
            fee             = best["fee"],
            withhold_rate   = best["withhold_rate"],
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
    base_positions:  list,
    current_balance: float,
    advance:         float,
    fee:             float,
    withhold_rate:   float,
) -> list:
    """
    Recompute 30-day balance assuming Capital advance received today.
    All Stripe inflows (charges, subscriptions, invoices) have withhold_rate deducted until advance + fee is repaid.
    """
    projected   = []
    running     = current_balance + advance
    total_repay = advance + fee
    repaid      = 0.0

    for pos in base_positions:
        still_repaying = repaid < total_repay
        # Sum up only Stripe-specific inflows (subscriptions, invoices, charges) on this day.
        # Do not include payouts (type payout) or external bank wires to prevent double-counting.
        stripe_inflow = sum(
            e["amount"] for e in pos.get("events", [])
            if e["direction"] == "in" and e["type"] in ("subscription_renewal", "invoice", "charge", "delayed_collection")
        )
        withheld       = min(stripe_inflow * withhold_rate, total_repay - repaid) if still_repaying else 0.0
        repaid        += withheld
        net_in         = pos["in"] - withheld
        running        = round(running + net_in - pos["out"], 2)

        projected.append({
            "date":            pos["date"],
            "balance":         running,
            "in":              round(net_in, 2),
            "in_gross":        pos["in"],
            "out":             pos["out"],
            "withheld":        round(withheld, 2),
            "repaid_to_date":  round(min(repaid, total_repay), 2),
        })

    return projected


# ── ASCII Chart Generation ─────────────────────────────────────────────────────
def generate_text_chart(analysis: dict, capital_data: dict) -> str:
    positions = analysis["daily_positions"]
    cap_proj = capital_data.get("capital_projection")

    # Scale calculation
    max_val = 1.0
    for pos in positions:
        max_val = max(max_val, abs(pos["balance"]))
    if cap_proj:
        for p in cap_proj:
            max_val = max(max_val, abs(p["balance"]))

    out = []
    out.append("── VISUAL CASH FLOW TREND (Base vs. With Capital) ──────────")
    out.append(f"  {'Date':<10} | {'Base Balance':<18} | {'With Stripe Capital':<22}")
    out.append("  " + "-" * 58)

    for idx, pos in enumerate(positions):
        dt = pos["date"]
        base_bal = pos["balance"]

        # We only print event days, negative days, or every 3rd day to keep it compact
        day_idx = (date.fromisoformat(dt) - date.fromisoformat(analysis["as_of"])).days
        has_event = bool(pos.get("events"))
        is_negative = base_bal < 0

        if has_event or is_negative or day_idx % 3 == 0 or day_idx == 0 or day_idx == len(positions) - 1:
            # Base bar representation (max 10 blocks)
            base_ratio = abs(base_bal) / max_val
            base_bars_count = int(round(base_ratio * 10))
            if base_bal >= 0:
                base_bar_str = "█" * base_bars_count + " " * (10 - base_bars_count)
                base_val_str = f"${base_bal/1000:.1f}k"
            else:
                base_bar_str = "░" * base_bars_count + " " * (10 - base_bars_count)
                base_val_str = f"-${abs(base_bal)/1000:.1f}k"

            base_fmt = f"{base_val_str:>7} [{base_bar_str}]"

            # Capital bar representation
            if cap_proj and idx < len(cap_proj):
                cap_bal = cap_proj[idx]["balance"]
                cap_ratio = abs(cap_bal) / max_val
                cap_bars_count = int(round(cap_ratio * 10))
                if cap_bal >= 0:
                    cap_bar_str = "█" * cap_bars_count + " " * (10 - cap_bars_count)
                    cap_val_str = f"${cap_bal/1000:.1f}k"
                else:
                    cap_bar_str = "░" * cap_bars_count + " " * (10 - cap_bars_count)
                    cap_val_str = f"-${abs(cap_bal)/1000:.1f}k"

                # Check if Stripe Capital resolved a gap on this day
                resolved_tag = ""
                if base_bal < 0 and cap_bal >= 0:
                    resolved_tag = " 🟢 Gap Resolved"
                elif cap_bal < 0:
                    resolved_tag = " 🔴 Shortfall"

                cap_fmt = f"{cap_val_str:>7} [{cap_bar_str}]{resolved_tag}"
            else:
                cap_fmt = "N/A"

            out.append(f"  {dt:<10} | {base_fmt:<18} | {cap_fmt}")

    return "\n".join(out)


# ── Save ───────────────────────────────────────────────────────────────────────
def save_report(report_text: str, analysis: dict, capital_data: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{analysis['as_of']}.md"
    content = (
        f"# Cash Flow Briefing — {analysis['as_of']}\n\n"
        f"{report_text}\n\n---\n\n"
        f"```json\n{json.dumps({'analysis': analysis, 'capital': capital_data}, indent=2)}\n```\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def add_expense(expense_str: str):
    """
    Parse expense_str: 'Description, Amount, [DayOfMonth], [Recurring], [Interval]'
    And add to config.yaml.
    """
    try:
        parts = [p.strip() for p in expense_str.split(",")]
        if len(parts) < 2:
            print("❌ Invalid format. Expected: 'Description, Amount, [DayOfMonth], [Recurring], [Interval]'", file=sys.stderr)
            sys.exit(1)

        desc = parts[0]
        try:
            amount = float(parts[1])
        except ValueError:
            print("❌ Invalid amount. Must be a numeric value.", file=sys.stderr)
            sys.exit(1)

        dom = int(parts[2]) if len(parts) > 2 and parts[2] else None
        recurring = parts[3].lower() in ("true", "yes", "1") if len(parts) > 3 and parts[3] else True
        interval = parts[4] if len(parts) > 4 and parts[4] else "monthly"

        # Load existing config
        cfg = {}
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    cfg = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ Error reading config, starting fresh: {e}", file=sys.stderr)

        if "expenses" not in cfg or not isinstance(cfg["expenses"], list):
            cfg["expenses"] = []

        new_exp = {
            "description": desc,
            "amount": amount,
            "day_of_month": dom,
            "recurring": recurring,
            "interval": interval
        }
        # If expense with same description exists, replace it, otherwise append
        replaced = False
        for idx, exp in enumerate(cfg["expenses"]):
            if exp.get("description") == desc:
                cfg["expenses"][idx] = new_exp
                replaced = True
                break
        if not replaced:
            cfg["expenses"].append(new_exp)

        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)

        print(f"✅ Added/updated expense: {desc} - ${amount:.2f}", file=sys.stderr)
    except Exception as e:
        print(f"❌ Error adding expense: {e}", file=sys.stderr)
        sys.exit(1)


def delete_expense(desc: str):
    try:
        if not CONFIG_PATH.exists():
            print("❌ No config.yaml found.", file=sys.stderr)
            sys.exit(1)

        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}

        if "expenses" not in cfg or not isinstance(cfg["expenses"], list):
            print("❌ No expenses configured.", file=sys.stderr)
            sys.exit(0)

        original_len = len(cfg["expenses"])
        cfg["expenses"] = [e for e in cfg["expenses"] if e.get("description") != desc]

        if len(cfg["expenses"]) == original_len:
            print(f"ℹ️ Expense '{desc}' not found.", file=sys.stderr)
        else:
            with open(CONFIG_PATH, "w") as f:
                yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
            print(f"✅ Deleted expense: {desc}", file=sys.stderr)
    except Exception as e:
        print(f"❌ Error deleting expense: {e}", file=sys.stderr)
        sys.exit(1)


def list_expenses():
    try:
        expenses = _load_config_expenses()
        if not expenses:
            print("No expenses found.", file=sys.stderr)
            return
        print(f"\n📋 CONFIGURED EXPENSES (As of today):", file=sys.stderr)
        print(f"{'Description':<35} | {'Amount':<10} | {'Due (Days)':<10} | {'Recurring':<10}", file=sys.stderr)
        print("-" * 75, file=sys.stderr)
        for exp in expenses:
            rec_str = "Yes" if exp["recurring"] else "No"
            amt_str = f"${exp['amount']/100:,.2f}"
            print(f"{exp['description']:<35} | {amt_str:<10} | {exp['due_in_days']:<10} | {rec_str:<10}", file=sys.stderr)
        print("", file=sys.stderr)
    except Exception as e:
        print(f"❌ Error listing expenses: {e}", file=sys.stderr)
        sys.exit(1)


def handle_webhook(payload_str: str):
    try:
        payload = json.loads(payload_str)
        evt_type = payload.get("type")
        print(f"📡 Webhook received: {evt_type}", file=sys.stderr)

        if evt_type == "capital.financing_offer.paid_out":
            data_obj = payload.get("data", {}).get("object", {})
            offer_id = data_obj.get("id")
            terms = data_obj.get("offered_terms", {})
            advance = terms.get("advance_amount", 0) / 100

            # Log the payout to a ledger file
            log_dir = Path.home() / ".hermes" / "cashflow" / "webhooks"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "ledger.jsonl"

            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "event_type": evt_type,
                "offer_id": offer_id,
                "advance_amount": advance
            }
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

            # Trigger re-analysis by invalidating any cached report for today
            # (Next run will pick up the new balance from Stripe)
            print(f"🎉 CONFIRMED: Stripe Capital advance of ${advance:,.2f} (Offer ID: {offer_id}) has been paid out and funds have landed in your account balance!", file=sys.stdout)
            print("💡 Next scheduled run will reflect the updated balance.", file=sys.stdout)
        else:
            print(f"ℹ️ Webhook type '{evt_type}' logged. No custom action taken.", file=sys.stderr)
    except Exception as e:
        print(f"❌ Error handling webhook: {e}", file=sys.stderr)
        sys.exit(1)


def detect_expenses_from_file(file_path_str: str):
    file_path = Path(file_path_str)
    if not file_path.exists():
        print(f"❌ File not found: {file_path_str}", file=sys.stderr)
        sys.exit(1)

    print(f"🔍 Reading transaction log from {file_path_str}...", file=sys.stderr)
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"❌ Failed to read file: {e}", file=sys.stderr)
        sys.exit(1)

    detected = _heuristic_detect_expenses(content)
    _print_detected_expenses(detected)


def _heuristic_detect_expenses(content: str) -> list:
    """
    Fallback parser that scans transaction text for common recurring keywords (like AWS, Rent, Google, Microsoft, Adobe)
    and estimates monthly patterns.
    """
    import re
    detected = []
    lines = content.splitlines()
    for line in lines:
        match = re.search(r'(payroll|rent|aws|google|adobe|notion|linear|github|office|utilities|comcast)', line, re.IGNORECASE)
        if match:
            keyword = match.group(0).capitalize()
            amt_match = re.search(r'[-$]?(\d+[\d,]*\.\d{2})', line)
            if amt_match:
                try:
                    amount = float(amt_match.group(1).replace(",", ""))
                    amount = abs(amount)
                    date_match = re.search(r'(\d{4})[-/](\d{2})[-/](\d{2})', line)
                    dom = int(date_match.group(3)) if date_match else 5

                    if not any(d["description"].startswith(keyword) for d in detected):
                        detected.append({
                            "description": f"{keyword} (Heuristically Detected)",
                            "amount": amount,
                            "day_of_month": dom,
                            "recurring": True,
                            "interval": "monthly"
                        })
                except ValueError:
                    continue
    return detected


def _print_detected_expenses(detected: list):
    if not detected:
        print("❌ No recurring expenses detected in this log.", file=sys.stdout)
        return

    print(f"\n🔮 DETECTED RECURRING EXPENSES:", file=sys.stdout)
    print(f"{'Description':<35} | {'Amount':<10} | {'Day of Month':<12} | {'Interval':<10}", file=sys.stdout)
    print("-" * 75, file=sys.stdout)
    for exp in detected:
        dom_str = str(exp.get('day_of_month', 'Any'))
        print(f"{exp['description']:<35} | ${exp['amount']:<10,.2f} | {dom_str:<12} | {exp['interval']:<10}", file=sys.stdout)

    print("\n💡 Tip: You can copy these and add them using the --add-expense command.", file=sys.stdout)
    print('Example: python cashflow_advisor.py --add-expense "Office Rent, 4500, 7, True, monthly"', file=sys.stdout)


def check_integrations_status() -> dict:
    """
    Check which integrations are configured (no secret key checks — skills must use MCP).
    """
    qb_enabled = _cfg.get("integrations", {}).get("quickbooks", {}).get("enabled", False)
    xero_enabled = _cfg.get("integrations", {}).get("xero", {}).get("enabled", False)
    plaid_enabled = _cfg.get("integrations", {}).get("plaid", {}).get("enabled", False)

    return {
        "stripe": "MCP MODE (pre-fetched via Hermes Stripe MCP)",
        "quickbooks": "ENABLED (Mock/Stub)" if qb_enabled else "DISABLED (Stub)",
        "xero": "ENABLED (Mock/Stub)" if xero_enabled else "DISABLED (Stub)",
        "plaid": "ENABLED (Mock/Stub)" if plaid_enabled else "DISABLED (Stub)",
    }


def format_text_report(analysis: dict, capital_data: dict) -> str:
    as_of = analysis["as_of"]
    available = analysis["current_balance"]
    pending = analysis["pending_payout"]

    out = []
    divider = "=" * 60
    out.append(divider)
    out.append(f"💰 CASH FLOW & EXPENSE REPORT — {as_of}")
    out.append(divider)
    out.append("")

    # 1. Current balances
    out.append("── CURRENT BALANCES ────────────────────────────────────────")
    out.append(f"  Available now:    ${available:,.2f}")
    out.append(f"  Pending payout:   ${pending:,.2f} (in Stripe pipeline)")
    out.append("")

    # 2. Configured Expenses
    out.append("── UPCOMING FIXED EXPENSES ─────────────────────────────────")
    exp_events = []
    seen_expenses = set()
    for pos in analysis.get("daily_positions", []):
        for e in pos.get("events", []):
            if e["direction"] == "out" and e["type"] == "expense":
                due = (date.fromisoformat(pos["date"]) - date.fromisoformat(as_of)).days
                unique_key = (e["label"], e["amount"], due)
                if unique_key not in seen_expenses:
                    seen_expenses.add(unique_key)
                    exp_events.append((e["label"], e["amount"], due, e.get("recurring", True)))

    if exp_events:
        for label, amt, due, rec in exp_events[:15]:
            rec_str = "recurring" if rec else "one-off"
            out.append(f"  • {label:<35} ${amt:>10,.2f}   (due in {due} days, {rec_str})")
    else:
        out.append("  No upcoming expenses configured.")
    out.append("")

    # 3. Cash flow projection
    out.append("── 30-DAY CASH FLOW PROJECTION ─────────────────────────────")
    out.append(f"  {'Date':<12} | {'Net In':<12} | {'Outflow':<12} | {'Projected Balance':<18}")
    out.append("  " + "-" * 60)

    gaps_found = []
    for pos in analysis.get("daily_positions", []):
        has_event = bool(pos.get("events"))
        is_negative = pos["balance"] < 0
        day_idx = (date.fromisoformat(pos["date"]) - date.fromisoformat(as_of)).days

        if has_event or is_negative or day_idx % 5 == 0 or day_idx == 0 or day_idx == 29:
            status_tag = ""
            if pos["balance"] < 0:
                status_tag = " 🔴 CRITICAL GAP"
                gaps_found.append((pos["date"], abs(pos["balance"]), day_idx))
            elif pos["balance"] < MIN_BUFFER:
                status_tag = " 🟡 BELOW BUFFER"

            out.append(f"  {pos['date']:<12} | ${pos['in']:>10,.2f} | ${pos['out']:>10,.2f} | ${pos['balance']:>16,.2f}{status_tag}")

            for e in pos.get("events", []):
                if e["type"] != "expense":
                    dir_str = "inflow" if e["direction"] == "in" else "outflow"
                    out.append(f"    └─ [{e['type'].upper()}] {e['label']}: ${e['amount']:,.2f} ({dir_str})")

    out.append("")

    # Visual Trend Chart
    out.append(generate_text_chart(analysis, capital_data))
    out.append("")

    # 4. Critical gaps
    if gaps_found:
        out.append("── CRITICAL GAPS DETECTED ──────────────────────────────────")
        unique_gaps = {}
        for dt, shortfall, days in gaps_found:
            unique_gaps[dt] = (shortfall, days)
        for dt, (shortfall, days) in sorted(unique_gaps.items()):
            causing_expense = "Shortfall"
            for pos in analysis.get("daily_positions", []):
                if pos["date"] == dt:
                    outflow_events = [e["label"] for e in pos.get("events", []) if e["direction"] == "out"]
                    if outflow_events:
                        causing_expense = ", ".join(outflow_events)
            out.append(f"  ✗ {dt} (Day {days}): shortage of -${shortfall:,.2f} (Due to: {causing_expense})")
        out.append("")

    # 5. Loan and Funding Suggestions
    out.append("── FUNDING & LOAN SUGGESTIONS ──────────────────────────────")
    options = capital_data.get("options", [])
    if options:
        out.append(f"  We identified {len(options)} resolution option(s) ranked by cost:")
        out.append("")
        for idx, opt in enumerate(options[:4]):
            covers = "COVERS GAP" if opt["covers_gap"] else "PARTIAL COVERAGE"
            out.append(f"  {idx+1}. [{opt['type'].upper()}] {opt['label']}")
            out.append(f"     Description:  {opt['description']}")
            out.append(f"     Cost:         ${opt.get('cost', 0):,.2f} | {covers}")
            out.append(f"     Action:       {opt['action']}")
            out.append("")
    else:
        out.append("  No funding options available.")
        out.append("")

    # 6. Integrations Diagnostic Checklist
    out.append("── INTEGRATIONS DIAGNOSTIC CHECKLIST ───────────────────────")
    status = check_integrations_status()

    out.append(f"  ✅ Stripe:      {status['stripe']}")

    qb_icon = "✅" if "ENABLED" in status["quickbooks"] else "✗"
    out.append(f"  {qb_icon} QuickBooks:  {status['quickbooks']}")

    xero_icon = "✅" if "ENABLED" in status["xero"] else "✗"
    out.append(f"  {xero_icon} Xero:        {status['xero']}")

    plaid_icon = "✅" if "ENABLED" in status["plaid"] else "✗"
    out.append(f"  {plaid_icon} Plaid:       {status['plaid']}")
    out.append("")

    # 7. Conversational Audit Dialogue
    out.append("── CONVERSATIONAL AUDIT DIALOGUE ───────────────────────────")
    out.append("  💡 SYSTEM QUESTION FOR THE AGENT:")
    out.append("     \"Did I miss any unlisted expenses? Ask the user if they want to add them now.\"")

    missing_any = not ("ENABLED" in status["quickbooks"] and "ENABLED" in status["xero"] and "ENABLED" in status["plaid"])
    if missing_any:
        unconfigured = []
        if "DISABLED" in status["quickbooks"]: unconfigured.append("QuickBooks")
        if "DISABLED" in status["xero"]: unconfigured.append("Xero")
        if "DISABLED" in status["plaid"]: unconfigured.append("Plaid")

        out.append("  💡 SYSTEM QUESTION FOR THE AGENT:")
        out.append(f"     \"Suggest configuring the following unlinked integration(s): {', '.join(unconfigured)}.\"")

    out.append(divider)
    return "\n".join(out)


# ── Main ───────────────────
def main():
    parser = argparse.ArgumentParser(description="Cash Flow Advisor v0.4 — MCP Mode + Stripe Capital")
    parser.add_argument("--demo",           action="store_true", help="Use demo data")
    parser.add_argument("--analyze-only",   action="store_true", help="Raw JSON output, skip LLM")
    parser.add_argument("--no-chart",       action="store_true", help="Skip ASCII chart")
    parser.add_argument("--input",          type=str,            help="JSON from Hermes MCP mode (pre-fetched Stripe data)")
    parser.add_argument("--output",         choices=["terminal", "json"], default="terminal")
    parser.add_argument("--add-expense",    type=str,            help="Add expense. Format: 'Description,Amount,DayOfMonth,Recurring,Interval'")
    parser.add_argument("--delete-expense", type=str,            help="Delete expense by description")
    parser.add_argument("--list-expenses",  action="store_true", help="List all expenses in config.yaml")
    parser.add_argument("--webhook",        type=str,            help="Mock/live webhook payload (JSON string)")
    parser.add_argument("--detect-expenses", type=str,           help="File path to historical transactions (CSV/JSON) to detect patterns")
    args = parser.parse_args()

    if args.add_expense:
        add_expense(args.add_expense)
        return
    if args.delete_expense:
        delete_expense(args.delete_expense)
        return
    if args.list_expenses:
        list_expenses()
        return
    if args.webhook:
        handle_webhook(args.webhook)
        return
    if args.detect_expenses:
        detect_expenses_from_file(args.detect_expenses)
        return

    # Data source
    if args.input:
        print("📡 MCP mode", file=sys.stderr)
        raw = json.loads(args.input)
        raw.setdefault("expenses", _load_config_expenses())
        raw.setdefault("capital_offers", [])
        raw.setdefault("active_financing", None)
        data = raw
    else:
        use_demo_mode = args.demo or USE_DEMO
        manager = DataSourceManager(CONFIG_PATH)
        data = manager.fetch_all(use_demo=use_demo_mode)

    # Analyze
    analysis     = analyze(data)
    capital_data = analyze_capital_options(data, analysis)

    if args.analyze_only or args.output == "json":
        print(json.dumps({"analysis": analysis, "capital": capital_data}, indent=2))
        return

    # Format and print the consolidated text report
    report = format_text_report(analysis, capital_data)
    if args.no_chart:
        # Strip the chart section
        lines = report.split("\n")
        chart_start = None
        for i, line in enumerate(lines):
            if "VISUAL CASH FLOW TREND" in line:
                chart_start = i
                break
        if chart_start:
            # Find end of chart (empty line after chart)
            for i in range(chart_start, len(lines)):
                if lines[i].strip() == "" and i > chart_start + 5:
                    report = "\n".join(lines[:chart_start] + lines[i:])
                    break

    print(report)

    # Save report
    path = save_report(report, analysis, capital_data)
    print(f"\n📁 Saved report locally → {path}", file=sys.stderr)


if __name__ == "__main__":
    main()