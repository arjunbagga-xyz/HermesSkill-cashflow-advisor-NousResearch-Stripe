"""
providers/xero_provider.py
Pulls upcoming bills and scheduled payments from Xero.

Credentials:
  XERO_CLIENT_ID
  XERO_CLIENT_SECRET
  XERO_TENANT_ID
  XERO_DEMO=true   for demo mode

Install: pip install xero-python
"""

import os
from datetime import date, timedelta
from .base import ExpenseProvider, ExpenseEvent

XERO_DEMO = os.getenv("XERO_DEMO", "false").lower() == "true"


class XeroProvider(ExpenseProvider):
    name        = "xero"
    description = "Bills and accounts payable (Xero)"

    def is_configured(self) -> bool:
        return XERO_DEMO or bool(
            os.getenv("XERO_CLIENT_ID")
            and os.getenv("XERO_CLIENT_SECRET")
            and os.getenv("XERO_TENANT_ID")
        )

    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        if XERO_DEMO:
            return self._demo_events(days_ahead)
        return self._fetch_live(days_ahead)

    def _fetch_live(self, days_ahead: int) -> list[ExpenseEvent]:
        try:
            from xero_python.accounting import AccountingApi
            from xero_python.api_client import ApiClient, Configuration

            config = Configuration(
                oauth2_token={
                    "client_id":     os.getenv("XERO_CLIENT_ID"),
                    "client_secret": os.getenv("XERO_CLIENT_SECRET"),
                }
            )
            client      = ApiClient(configuration=config)
            api         = AccountingApi(api_client=client)
            tenant_id   = os.getenv("XERO_TENANT_ID")

            today     = date.today()
            cutoff    = today + timedelta(days=days_ahead)
            bills     = api.get_invoices(
                xero_tenant_id = tenant_id,
                statuses        = ["AUTHORISED"],
                where           = f"Type=\"ACCPAY\" AND DueDate<={cutoff.isoformat()}"
            )

            events = []
            for bill in bills.invoices or []:
                due = bill.due_date.date() if bill.due_date else today
                if (due - today).days > days_ahead:
                    continue
                events.append(ExpenseEvent(
                    description = bill.contact.name if bill.contact else "Supplier",
                    amount      = float(bill.amount_due or 0),
                    due_date    = due,
                    source      = self.name,
                    recurring   = False,
                    interval    = "once",
                    category    = "general",
                    confidence  = 0.95,
                    external_id = f"xero:{bill.invoice_id}",
                ))
            return events

        except ImportError:
            print("ℹ️  pip install xero-python to use Xero provider")
            return []
        except Exception as e:
            print(f"⚠️  Xero fetch failed: {e}")
            return []

    def _demo_events(self, days_ahead: int) -> list[ExpenseEvent]:
        today = date.today()
        return [
            ExpenseEvent(
                description = "Acme Suppliers — Invoice #1042",
                amount      = 8_400.00,
                due_date    = today + timedelta(days=5),
                source      = self.name,
                recurring   = False,
                interval    = "once",
                category    = "general",
                confidence  = 0.95,
                external_id = "xero:demo:inv-1042",
            ),
            ExpenseEvent(
                description = "Annual Software Audit — Ernst & Young",
                amount      = 12_000.00,
                due_date    = today + timedelta(days=14),
                source      = self.name,
                recurring   = False,
                interval    = "once",
                category    = "general",
                confidence  = 0.95,
                external_id = "xero:demo:inv-1055",
            ),
        ]


# ─────────────────────────────────────────────────────────────────────────────
"""
providers/gusto_provider.py
Pulls scheduled payroll runs from Gusto.

Credentials:
  GUSTO_API_TOKEN
  GUSTO_COMPANY_ID
  GUSTO_DEMO=true   for demo mode

Install: pip install requests
Docs: https://docs.gusto.com/app-integrations/docs/api-overview
"""


GUSTO_DEMO = os.getenv("GUSTO_DEMO", "false").lower() == "true"


