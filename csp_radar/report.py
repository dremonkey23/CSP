from __future__ import annotations
from .models import ScoredCandidate

def fmt_pct(x): return f'{x*100:.1f}%'
def fmt_money(x): return f'${x:,.2f}'

def render_markdown(scored: list[ScoredCandidate], limit: int = 10) -> str:
    rows = sorted(scored, key=lambda x: x.total_score, reverse=True)
    good = [r for r in rows if not r.reject_reason][:limit]
    rejects = [r for r in rows if r.reject_reason][:limit]
    lines = ['# CSP Radar', '', '## Best Overall']
    for i, s in enumerate(good, 1):
        c=s.candidate
        lines += [
            f'{i}. **{c.ticker} ${c.strike:g}P — {c.expiry.isoformat()} ({c.dte} DTE)**',
            f'   Score: {s.total_score:.0f}/100 | Annualized: {fmt_pct(s.annualized_return)} | Premium: {fmt_money(s.premium_received)} | Cash required: {fmt_money(s.cash_required)}',
            f'   Breakeven: ${s.breakeven:.2f} | Assignment discount: {fmt_pct(s.assignment_discount)} | Delta: {c.delta} | OI: {c.open_interest} | Vol: {c.volume} | Spread: {s.spread_pct:.1f}%',
            ''
        ]
    lines += ['', '## Rejects / Landmines']
    for s in rejects[:limit]:
        c=s.candidate
        lines.append(f'- {c.ticker} ${c.strike:g}P {c.expiry.isoformat()}: {s.reject_reason}')
    return '\n'.join(lines) + '\n'
