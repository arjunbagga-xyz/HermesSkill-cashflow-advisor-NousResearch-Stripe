"""
providers/base.py
Universal expense provider interface for cashflow-advisor.

Every provider implements two methods:
  is_configured() → bool     checks env vars / config, no API calls
  fetch(days)     → list     returns ExpenseEvent objects

Adding a new provider:
  1. Create providers/yourprovider.py
  2. Subclass ExpenseProvider
  3. Add to PROVIDER_REGISTRY in providers/__init__.py
  That's it. The core engine picks it up automatically.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ExpenseEvent:
    """Standardised representation of a future cash outflow."""
    description:  str
    amount:       float             # USD
    due_date:     date
    source:       str               # provider name, shown in briefing
    recurring:    bool  = True
    interval:     str   = "monthly" # monthly | biweekly | weekly | once
    category:     str   = "general" # payroll | rent | saas | tax | subscription | general
    confidence:   float = 1.0       # 0–1 how certain this expense will occur
    external_id:  Optional[str] = None  # provider's own ID — used for dedup


class ExpenseProvider(ABC):
    """
    Abstract base for all expense data sources.

    Subclasses must set `name` and `description` as class attributes
    and implement `is_configured()` and `fetch()`.
    """
    name:        str = "unknown"
    description: str = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Return True if this provider has the credentials / config it needs.
        Must not make network calls — check env vars and config files only.
        """
        ...

    @abstractmethod
    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        """
        Return upcoming expense events within days_ahead.
        Should handle its own errors and return [] on failure rather than raising.
        """
        ...

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_legacy_format(self, events: list[ExpenseEvent]) -> list[dict]:
        """
        Convert ExpenseEvent objects to the dict format cashflow_advisor.py
        uses internally (amount in cents, due_in_days offset).
        """
        today  = date.today()
        result = []
        for e in events:
            due_in_days = (e.due_date - today).days
            if due_in_days < 0:
                continue
            result.append({
                "description": f"[{e.source}] {e.description}",
                "amount":      int(e.amount * 100),  # cents
                "due_in_days": due_in_days,
                "recurring":   e.recurring,
                "interval":    e.interval,
                "category":    e.category,
                "source":      e.source,
                "confidence":  e.confidence,
                "external_id": e.external_id,
            })
        return result


def deduplicate(events: list[ExpenseEvent]) -> list[ExpenseEvent]:
    """
    Remove duplicate expenses that appear in multiple sources.
    Matches on: same category + similar amount (±5%) + same due week.
    Keeps the higher-confidence event.

    Example: payroll appearing in both Gusto and Plaid bank feed
    → keep Gusto (confidence 1.0) and drop the Plaid transaction (confidence 0.8).
    """
    from datetime import timedelta

    def week_of(d: date) -> int:
        return (d - date(d.year, 1, 1)).days // 7

    unique: list[ExpenseEvent] = []

    for event in sorted(events, key=lambda e: -e.confidence):
        duplicate = False
        for existing in unique:
            same_week   = abs(week_of(event.due_date) - week_of(existing.due_date)) <= 1
            similar_amt = abs(event.amount - existing.amount) / max(existing.amount, 1) < 0.05
            same_cat    = event.category == existing.category and event.category != "general"
            if same_week and similar_amt and same_cat:
                duplicate = True
                break
        if not duplicate:
            unique.append(event)

    return sorted(unique, key=lambda e: e.due_date)