class GustoProvider(ExpenseProvider):
    name        = "gusto"
    description = "Scheduled payroll runs (Gusto)"

    def is_configured(self) -> bool:
        return GUSTO_DEMO or bool(
            os.getenv("GUSTO_API_TOKEN") and os.getenv("GUSTO_COMPANY_ID")
        )

    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        if GUSTO_DEMO:
            return self._demo_events(days_ahead)
        return self._fetch_live(days_ahead)

    def _fetch_live(self, days_ahead: int) -> list[ExpenseEvent]:
        try:
            import requests
            token      = os.getenv("GUSTO_API_TOKEN")
            company_id = os.getenv("GUSTO_COMPANY_ID")
            today      = date.today()
            cutoff     = today + timedelta(days=days_ahead)

            resp = requests.get(
                f"https://api.gusto.com/v1/companies/{company_id}/payroll_runs",
                headers = {"Authorization": f"Bearer {token}"},
                params  = {
                    "start_date": str(today),
                    "end_date":   str(cutoff),
                },
                timeout = 10,
            )
            resp.raise_for_status()

            events = []
            for run in resp.json():
                check_date = date.fromisoformat(run["check_date"])
                total      = float(run.get("totals", {}).get("net_pay", 0))
                if total <= 0 or (check_date - today).days > days_ahead:
                    continue
                events.append(ExpenseEvent(
                    description = f"Gusto Payroll — {run.get('pay_period', {}).get('end_date', '')}",
                    amount      = total,
                    due_date    = check_date,
                    source      = self.name,
                    recurring   = True,
                    interval    = "biweekly",
                    category    = "payroll",
                    confidence  = 1.0,   # Gusto is authoritative for payroll
                    external_id = f"gusto:{run['uuid']}",
                ))
            return events

        except Exception as e:
            print(f"⚠️  Gusto fetch failed: {e}")
            return []

    def _demo_events(self, days_ahead: int) -> list[ExpenseEvent]:
        today = date.today()
        return [
            ExpenseEvent(
                description = "Gusto Payroll — Jun 1–15",
                amount      = 28_412.00,   # slightly more precise than manual entry
                due_date    = today + timedelta(days=3),
                source      = self.name,
                recurring   = True,
                interval    = "biweekly",
                category    = "payroll",
                confidence  = 1.0,
                external_id = "gusto:demo:run-1",
            ),
            ExpenseEvent(
                description = "Gusto Payroll — Jun 16–30",
                amount      = 28_412.00,
                due_date    = today + timedelta(days=17),
                source      = self.name,
                recurring   = True,
                interval    = "biweekly",
                category    = "payroll",
                confidence  = 1.0,
                external_id = "gusto:demo:run-2",
            ),
        ]


# ─────────────────────────────────────────────────────────────────────────────
"""
providers/mercury_provider.py
Pulls scheduled and recurring outgoing payments from Mercury bank.

Mercury is the most common bank for US startups and has a REST API.
Requires a Mercury API key from Mercury Treasury.

Credentials:
  MERCURY_API_KEY
  MERCURY_ACCOUNT_ID   (optional — defaults to first account)
  MERCURY_DEMO=true    for demo mode

Install: pip install requests
Docs: https://docs.mercury.com/reference
"""


MERCURY_DEMO = os.getenv("MERCURY_DEMO", "false").lower() == "true"


class MercuryProvider(ExpenseProvider):
    name        = "mercury"
    description = "Mercury bank scheduled payments"

    def is_configured(self) -> bool:
        return MERCURY_DEMO or bool(os.getenv("MERCURY_API_KEY"))

    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        if MERCURY_DEMO:
            return self._demo_events(days_ahead)
        return self._fetch_live(days_ahead)

    def _fetch_live(self, days_ahead: int) -> list[ExpenseEvent]:
        try:
            import requests
            api_key    = os.getenv("MERCURY_API_KEY")
            account_id = os.getenv("MERCURY_ACCOUNT_ID")
            headers    = {"Authorization": f"api-key {api_key}"}

            # Get account list if no specific account given
            if not account_id:
                r = requests.get("https://api.mercury.com/api/v1/accounts",
                                 headers=headers, timeout=10)
                r.raise_for_status()
                accounts   = r.json().get("accounts", [])
                account_id = accounts[0]["id"] if accounts else None
            if not account_id:
                return []

            today  = date.today()
            cutoff = today + timedelta(days=days_ahead)

            # Mercury provides scheduled payments via wire/ACH endpoints
            r = requests.get(
                f"https://api.mercury.com/api/v1/account/{account_id}/transactions",
                headers = headers,
                params  = {
                    "start":  str(today),
                    "end":    str(cutoff),
                    "status": "pending",
                },
                timeout = 10,
            )
            r.raise_for_status()

            events = []
            for txn in r.json().get("transactions", []):
                if txn.get("amount", 0) >= 0:
                    continue   # skip incoming
                events.append(ExpenseEvent(
                    description = txn.get("counterpartyName") or txn.get("note", "Bank payment"),
                    amount      = abs(float(txn["amount"])),
                    due_date    = date.fromisoformat(txn["estimatedDeliveryDate"][:10]),
                    source      = self.name,
                    recurring   = False,
                    interval    = "once",
                    category    = "general",
                    confidence  = 0.98,
                    external_id = f"mercury:{txn['id']}",
                ))
            return events

        except Exception as e:
            print(f"⚠️  Mercury fetch failed: {e}")
            return []

    def _demo_events(self, days_ahead: int) -> list[ExpenseEvent]:
        today = date.today()
        return [
            ExpenseEvent(
                description = "Landlord — WeWork Mission St",
                amount      = 4_500.00,
                due_date    = today + timedelta(days=7),
                source      = self.name,
                recurring   = True,
                interval    = "monthly",
                category    = "rent",
                confidence  = 0.99,
                external_id = "mercury:demo:rent",
            ),
        ]
