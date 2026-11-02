"""API usage and spending limits. Every paid call goes through `Budget.charge`."""
from __future__ import annotations

from typing import Any

from .config import Config
from .state import today


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, cfg: Config, state_data: dict[str, Any]):
        self.cfg = cfg
        self.usage = state_data.setdefault("usage", {})
        self.month = today()[:7]
        self.calls_this_run = 0

    def _m(self) -> dict[str, float]:
        return self.usage.setdefault(self.month, {"claude_calls": 0, "input_tokens": 0, "output_tokens": 0, "usd_estimate": 0.0})

    def check(self) -> None:
        lim = self.cfg.get("limits", {}) or {}
        if self.calls_this_run >= lim.get("max_claude_calls_per_run", 12):
            raise BudgetExceeded("per-run Claude call limit reached")
        if self._m()["usd_estimate"] >= lim.get("max_monthly_usd", 10):
            raise BudgetExceeded(f"monthly budget ${lim.get('max_monthly_usd')} reached")

    def charge(self, input_tokens: int, output_tokens: int) -> None:
        lim = self.cfg.get("limits", {}) or {}
        m = self._m()
        self.calls_this_run += 1
        m["claude_calls"] += 1
        m["input_tokens"] += input_tokens
        m["output_tokens"] += output_tokens
        m["usd_estimate"] = round(m["usd_estimate"] + input_tokens / 1e6 * lim.get("input_usd_per_mtok", 3.0)
                                  + output_tokens / 1e6 * lim.get("output_usd_per_mtok", 15.0), 4)

    def summary(self) -> dict[str, Any]:
        return {"month": self.month, **self._m(), "calls_this_run": self.calls_this_run}


_current: Budget | None = None


def set_current(b: Budget | None) -> None:
    global _current
    _current = b


def current() -> Budget | None:
    return _current
