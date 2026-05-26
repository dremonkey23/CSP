from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from statistics import median
from typing import Any

import requests


class NasdaqEarningsClient:
    """No-key fallback earnings-calendar client.

    Nasdaq's public calendar endpoint is not a substitute for a paid data feed,
    but it is good enough to keep the dashboard's earnings-date column populated
    when Finnhub credentials are absent or unavailable in GitHub Actions.
    """

    BASE = 'https://api.nasdaq.com/api/calendar/earnings'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://www.nasdaq.com',
            'Referer': 'https://www.nasdaq.com/',
        })
        self._date_cache: dict[str, list[dict[str, Any]]] = {}
        self._symbol_cache: dict[tuple[str, int], dict[str, date]] = {}
        self._estimate_cache: dict[str, date | None] = {}

    @staticmethod
    def _normalize(symbol: str) -> str:
        return symbol.upper().replace('-', '.').strip()

    def _rows_for_date(self, day: date) -> list[dict[str, Any]]:
        key = day.isoformat()
        if key in self._date_cache:
            return self._date_cache[key]
        r = self.session.get(self.BASE, params={'date': key}, timeout=20)
        r.raise_for_status()
        payload = r.json()
        rows = ((payload.get('data') or {}).get('rows')) or []
        self._date_cache[key] = rows if isinstance(rows, list) else []
        return self._date_cache[key]

    def _build_symbol_cache(self, start: date, days: int) -> dict[str, date]:
        cache_key = (start.isoformat(), days)
        if cache_key in self._symbol_cache:
            return self._symbol_cache[cache_key]

        weekdays = [start + timedelta(days=offset) for offset in range(days + 1) if (start + timedelta(days=offset)).weekday() < 5]
        by_symbol: dict[str, date] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self._rows_for_date, day): day for day in weekdays}
            for future in as_completed(futures):
                day = futures[future]
                try:
                    rows = future.result()
                except Exception:
                    continue
                for row in rows:
                    row_symbol = self._normalize(str(row.get('symbol') or ''))
                    if row_symbol and (row_symbol not in by_symbol or day < by_symbol[row_symbol]):
                        by_symbol[row_symbol] = day

        self._symbol_cache[cache_key] = by_symbol
        return by_symbol

    def _estimated_next_earnings_date(self, symbol: str, start: date) -> date | None:
        target = self._normalize(symbol)
        if target in self._estimate_cache:
            return self._estimate_cache[target]

        url = f'https://api.nasdaq.com/api/company/{target}/earnings-surprise'
        try:
            r = self.session.get(url, timeout=20)
            r.raise_for_status()
            payload = r.json()
        except Exception:
            self._estimate_cache[target] = None
            return None

        rows = (((payload.get('data') or {}).get('earningsSurpriseTable') or {}).get('rows')) or []
        reported: list[date] = []
        for row in rows:
            raw = str(row.get('dateReported') or '').strip()
            if not raw:
                continue
            try:
                month, day, year = [int(part) for part in raw.split('/')]
                reported.append(date(year, month, day))
            except Exception:
                continue
        reported = sorted(set(reported))
        if not reported:
            self._estimate_cache[target] = None
            return None

        gaps = [(b - a).days for a, b in zip(reported, reported[1:]) if 60 <= (b - a).days <= 130]
        cadence = int(round(median(gaps))) if gaps else 91
        next_date = reported[-1] + timedelta(days=cadence)
        while next_date < start:
            next_date += timedelta(days=cadence)

        self._estimate_cache[target] = next_date
        return next_date

    def next_earnings_date(self, symbol: str, start: date | None = None, days: int = 90) -> date | None:
        start = start or date.today()
        confirmed = self._build_symbol_cache(start, days).get(self._normalize(symbol))
        if confirmed:
            return confirmed
        estimated = self._estimated_next_earnings_date(symbol, start)
        if estimated and estimated <= start + timedelta(days=days):
            return estimated
        return None
