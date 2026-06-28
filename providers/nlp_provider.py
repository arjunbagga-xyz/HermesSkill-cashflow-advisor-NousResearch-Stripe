"""
providers/nlp_provider.py
Parses plain-English expense descriptions into ExpenseEvents.

Used by Hermes when the user describes their expenses in chat.
Calls Nemotron via NVIDIA NIM if NVIDIA_API_KEY is set.
Falls back to a regex heuristic if not.

Usage (called by SKILL.md / cashflow_advisor.py --save-expenses):
  provider = NLPProvider()
  events   = provider.parse("Payroll $28k twice a month on the 1st and 15th")
  provider.save_to_config(events)
"""

import os, re, json, yaml
from datetime import date, timedelta
from pathlib import Path
from .base import ExpenseProvider, ExpenseEvent

CONFIG_PATH = Path(os.getenv("CASHFLOW_CONFIG", Path(__file__).parent.parent / "config.yaml"))


class NLPProvider(ExpenseProvider):
    """
    Not a pull-based provider — this is a write-once parser.
    is_configured() always returns False so it never auto-activates
    in the provider registry. It's invoked explicitly via --save-expenses.
    """
    name        = "nlp"
    description = "Natural language expense parser"

    def is_configured(self) -> bool:
        return False   # never auto-activates

    def fetch(self, days_ahead: int = 30) -> list[ExpenseEvent]:
        return []      # not a pull source

    # ── Core parsing ──────────────────────────────────────────────────────────

    def parse(self, text: str) -> list[ExpenseEvent]:
        """Parse free-form text into ExpenseEvent objects."""
        api_key = os.getenv("NVIDIA_API_KEY")
        model   = os.getenv("NEMOTRON_MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1")

        if api_key:
            try:
                return self._parse_with_llm(text, api_key, model)
            except Exception as e:
                print(f"⚠️  LLM parse failed ({e}), falling back to heuristic")

        return self._parse_heuristic(text)

    def _parse_with_llm(self, text: str, api_key: str, model: str) -> list[ExpenseEvent]:
        from openai import OpenAI
        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)

        prompt = f"""Parse these business expense descriptions into a JSON array.
Return ONLY a valid JSON array, no preamble, no markdown fences.

Input: "{text}"

Each object:
  description   string   expense name
  amount        number   amount in USD (convert "28k"→28000, "$4.5k"→4500)
  day_of_month  integer  day of month due (1-28). Use 1 if unclear.
  recurring     boolean  true for repeating, false for one-off
  interval      string   "monthly" | "biweekly" | "weekly" | "once"
  category      string   "payroll" | "rent" | "saas" | "tax" | "subscription" | "general"

Rules:
- Biweekly payroll → TWO entries with different day_of_month values
- Do not include Stripe fees (handled automatically)
- If amount is a range, use the midpoint

Example for "payroll $28k twice monthly on 1st and 15th, rent $4500 7th":
[
  {{"description":"Payroll","amount":28000,"day_of_month":1,"recurring":true,"interval":"biweekly","category":"payroll"}},
  {{"description":"Payroll","amount":28000,"day_of_month":15,"recurring":true,"interval":"biweekly","category":"payroll"}},
  {{"description":"Office Rent","amount":4500,"day_of_month":7,"recurring":true,"interval":"monthly","category":"rent"}}
]"""

        resp = client.chat.completions.create(
            model    = model,
            messages = [{"role": "user", "content": prompt}],
            temperature = 0.1,
            max_tokens  = 800,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        return self._dicts_to_events(parsed)

    def _parse_heuristic(self, text: str) -> list[ExpenseEvent]:
        """Regex fallback — no API key needed."""
        events = []
        for chunk in re.split(r'[,;\n]', text):
            chunk = chunk.strip()
            if not chunk:
                continue
            amt_m = re.search(r'\$?([\d,]+\.?\d*)\s*(k)?\b', chunk, re.I)
            if not amt_m:
                continue
            amount  = float(amt_m.group(1).replace(",", ""))
            if amt_m.group(2):
                amount *= 1000
            day_m   = re.search(r'\b(\d{1,2})(st|nd|rd|th)?\b', chunk)
            dom     = int(day_m.group(1)) if day_m and 1 <= int(day_m.group(1)) <= 28 else 1
            biweekly = any(w in chunk.lower() for w in ["biweekly","twice","2x","fortnightly"])
            recurring = "once" not in chunk.lower()
            interval  = "biweekly" if biweekly else "monthly"
            desc      = re.sub(r'\$[\d,\.]+k?\s*', '', chunk, flags=re.I).strip()[:50] or "Expense"
            category  = self._infer_category(desc)
            today     = date.today()
            target    = today.replace(day=dom) if dom else today + timedelta(days=30)
            if target <= today:
                m = (today.month % 12) + 1
                y = today.year + (1 if today.month == 12 else 0)
                target = target.replace(year=y, month=m)
            events.append(ExpenseEvent(
                description=desc, amount=amount, due_date=target,
                source="nlp", recurring=recurring, interval=interval,
                category=category, confidence=0.8,
            ))
        return events

    @staticmethod
    def _dicts_to_events(parsed: list[dict]) -> list[ExpenseEvent]:
        today  = date.today()
        events = []
        for d in parsed:
            dom    = int(d.get("day_of_month", 1))
            target = today.replace(day=dom)
            if target <= today:
                m = (today.month % 12) + 1
                y = today.year + (1 if today.month == 12 else 0)
                target = target.replace(year=y, month=m)
            events.append(ExpenseEvent(
                description = d["description"],
                amount      = float(d["amount"]),
                due_date    = target,
                source      = "nlp",
                recurring   = d.get("recurring", True),
                interval    = d.get("interval", "monthly"),
                category    = d.get("category", "general"),
                confidence  = 0.9,
            ))
        return events

    @staticmethod
    def _infer_category(desc: str) -> str:
        lower = desc.lower()
        if any(w in lower for w in ["payroll","salary","wages"]): return "payroll"
        if any(w in lower for w in ["rent","lease","office"]):    return "rent"
        if any(w in lower for w in ["aws","gcp","azure","cloud"]): return "saas"
        if any(w in lower for w in ["tax","irs","vat","gst"]):    return "tax"
        return "general"

    def save_to_config(self, events: list[ExpenseEvent]):
        """Persist parsed events to config.yaml expenses list."""
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
        else:
            cfg = {}

        cfg["expenses"] = [
            {
                "description":  e.description,
                "amount":       e.amount,
                "day_of_month": e.due_date.day,
                "recurring":    e.recurring,
                "interval":     e.interval,
                "category":     e.category,
            }
            for e in events
        ]

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        print(f"✓ {len(events)} expense(s) saved to {CONFIG_PATH}")
        for e in events:
            print(f"  · [{e.category}] {e.description:<30} ${e.amount:>10,.0f}  day {e.due_date.day}")
