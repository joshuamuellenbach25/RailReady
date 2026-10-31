"""Server-authoritative money. Decimal, ROUND_HALF_UP, USD. Decimals stored as strings."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")


class MoneyError(ValueError):
    def __init__(self, field: str, msg: str):
        super().__init__(f"{field}: {msg}")
        self.field, self.msg = field, msg


def dec(value, field: str, *, positive=False, nonneg=False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise MoneyError(field, "required number")
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise MoneyError(field, "must be a number")
    if not d.is_finite():
        raise MoneyError(field, "must be finite")
    exp = d.as_tuple().exponent
    if isinstance(exp, int) and exp < -4:
        raise MoneyError(field, "max 4 decimal places")
    if positive and d <= 0:
        raise MoneyError(field, "must be greater than 0")
    if nonneg and d < 0:
        raise MoneyError(field, "must not be negative")
    return d


def r2(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def s(d: Decimal) -> str:
    return format(d, "f")


def line_amounts(line: dict) -> dict:
    q, c, m = Decimal(line["quantity"]), Decimal(line["unit_cost"]), Decimal(line["markup_pct"])
    return {"internal_cost": s(r2(q * c)), "line_total": s(r2(q * c * (1 + m / 100)))}


def totals(lines: list, tax_rate: str) -> dict:
    inc = [l for l in lines if l.get("included", True)]
    sub = sum((Decimal(line_amounts(l)["line_total"]) for l in inc), Decimal("0"))
    cost = sum((Decimal(line_amounts(l)["internal_cost"]) for l in inc), Decimal("0"))
    taxable = sum((Decimal(line_amounts(l)["line_total"]) for l in inc if l["taxable"]), Decimal("0"))
    tax = r2(taxable * Decimal(tax_rate) / 100)
    sub = r2(sub)
    margin = "N/A" if sub == 0 else s(((sub - cost) / sub * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return {"subtotal": s(sub), "taxable_subtotal": s(r2(taxable)), "tax_rate": tax_rate, "tax": s(tax),
            "total": s(sub + tax), "internal_cost": s(r2(cost)), "margin_pct": margin, "currency": "USD"}
