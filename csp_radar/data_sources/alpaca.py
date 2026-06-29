from __future__ import annotations

import os
import re
from math import erf, exp, log, sqrt
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from csp_radar.models import OptionCandidate

DEFAULT_DATA_BASE = 'https://data.alpaca.markets/v2'
CREDENTIALS_PATH = Path.home() / '.hermes' / 'workspace' / 'CREDENTIALS.md'
CREDS_RE = re.compile(
    r"## Alpaca \(Paper Trading\)\s*"
    r"- Endpoint: (?P<endpoint>\S+)\s*"
    r"- Key: (?P<key>\S+)\s*"
    r"- Secret: (?P<secret>\S+)\s*"
    r"- Data: (?P<data>\S+)",
    re.S,
)
OCC_RE = re.compile(r'^(?P<root>.+?)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$')


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _bs_put_price_delta(
    stock_price: float,
    strike: float,
    dte: int,
    sigma: float,
    risk_free_rate: float = 0.045,
) -> tuple[float, float] | None:
    """Return Black-Scholes put price and delta for fallback Greeks.

    Alpaca free/basic options snapshots give bid/ask but often omit Greeks. We
    solve an implied volatility from the observed mid and use that to display a
    model delta. This is lower-confidence than provider Greeks, but much better
    than rendering a broken all-blank Delta column.
    """
    if stock_price <= 0 or strike <= 0 or dte <= 0 or sigma <= 0:
        return None
    t = dte / 365.0
    if t <= 0:
        return None
    vol_t = sigma * sqrt(t)
    if vol_t <= 0:
        return None
    d1 = (log(stock_price / strike) + (risk_free_rate + 0.5 * sigma * sigma) * t) / vol_t
    d2 = d1 - vol_t
    put = strike * exp(-risk_free_rate * t) * _norm_cdf(-d2) - stock_price * _norm_cdf(-d1)
    delta = _norm_cdf(d1) - 1.0
    return put, delta


def _estimate_put_delta(stock_price: float, strike: float, dte: int, mid: float) -> tuple[float | None, float | None]:
    """Estimate put delta and IV from market mid using bisection.

    Returns (delta, iv). If the market price is outside sane Black-Scholes
    bounds, returns (None, None) rather than inventing a misleading value.
    """
    if stock_price <= 0 or strike <= 0 or dte <= 0 or mid <= 0:
        return None, None
    intrinsic = max(strike - stock_price, 0.0)
    # Allow a small tolerance because quotes are noisy and markets can be wide.
    if mid < intrinsic - 0.05 or mid > strike:
        return None, None

    lo, hi = 0.01, 5.0
    lo_price = _bs_put_price_delta(stock_price, strike, dte, lo)
    hi_price = _bs_put_price_delta(stock_price, strike, dte, hi)
    if not lo_price or not hi_price or mid < lo_price[0] - 0.05 or mid > hi_price[0] + 0.05:
        return None, None

    for _ in range(60):
        sigma = (lo + hi) / 2.0
        priced = _bs_put_price_delta(stock_price, strike, dte, sigma)
        if not priced:
            return None, None
        price, _ = priced
        if price < mid:
            lo = sigma
        else:
            hi = sigma

    iv = (lo + hi) / 2.0
    priced = _bs_put_price_delta(stock_price, strike, dte, iv)
    if not priced:
        return None, None
    _, delta = priced
    return delta, iv


