"""
providers/plaid_provider.py
Pulls recurring outgoing transactions from Plaid bank feeds.

Credentials (set in environment):
  PLAID_CLIENT_ID
  PLAID_SECRET
  PLAID_ACCESS_TOKEN   (one per connected bank account)
  PLAID_ENV            sandbox | development | production  (default: sandbox)

Demo mode: set PLAID_DEMO=true — returns realistic demo transactions
without hitting the Plaid API.

Plaid gives us:
  - Real checking account balance (more accurate than Stripe available balance)
  - Outgoing ACH transfers (payroll, rent, supplier payments)
  - Recurring payment detection via /transactions/recurring/get
  - Card spend patterns

Install: pip install plaid-python
"""

import os
from datetime import date, timedelta
from .base import ExpenseProvider, ExpenseEvent

PLAID_CLIENT_ID   = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET      = os.getenv("PLAID_SECRET")
PLAID_ACCESS_TOKEN = os.getenv("PLAID_ACCESS_TOKEN")
PLAID_ENV         = os.getenv("PLAID_ENV", "sandbox")
PLAID_DEMO        = os.getenv("PLAID_DEMO", "false").lower() == "true"


class PlaidProvider(ExpenseProvider):
    name        = "plaid"
    description = "Bank account recurring transactions (Plaid)"

    def is_configured(self) -> bool:
        return PLAID_DEMO or bool(PLAID_CLIENT_ID and PLAID_SECRET and PLAID_ACCESS_TOKEN)

    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        if PLAID_DEMO:
            return self._demo_events(days_ahead)
        return self._fetch_live(days_ahead)

    def _fetch_live(self, days_ahead: int) -> list[ExpenseEvent]:
        try:
            from plaid.api   import plaid_api
            from plaid.model import (
                TransactionsRecurringGetRequest,
                ItemPublicTokenExchangeRequest,
            )
            import plaid

            env_map = {
                "sandbox":     plaid.Environment.Sandbox,
                "development": plaid.Environment.Development,
                "production":  plaid.Environment.Production,
            }
            configuration = plaid.Configuration(
                host       = env_map.get(PLAID_ENV, plaid.Environment.Sandbox),
                api_key    = {"clientId": PLAID_CLIENT_ID, "secret": PLAID_SECRET},
            )
            client = plaid_api.PlaidApi(plaid.ApiClient(configuration))

            # Get recurring outflows
            request  = TransactionsRecurringGetRequest(access_token=PLAID_ACCESS_TOKEN)
            response = client.transactions_recurring_get(request)

            events = []
            today  = date.today()

            for stream in response.outflow_streams:
                if stream.status != "MATURE":   # skip one-off / immature patterns
                    continue
                next_date = stream.last_date + timedelta(days=stream.average_days_between_transactions or 30)
                if (next_date - today).days > days_ahead:
                    continue
                events.append(ExpenseEvent(
                    description = stream.merchant_name or stream.description or "Bank payment",
                    amount      = abs(stream.average_amount.amount),
                    due_date    = next_date,
                    source      = self.name,
                    recurring   = True,
                    interval    = self._days_to_interval(stream.average_days_between_transactions or 30),
                    category    = self._plaid_category(stream.personal_finance_category.primary
                                                       if stream.personal_finance_category else ""),
                    confidence  = min(0.95, 0.6 + stream.transaction_ids.__len__() * 0.05),
                    external_id = f"plaid:{stream.stream_id}",
                ))

            return events

        except ImportError:
            print("ℹ️  pip install plaid-python to use Plaid provider")
            return []
        except Exception as e:
            print(f"⚠️  Plaid fetch failed: {e}")
            return []

    def _demo_events(self, days_ahead: int) -> list[ExpenseEvent]:
        """Realistic demo bank transactions — mirrors the demo scenario."""
        today = date.today()
        return [
            ExpenseEvent(
                description = "ADP Payroll",
                amount      = 28_000.00,
                due_date    = today + timedelta(days=3),
                source      = self.name,
                recurring   = True,
                interval    = "biweekly",
                category    = "payroll",
                confidence  = 0.97,
                external_id = "plaid:demo:payroll:1",
            ),
            ExpenseEvent(
                description = "Amazon Web Services",
                amount      = 3_200.00,
                due_date    = today + timedelta(days=2),
                source      = self.name,
                recurring   = True,
                interval    = "monthly",
                category    = "saas",
                confidence  = 0.99,
                external_id = "plaid:demo:aws",
            ),
            ExpenseEvent(
                description = "Office Lease — 340 Pine St",
                amount      = 4_500.00,
                due_date    = today + timedelta(days=7),
                source      = self.name,
                recurring   = True,
                interval    = "monthly",
                category    = "rent",
                confidence  = 1.0,
                external_id = "plaid:demo:rent",
            ),
            ExpenseEvent(
                description = "ADP Payroll",
                amount      = 28_000.00,
                due_date    = today + timedelta(days=17),
                source      = self.name,
                recurring   = True,
                interval    = "biweekly",
                category    = "payroll",
                confidence  = 0.97,
                external_id = "plaid:demo:payroll:2",
            ),
        ]

    @staticmethod
    def _days_to_interval(days: int) -> str:
        if days <= 8:  return "weekly"
        if days <= 16: return "biweekly"
        return "monthly"

    @staticmethod
    def _plaid_category(primary: str) -> str:
        mapping = {
            "PAYROLL_BENEFITS": "payroll",
            "RENT_AND_UTILITIES": "rent",
            "GENERAL_SERVICES": "saas",
            "GOVERNMENT_AND_NON_PROFIT": "tax",
            "LOAN_PAYMENTS": "general",
            "SUBSCRIPTION": "subscription",
        }
        return mapping.get(primary, "general")
