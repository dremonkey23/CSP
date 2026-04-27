from __future__ import annotations
import argparse, json
from dataclasses import asdict
from datetime import date
from pathlib import Path
import yaml
from .data_sources.tradier import TradierClient
from .data_sources.alpaca import AlpacaClient
from .data_sources.finnhub import FinnhubClient
from .scoring import score_candidate
from .report import render_markdown

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
    earnings=None
    try:
        earnings=FinnhubClient()
    except RuntimeError:
        pass
    all_scored=[]
    for ticker in cfg['universe']['tickers']:
        price=market_data.get_quote(ticker)
        next_earn = earnings.next_earnings_date(ticker, today) if earnings else None
        for exp in market_data.expirations(ticker):
            exp_date=date.fromisoformat(exp)
            dte=(exp_date-today).days
            if not (cfg['filters']['min_dte'] <= dte <= cfg['filters']['max_dte']):
                continue
            for cand in market_data.chain(ticker, exp, price):
                cand.earnings_date=next_earn
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
