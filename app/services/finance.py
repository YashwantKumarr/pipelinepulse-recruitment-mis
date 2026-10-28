"""Placement-fee and payment DEMONSTRATIONS. Decimal arithmetic only. No invoices or transfers."""

import re
from decimal import ROUND_HALF_UP, Decimal

from app.errors import AppError

DEMO_LABEL = "DEMONSTRATION ONLY - not an invoice and not a financial transaction"
_MONEY_RE = re.compile(r"^\d{1,12}(\.\d{1,2})?$")
_PERCENT_RE = re.compile(r"^\d{1,3}(\.\d{1,2})?$")
_CENT = Decimal("0.01")


def parse_money(value: str, field: str) -> Decimal:
    raw = (value or "").strip()
    if not _MONEY_RE.match(raw):
        raise AppError(422, "invalid_amount", f"{field} must be a plain decimal with up to 2 decimal places.")
    amount = Decimal(raw)
    if amount <= 0:
        raise AppError(422, "invalid_amount", f"{field} must be greater than zero.")
    return amount.quantize(_CENT)


def parse_percent(value: str) -> Decimal:
    raw = (value or "").strip()
    if not _PERCENT_RE.match(raw):
        raise AppError(422, "invalid_percent", "fee_percent must be a plain decimal, for example 8.33.")
    percent = Decimal(raw)
    if not Decimal(0) < percent <= Decimal(100):
        raise AppError(422, "invalid_percent", "fee_percent must be greater than 0 and at most 100.")
    return percent


def compute_draft_amount(annual_ctc: Decimal, fee_percent: Decimal) -> Decimal:
    return (annual_ctc * fee_percent / Decimal(100)).quantize(_CENT, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal) -> str:
    return f"{amount:.2f}"
