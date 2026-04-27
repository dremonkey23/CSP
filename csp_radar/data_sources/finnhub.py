from __future__ import annotations
import os, requests
from datetime import date, timedelta

class FinnhubClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get('FINNHUB_API_KEY')
        if not self.token:
            raise RuntimeError('Missing FINNHUB_API_KEY')

    def next_earnings_date(self, symbol: str, start: date | None = None, days: int = 90) -> date | None:
        start = start or date.today()
        end = start + timedelta(days=days)
        url = 'https://finnhub.io/api/v1/calendar/earnings'
        r = requests.get(url, params={'symbol': symbol, 'from': start.isoformat(), 'to': end.isoformat(), 'token': self.token}, timeout=20)
        r.raise_for_status()
        rows = r.json().get('earningsCalendar') or []
        dates = sorted(date.fromisoformat(x['date']) for x in rows if x.get('date'))
        return dates[0] if dates else None
