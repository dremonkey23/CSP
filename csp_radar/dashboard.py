from __future__ import annotations

import base64
import hmac
import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / 'web'
REPORTS_DIR = ROOT / 'reports'
DEFAULT_CONFIG = ROOT / 'config.alpaca.yaml'


def _json_default(obj):
    return str(obj)


def latest_report_path() -> Path | None:
    reports = sorted(REPORTS_DIR.glob('*.json'))
    return reports[-1] if reports else None


def report_path_for(date_str: str | None) -> Path | None:
    if date_str:
        candidate = REPORTS_DIR / f'{date_str}.json'
        return candidate if candidate.exists() else None
    return latest_report_path()


def load_report(date_str: str | None = None) -> tuple[Path, list[dict]]:
    path = report_path_for(date_str)
    if not path:
        raise FileNotFoundError('No CSP Radar JSON reports found. Run a scan first.')
    return path, json.loads(path.read_text())


def money(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def summarize_item(row: dict) -> dict:
    c = row.get('candidate') or {}
    return {
        'ticker': c.get('ticker'),
        'stock_price': money(c.get('stock_price')),
        'expiry': c.get('expiry'),
        'dte': c.get('dte'),
        'strike': money(c.get('strike')),
        'bid': money(c.get('bid')),
        'ask': money(c.get('ask')),
        'mid': money(c.get('mid')),
        'delta': c.get('delta'),
        'iv': c.get('iv'),
        'open_interest': c.get('open_interest'),
        'volume': c.get('volume'),
        'earnings_date': c.get('earnings_date'),
        'cash_required': money(row.get('cash_required')),
        'premium_received': money(row.get('premium_received')),
        'breakeven': money(row.get('breakeven')),
        'return_if_expires': money(row.get('return_if_expires')),
        'annualized_return': money(row.get('annualized_return')),
        'distance_otm': money(row.get('distance_otm')),
        'assignment_discount': money(row.get('assignment_discount')),
        'spread_pct': money(row.get('spread_pct')),
        'premium_score': money(row.get('premium_score')),
        'assignment_score': money(row.get('assignment_score')),
        'liquidity_score': money(row.get('liquidity_score')),
        'event_score': money(row.get('event_score')),
        'total_score': money(row.get('total_score')),
        'reject_reason': row.get('reject_reason'),
    }


def build_payload(date_str: str | None = None) -> dict:
    path, rows = load_report(date_str)
    items = [summarize_item(r) for r in rows]
    accepted = [x for x in items if not x.get('reject_reason')]
    rejects = [x for x in items if x.get('reject_reason')]

    accepted_by_score = sorted(accepted, key=lambda x: x['total_score'], reverse=True)
    high_premium = sorted(
        [x for x in accepted if x['spread_pct'] <= 35],
        key=lambda x: (x['annualized_return'], x['total_score']),
        reverse=True,
    )
    best_assignment = sorted(
        accepted,
        key=lambda x: (x['assignment_discount'], x['total_score']),
        reverse=True,
    )
    reject_reasons: dict[str, int] = {}
    for r in rejects:
        reason = r.get('reject_reason') or 'unknown'
        reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    missing_delta = sum(1 for x in items if x.get('delta') is None)
    missing_oi = sum(1 for x in items if x.get('open_interest') is None)
    symbols = sorted({x.get('ticker') for x in items if x.get('ticker')})

    return {
        'date': path.stem,
        'source_file': str(path),
        'updated_at_epoch': path.stat().st_mtime,
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(path.stat().st_mtime)),
        'stats': {
            'total_candidates': len(items),
            'accepted_count': len(accepted),
            'reject_count': len(rejects),
            'symbols_count': len(symbols),
            'symbols': symbols,
            'missing_delta_pct': round((missing_delta / len(items) * 100), 1) if items else 0,
            'missing_open_interest_pct': round((missing_oi / len(items) * 100), 1) if items else 0,
            'reject_reasons': sorted(reject_reasons.items(), key=lambda kv: kv[1], reverse=True)[:10],
            'data_quality_note': 'Alpaca bridge mode: Greeks/open interest may be absent. Upgrade to Tradier/Schwab for higher-confidence rankings.' if missing_delta or missing_oi else 'Greeks/open-interest present in report.',
        },
        'sections': {
            'best_overall': accepted_by_score[:100],
            'highest_premium': high_premium[:100],
            'best_assignment': best_assignment[:100],
            'rejects': sorted(rejects, key=lambda x: x['total_score'], reverse=True)[:100],
        },
    }


