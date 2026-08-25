"""A-share board quantity rules used by strict paper execution."""
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN

def board(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("688", "689")): return "STAR"
    if code.startswith(("4", "8", "92")): return "BSE"
    if code.startswith(("300", "301")): return "CHINEXT"
    return "MAIN"

def minimum_buy(code: str) -> int:
    return 200 if board(code) == "STAR" else 100

def valid_buy(code: str, shares: int) -> bool:
    if shares < minimum_buy(code): return False
    return shares % 100 == 0 if board(code) in {"MAIN", "CHINEXT"} else True

def valid_sell(code: str, shares: int, position_shares: int) -> bool:
    if shares <= 0 or shares > position_shares: return False
    # The engine only closes full strict-paper positions. This also satisfies
    # the exchange requirement that a residual odd lot is sold in one order.
    if shares == position_shares: return True
    return valid_buy(code, shares)

def floor_quantity(code: str, raw_shares) -> int:
    raw = int(Decimal(str(raw_shares)).to_integral_value(rounding=ROUND_DOWN))
    if board(code) in {"MAIN", "CHINEXT"}: raw = raw // 100 * 100
    return raw if raw >= minimum_buy(code) else 0
