from __future__ import annotations
import argparse, json
from dataclasses import asdict
from datetime import date
from pathlib import Path
import yaml
from .data_sources.tradier import TradierClient
from .data_sources.alpaca import AlpacaClient
from .data_sources.earnings import NasdaqEarningsClient
from .data_sources.finnhub import FinnhubClient
from .indicators import calculate_rsi
from .scoring import score_candidate
from .report import render_markdown


def universe_tickers(cfg: dict) -> tuple[list[str], dict[str, str]]:
    """Return a deduped ticker list plus optional category metadata.

    Supports the original flat `universe.tickers` config and the newer
    curated `universe.categories` shape used to keep the watchlist broad
    without turning it into an unbounded noisy scan.
    """
    universe = cfg.get('universe') or {}
    seen: set[str] = set()
    tickers: list[str] = []
    categories: dict[str, str] = {}

    for category, symbols in (universe.get('categories') or {}).items():
        for symbol in symbols or []:
            ticker = str(symbol).upper().strip()
            if not ticker:
                continue
            categories.setdefault(ticker, str(category))
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)

    for symbol in universe.get('tickers') or []:
        ticker = str(symbol).upper().strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    if not tickers:
        raise RuntimeError('No universe tickers configured')
    return tickers, categories


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config', default='config.yaml')
    args=ap.parse_args()
    cfg=yaml.safe_load(Path(args.config).read_text())
    today=date.today()
    provider = (cfg.get('providers', {}).get('options') or 'tradier').lower()
    if provider == 'alpaca':
        market_data = AlpacaClient()
    elif provider == 'tradier':
        market_data = TradierClient()
    else:
        raise RuntimeError(f'Unsupported options provider: {provider}')
    earnings_clients=[]
    try:
        earnings_clients.append(FinnhubClient())
    except RuntimeError:
        pass
    earnings_clients.append(NasdaqEarningsClient())
    all_scored=[]
    tickers, ticker_categories = universe_tickers(cfg)
    for ticker in tickers:
        price=market_data.get_quote(ticker)
        rsi_14=None
        if hasattr(market_data, 'daily_closes'):
            try:
                rsi_14=calculate_rsi(market_data.daily_closes(ticker), 14)
            except Exception:
                rsi_14=None
        next_earn = None
        for earnings in earnings_clients:
            next_earn = earnings.next_earnings_date(ticker, today)
            if next_earn:
                break
        for exp in market_data.expirations(ticker):
            exp_date=date.fromisoformat(exp)
            dte=(exp_date-today).days
            if not (cfg['filters']['min_dte'] <= dte <= cfg['filters']['max_dte']):
                continue
            for cand in market_data.chain(ticker, exp, price):
                cand.rsi_14=rsi_14
                cand.earnings_date=next_earn
                cand.category=ticker_categories.get(ticker)
                all_scored.append(score_candidate(cand, cfg, today))
    out_dir=Path('reports'); out_dir.mkdir(exist_ok=True)
    md=render_markdown(all_scored, cfg.get('ranking',{}).get('top_n',10))
    (out_dir/f'{today.isoformat()}.md').write_text(md)
    serial=[]
    for s in all_scored:
        d=asdict(s)
        d['candidate']['expiry']=s.candidate.expiry.isoformat()
        d['candidate']['earnings_date']=s.candidate.earnings_date.isoformat() if s.candidate.earnings_date else None
        serial.append(d)
    (out_dir/f'{today.isoformat()}.json').write_text(json.dumps(serial, indent=2))
    print(md)

if __name__ == '__main__':
    main()
