from dataclasses import dataclass
from datetime import date

@dataclass
class OptionCandidate:
    ticker: str
    stock_price: float
    expiry: date
    dte: int
    strike: float
    bid: float
    ask: float
    mid: float
    delta: float | None
    iv: float | None
    open_interest: int | None
    volume: int | None
    earnings_date: date | None = None

@dataclass
class ScoredCandidate:
    candidate: OptionCandidate
    cash_required: float
    premium_received: float
    breakeven: float
    return_if_expires: float
    annualized_return: float
    distance_otm: float
    assignment_discount: float
    spread_pct: float
    premium_score: float
    assignment_score: float
    liquidity_score: float
    event_score: float
    total_score: float
    reject_reason: str | None = None
