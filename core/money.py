"""Money is integer paise everywhere. ₹ appears only at the UI layer (fmt_inr)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def rupees_to_paise(rupees: int | str | Decimal) -> int:
    """'450' -> 45000, '12.5' -> 1250. Floats are rejected on purpose."""
    if isinstance(rupees, float):
        raise TypeError("pass rupees as int, str or Decimal, never float")
    d = Decimal(str(rupees)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)


def _group_indian(n: int) -> str:
    """1250000 -> '12,50,000' (lakh grouping), independent of system locale."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def fmt_inr(paise: int, *, always_paise: bool = False) -> str:
    """12500000 -> '₹1,25,000'; 45050 -> '₹450.50'; -45000 -> '-₹450'."""
    if not isinstance(paise, int):
        raise TypeError("paise must be int")
    sign = "-" if paise < 0 else ""
    p = abs(paise)
    rupees, rem = divmod(p, 100)
    out = f"{sign}₹{_group_indian(rupees)}"
    if rem or always_paise:
        out += f".{rem:02d}"
    return out


def round_to_rupee(paise: int | float) -> int:
    """Round a computed paise value (e.g. an expected value) to whole rupees, still in paise."""
    return int(Decimal(str(paise)).quantize(Decimal("1E2"), rounding=ROUND_HALF_UP))


def round_to_hundred_rupees(paise: int | float) -> int:
    """For forecast display: ₹23,871 -> ₹23,900 (avoids fake precision)."""
    return int(Decimal(str(paise)).quantize(Decimal("1E4"), rounding=ROUND_HALF_UP))
