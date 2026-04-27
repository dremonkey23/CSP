from __future__ import annotations
import os, requests
from datetime import date
from csp_radar.models import OptionCandidate

BASE = 'https://api.tradier.com/v1'

class TradierClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get('TRADIER_TOKEN') or os.environ.get('TRADIER_ACCESS_TOKEN')
        if not self.token:
            raise RuntimeError('Missing TRADIER_TOKEN or TRADIER_ACCESS_TOKEN')
        self.headers = {'Authorization': f'Bearer {self.token}', 'Accept': 'application/json'}

    def get_quote(self, symbol: str) -> float:
        r = requests.get(f'{BASE}/markets/quotes', headers=self.headers, params={'symbols': symbol}, timeout=20)
        r.raise_for_status()
        q = (r.json().get('quotes') or {}).get('quote') or {}
        return float(q.get('last') or q.get('bid') or q.get('ask'))

    def expirations(self, symbol: str) -> list[str]:
        r = requests.get(f'{BASE}/markets/options/expirations', headers=self.headers, params={'symbol': symbol, 'includeAllRoots': 'false', 'strikes': 'false'}, timeout=20)
        r.raise_for_status()
        exp = ((r.json().get('expirations') or {}).get('date')) or []
        return exp if isinstance(exp, list) else [exp]

    def chain(self, symbol: str, expiration: str, stock_price: float) -> list[OptionCandidate]:
        r = requests.get(f'{BASE}/markets/options/chains', headers=self.headers, params={'symbol': symbol, 'expiration': expiration, 'greeks': 'true'}, timeout=30)
        r.raise_for_status()
        opts = ((r.json().get('options') or {}).get('option')) or []
        if isinstance(opts, dict): opts = [opts]
        out = []
        exp_date = date.fromisoformat(expiration)
        today = date.today()
        for o in opts:
            if o.get('option_type') != 'put':
                continue
            bid, ask = float(o.get('bid') or 0), float(o.get('ask') or 0)
            mid = (bid + ask) / 2 if bid and ask else float(o.get('last') or 0)
            greeks = o.get('greeks') or {}
            out.append(OptionCandidate(
                ticker=symbol, stock_price=stock_price, expiry=exp_date, dte=(exp_date - today).days,
                strike=float(o.get('strike')), bid=bid, ask=ask, mid=mid,
                delta=float(greeks['delta']) if greeks.get('delta') is not None else None,
                iv=float(greeks['mid_iv']) if greeks.get('mid_iv') is not None else None,
                open_interest=int(o.get('open_interest') or 0), volume=int(o.get('volume') or 0),
            ))
        return out
