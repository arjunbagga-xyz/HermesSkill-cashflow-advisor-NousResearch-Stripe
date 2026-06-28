"""
providers/__init__.py
Provider registry for cashflow-advisor.

Auto-discovers configured providers, fetches from all of them,
deduplicates overlapping events (e.g. payroll in both Gusto + Plaid),
and returns a merged, sorted expense list.

Adding a new provider:
  1. Create providers/yourprovider.py subclassing ExpenseProvider
  2. Import and add to REGISTRY below
  That's it.
"""

from .base              import ExpenseEvent, ExpenseProvider, deduplicate
from .config_provider   import ConfigProvider
from .nlp_provider      import NLPProvider
from .plaid_provider    import PlaidProvider
from .xero_gusto_mercury import XeroProvider, GustoProvider, MercuryProvider

# ── Registry ───────────────────────────────────────────────────────────────────
# Order matters for deduplication priority:
# Higher-confidence providers should come first so their events win ties.
REGISTRY: list[type[ExpenseProvider]] = [
    GustoProvider,    # payroll-authoritative (confidence 1.0)
    PlaidProvider,    # bank transactions (confidence 0.97-0.99)
    XeroProvider,     # bills / accounts payable (confidence 0.95)
    MercuryProvider,  # Mercury bank scheduled payments (confidence 0.98-0.99)
    ConfigProvider,   # manual config fallback (confidence 1.0 but user-entered)
]


def load_active_providers() -> list[ExpenseProvider]:
    """Return instantiated providers that have credentials configured."""
    active = []
    for ProviderClass in REGISTRY:
        p = ProviderClass()
        if p.is_configured():
            active.append(p)
    return active


def fetch_all_expenses(days_ahead: int = 30) -> tuple[list[dict], list[str]]:
    """
    Fetch expenses from all active providers, deduplicate, and return:
      - expenses: list of dicts in cashflow_advisor.py legacy format
      - summary:  list of human-readable source descriptions for the briefing

    Returns ([], ["No expense sources configured"]) if nothing is set up.
    """
    providers = load_active_providers()

    if not providers:
        return [], ["⚠️ No expense sources configured"]

    all_events: list[ExpenseEvent] = []
    summary:    list[str]          = []

    for provider in providers:
        try:
            events = provider.fetch(days_ahead=days_ahead)
            all_events.extend(events)
            summary.append(f"{provider.name} ({len(events)} event{'s' if len(events) != 1 else ''})")
        except Exception as e:
            summary.append(f"{provider.name} (error: {e})")

    deduped   = deduplicate(all_events)
    dropped   = len(all_events) - len(deduped)
    if dropped > 0:
        summary.append(f"{dropped} duplicate{'s' if dropped != 1 else ''} removed")

    legacy = []
    for e in deduped:
        from datetime import date
        due_in_days = (e.due_date - date.today()).days
        if due_in_days < 0:
            continue
        legacy.append({
            "description": e.description,
            "amount":      int(e.amount * 100),
            "due_in_days": due_in_days,
            "recurring":   e.recurring,
            "interval":    e.interval,
            "category":    e.category,
            "source":      e.source,
            "confidence":  e.confidence,
            "external_id": e.external_id,
        })

    return legacy, summary


__all__ = [
    "ExpenseEvent",
    "ExpenseProvider",
    "ConfigProvider",
    "NLPProvider",
    "PlaidProvider",
    "XeroProvider",
    "GustoProvider",
    "MercuryProvider",
    "load_active_providers",
    "fetch_all_expenses",
    "deduplicate",
]