class AlpacaClient:
    """Read-only Alpaca market-data client for CSP Radar.

    Alpaca Basic/free options snapshots currently do not expose every field we
    want for high-quality CSP ranking. In particular, Greeks and open interest
    may be absent. This adapter is still useful as a no-cost bridge while
    Tradier/Schwab are pending: it can provide stock quotes and option bid/ask
    snapshots for puts.
    """

    def __init__(self, key: str | None = None, secret: str | None = None, data_base: str | None = None):
        env_key = os.environ.get('ALPACA_API_KEY') or os.environ.get('APCA_API_KEY_ID') or os.environ.get('APCA_API_KEY')
        env_secret = os.environ.get('ALPACA_SECRET_KEY') or os.environ.get('APCA_API_SECRET_KEY') or os.environ.get('APCA_SECRET_KEY')
        env_data = os.environ.get('ALPACA_DATA_BASE_URL') or os.environ.get('APCA_API_DATA_URL')

        file_key = file_secret = file_data = None
        if (not key or not secret or not data_base) and CREDENTIALS_PATH.exists():
            m = CREDS_RE.search(CREDENTIALS_PATH.read_text())
            if m:
                file_key, file_secret, file_data = m.group('key'), m.group('secret'), m.group('data')

        self.key = key or env_key or file_key
        self.secret = secret or env_secret or file_secret
        self.data_base = (data_base or env_data or file_data or DEFAULT_DATA_BASE).rstrip('/')
        if not self.key or not self.secret:
            raise RuntimeError('Missing Alpaca API credentials: set ALPACA_API_KEY/ALPACA_SECRET_KEY or APCA_API_KEY_ID/APCA_API_SECRET_KEY')

        # CREDENTIALS.md stores https://data.alpaca.markets/v2. Some options
        # endpoints are under /v1beta1, so keep both forms.
        self.data_root = self.data_base[:-3] if self.data_base.endswith('/v2') else self.data_base
        self.session = requests.Session()
        self.session.headers.update({
            'APCA-API-KEY-ID': self.key,
            'APCA-API-SECRET-KEY': self.secret,
        })
        self._snapshot_cache: dict[str, dict[str, Any]] = {}

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_quote(self, symbol: str) -> float:
        data = self._get_json(f'{self.data_base}/stocks/{symbol}/quotes/latest')
        quote = data.get('quote') or {}
        bid = float(quote.get('bp') or 0)
        ask = float(quote.get('ap') or 0)
        if bid and ask:
            return (bid + ask) / 2
        return ask or bid

    def daily_closes(self, symbol: str, days: int = 90) -> list[float]:
        start = (date.today() - timedelta(days=days * 2)).isoformat()
        data = self._get_json(
            f'{self.data_base}/stocks/{symbol}/bars',
            params={'timeframe': '1Day', 'start': start, 'adjustment': 'raw', 'limit': days},
        )
        bars = data.get('bars') or []
        return [float(x.get('c')) for x in bars if x.get('c') is not None]

    def _fetch_put_snapshots(self, symbol: str, limit: int = 1000, max_pages: int = 3) -> dict[str, Any]:
        if symbol in self._snapshot_cache:
            return self._snapshot_cache[symbol]

        snapshots: dict[str, Any] = {}
        token = None
        for _ in range(max_pages):
            params: dict[str, Any] = {'type': 'put', 'limit': limit}
            if token:
                params['page_token'] = token
            data = self._get_json(f'{self.data_root}/v1beta1/options/snapshots/{symbol}', params=params)
            snapshots.update(data.get('snapshots') or {})
            token = data.get('next_page_token')
            if not token:
                break

        self._snapshot_cache[symbol] = snapshots
        return snapshots

    @staticmethod
    def _parse_occ(option_symbol: str) -> tuple[date, str, float] | None:
        m = OCC_RE.match(option_symbol)
        if not m:
            return None
        yy = int(m.group('yy'))
        year = 2000 + yy
        expiry = date(year, int(m.group('mm')), int(m.group('dd')))
        return expiry, m.group('cp'), int(m.group('strike')) / 1000.0

    def expirations(self, symbol: str) -> list[str]:
        expiries = set()
        for option_symbol in self._fetch_put_snapshots(symbol).keys():
            parsed = self._parse_occ(option_symbol)
            if parsed:
                exp, cp, _ = parsed
                if cp == 'P':
                    expiries.add(exp.isoformat())
        return sorted(expiries)

    def chain(self, symbol: str, expiration: str, stock_price: float) -> list[OptionCandidate]:
        exp_date = date.fromisoformat(expiration)
        today = date.today()
        out: list[OptionCandidate] = []
        for option_symbol, snap in self._fetch_put_snapshots(symbol).items():
            parsed = self._parse_occ(option_symbol)
            if not parsed:
                continue
            opt_exp, cp, strike = parsed
            if cp != 'P' or opt_exp != exp_date:
                continue

            quote = snap.get('latestQuote') or {}
            bid = float(quote.get('bp') or 0)
            ask = float(quote.get('ap') or 0)
            trade = snap.get('latestTrade') or {}
            last = float(trade.get('p') or 0)
            mid = (bid + ask) / 2 if bid and ask else last
            daily = snap.get('dailyBar') or {}
            prev_daily = snap.get('prevDailyBar') or {}
            volume = int(daily.get('v') or prev_daily.get('v') or trade.get('s') or 0)
            dte = (opt_exp - today).days
            delta, iv = _estimate_put_delta(stock_price, strike, dte, mid)

            out.append(OptionCandidate(
                ticker=symbol,
                stock_price=stock_price,
                expiry=opt_exp,
                dte=dte,
                strike=strike,
                bid=bid,
                ask=ask,
                mid=mid,
                # Alpaca free/basic snapshots omit Greeks. Fill display/ranking
                # with a model-estimated delta/IV from the live bid/ask mid.
                delta=delta,
                iv=iv,
                open_interest=None,
                volume=volume,
            ))
        return out
