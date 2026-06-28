"""
providers/config_provider.py
Reads manually configured expenses from config.yaml.

This is the fallback source — always available, no credentials needed.
Expenses are entered either by the user directly or by the NLP provider
after parsing plain-English input.
"""

import os, yaml
from datetime import date, timedelta
from pathlib import Path
from .base import ExpenseProvider, ExpenseEvent

CONFIG_PATH = Path(os.getenv("CASHFLOW_CONFIG", Path(__file__).parent.parent / "config.yaml"))

INTERVAL_TO_CATEGORY = {
    "payroll": "payroll",
    "salary":  "payroll",
    "rent":    "rent",
    "lease":   "rent",
    "aws":     "saas",
    "gcp":     "saas",
    "azure":   "saas",
    "tax":     "tax",
    "irs":     "tax",
    "vat":     "tax",
    "gsm":     "subscription",
}

def _infer_category(description: str) -> str:
    lower = description.lower()
    for keyword, cat in INTERVAL_TO_CATEGORY.items():
        if keyword in lower:
            return cat
    return "general"


class ConfigProvider(ExpenseProvider):
    name        = "config"
    description = "Manually configured expenses (config.yaml)"

    def is_configured(self) -> bool:
        if not CONFIG_PATH.exists():
            return False
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        return bool(cfg.get("expenses"))

    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        if not CONFIG_PATH.exists():
            return []
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}

        today   = date.today()
        events  = []

        for exp in cfg.get("expenses", []):
            try:
                amount = float(exp["amount"])
                dom    = exp.get("day_of_month")

                if dom:
                    target = today.replace(day=int(dom))
                    if target <= today:
                        m = (today.month % 12) + 1
                        y = today.year + (1 if today.month == 12 else 0)
                        target = target.replace(year=y, month=m)
                else:
                    due_in = int(exp.get("due_in_days", 30))
                    target = today + timedelta(days=due_in)

                if (target - today).days > days_ahead:
                    continue

                events.append(ExpenseEvent(
                    description = exp["description"],
                    amount      = amount,
                    due_date    = target,
                    source      = self.name,
                    recurring   = exp.get("recurring", True),
                    interval    = exp.get("interval", "monthly"),
                    category    = exp.get("category") or _infer_category(exp["description"]),
                    confidence  = 1.0,
                    external_id = f"config:{exp['description']}:{dom}",
                ))

                # Biweekly: add the second occurrence within the window
                if exp.get("interval") == "biweekly":
                    second = target + timedelta(days=14)
                    if (second - today).days <= days_ahead:
                        events.append(ExpenseEvent(
                            description = exp["description"],
                            amount      = amount,
                            due_date    = second,
                            source      = self.name,
                            recurring   = True,
                            interval    = "biweekly",
                            category    = events[-1].category,
                            confidence  = 1.0,
                            external_id = f"config:{exp['description']}:{dom}:2",
                        ))

            except Exception:
                continue

        return events
