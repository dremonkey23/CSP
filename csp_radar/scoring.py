from __future__ import annotations
from datetime import date
from .models import OptionCandidate, ScoredCandidate

def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))

def days_until(d: date | None, today: date) -> int | None:
    if not d:
        return None
    return (d - today).days

def score_candidate(c: OptionCandidate, cfg: dict, today: date) -> ScoredCandidate:
    filters = cfg.get('filters', {})
    mid = c.mid or ((c.bid + c.ask) / 2)
    cash_required = c.strike * 100
    premium_received = mid * 100
    breakeven = c.strike - mid
    return_if_expires = mid / c.strike if c.strike else 0.0
    annualized_return = return_if_expires * (365 / c.dte) if c.dte else 0.0
    distance_otm = (c.stock_price - c.strike) / c.stock_price if c.stock_price else 0.0
    assignment_discount = (c.stock_price - breakeven) / c.stock_price if c.stock_price else 0.0
    spread_pct = ((c.ask - c.bid) / mid * 100) if mid else 999.0

    reject = None
    if c.bid < filters.get('min_bid', 0.2): reject = 'bid below minimum'
    elif not filters.get('allow_itm', False) and c.strike >= c.stock_price: reject = 'strike not OTM'
    elif spread_pct > filters.get('max_bid_ask_spread_pct', 20): reject = f'spread too wide ({spread_pct:.1f}%)'
    elif (c.open_interest or 0) < filters.get('min_open_interest', 100): reject = 'open interest too low'
    elif (c.volume or 0) < filters.get('min_volume', 20): reject = 'volume too low'
    elif c.delta is not None and not (filters.get('min_delta', -0.35) <= c.delta <= filters.get('max_delta', -0.15)): reject = 'delta outside target range'
    elif not (filters.get('min_dte', 14) <= c.dte <= filters.get('max_dte', 45)): reject = 'DTE outside target range'
    else:
        e_days = days_until(c.earnings_date, today)
        if e_days is not None and 0 <= e_days <= filters.get('avoid_earnings_within_days', 14):
            reject = f'earnings too close ({e_days}d)'

    # Premium Edge: high annualized yield, but capped to avoid worshipping junk.
    premium_score = clamp((annualized_return * 100) / 80 * 100)
    if c.iv is not None:
        premium_score = 0.75 * premium_score + 0.25 * clamp(c.iv * 100)

    # Assignment Quality: reward OTM cushion + breakeven discount.
    assignment_score = clamp((assignment_discount * 100) / 20 * 100) * 0.65 + clamp((distance_otm * 100) / 15 * 100) * 0.35

    # Liquidity: tight spreads, OI, volume.
    spread_score = clamp(100 - (spread_pct / filters.get('max_bid_ask_spread_pct', 20) * 100))
    oi_score = clamp(((c.open_interest or 0) / 1000) * 100)
    vol_score = clamp(((c.volume or 0) / 250) * 100)
    liquidity_score = 0.45 * spread_score + 0.35 * oi_score + 0.20 * vol_score

    event_score = 100.0
    e_days = days_until(c.earnings_date, today)
    if e_days is not None:
        if 0 <= e_days <= 14: event_score = 0.0
        elif 15 <= e_days <= 21: event_score = 65.0

    total = 0.30 * premium_score + 0.30 * assignment_score + 0.20 * liquidity_score + 0.20 * event_score
    if reject:
        total = min(total, 49.0)

    return ScoredCandidate(c, cash_required, premium_received, breakeven, return_if_expires, annualized_return, distance_otm, assignment_discount, spread_pct, premium_score, assignment_score, liquidity_score, event_score, total, reject)