def list_reports() -> list[dict]:
    out = []
    for path in sorted(REPORTS_DIR.glob('*.json'), reverse=True):
        out.append({
            'date': path.stem,
            'file': str(path),
            'bytes': path.stat().st_size,
            'updated_at': time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(path.stat().st_mtime)),
        })
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = 'CSPRadarDashboard/0.1'

    def is_authorized(self) -> bool:
        user = os.environ.get('CSP_DASHBOARD_USER')
        password = os.environ.get('CSP_DASHBOARD_PASSWORD')
        if not user or not password:
            return True
        header = self.headers.get('Authorization') or ''
        if not header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(header.split(' ', 1)[1]).decode('utf-8')
            supplied_user, supplied_password = decoded.split(':', 1)
        except Exception:
            return False
        return hmac.compare_digest(supplied_user, user) and hmac.compare_digest(supplied_password, password)

    def require_auth(self) -> bool:
        if self.is_authorized():
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="CSP Radar"')
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'Authentication required')
        return False

    def log_message(self, fmt, *args):
        print(f'{self.address_string()} - {fmt % args}')

    def send_json(self, payload: dict | list, status: int = 200):
        body = json.dumps(payload, default=_json_default).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, status: int = 200, content_type: str = 'text/plain; charset=utf-8'):
        body = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.require_auth():
            return
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            path = WEB_DIR / 'index.html'
            if not path.exists():
                self.send_text('Dashboard HTML missing.', 500)
                return
            self.send_text(path.read_text(), 200, 'text/html; charset=utf-8')
            return
        if parsed.path == '/api/reports':
            self.send_json(list_reports())
            return
        if parsed.path == '/api/report':
            try:
                qs = parse_qs(parsed.query)
                self.send_json(build_payload((qs.get('date') or [None])[0]))
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
            return
        self.send_text('Not found', 404)

    def do_POST(self):
        if not self.require_auth():
            return
        parsed = urlparse(self.path)
        if parsed.path != '/api/scan':
            self.send_text('Not found', 404)
            return
        config = DEFAULT_CONFIG
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length:
                payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                requested = payload.get('config')
                if requested:
                    candidate = (ROOT / requested).resolve()
                    if ROOT not in candidate.parents and candidate != ROOT:
                        raise ValueError('Config path must stay inside CSP Radar project')
                    config = candidate
            started = time.time()
            proc = subprocess.run(
                ['python', '-m', 'csp_radar.scanner', '--config', str(config)],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
            )
            self.send_json({
                'ok': proc.returncode == 0,
                'returncode': proc.returncode,
                'seconds': round(time.time() - started, 2),
                'config': str(config),
                'stdout_tail': proc.stdout[-6000:],
                'stderr_tail': proc.stderr[-3000:],
                'latest_report': str(latest_report_path()) if latest_report_path() else None,
            }, 200 if proc.returncode == 0 else 500)
        except Exception as e:
            self.send_json({'ok': False, 'error': str(e)}, 500)


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Local CSP Radar dashboard')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8787)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'CSP Radar dashboard: http://{args.host}:{args.port}')
    print('Read-only dashboard. POST /api/scan refreshes market-data reports; it does not place trades.')
    httpd.serve_forever()


if __name__ == '__main__':
    main()
